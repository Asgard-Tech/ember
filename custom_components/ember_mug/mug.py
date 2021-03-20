"""Reusable class for Ember Mug connection and data."""

import asyncio
import contextlib
from typing import Callable

from bleak import BleakClient
from bleak.exc import BleakError
from homeassistant.helpers.typing import HomeAssistantType

from . import _LOGGER
from .const import (
    BATTERY_UUID,
    CURRENT_TEMP_UUID,
    LED_COLOUR_UUID,
    STATE_UUID,
    TARGET_TEMP_UUID,
    UNKNOWN_READ_UUIDS,
)


class EmberMug:
    """Class to connect and communicate with the mug via Bluetooth."""

    def __init__(
        self,
        mac_address: str,
        use_metric: bool,
        async_update_callback: Callable,
        hass: HomeAssistantType,
    ) -> None:
        """Set default values in for mug attributes."""
        self._loop = False
        self.hass = hass
        self.async_update_callback = async_update_callback
        self.mac_address = mac_address
        self.client = BleakClient(mac_address)
        self.use_metric = use_metric
        self.state = None
        self.charging = False  # TODO from state?
        self.led_colour_rgb = [255, 255, 255]
        self.current_temp: float = None
        self.target_temp: float = None
        self.battery: float = None
        self.available = False
        self.uuid_debug = {uuid: None for uuid in UNKNOWN_READ_UUIDS}

        # Start loop
        self.hass.async_create_task(self.async_run())

    @property
    def colour(self) -> str:
        """Return colour as hex value."""
        r, g, b = self.led_colour_rgb
        return f"#{r:02x}{g:02x}{b:02x}"

    async def async_run(self) -> None:
        """Start a the task loop."""
        try:
            self._loop = True
            _LOGGER.info(f"Starting mug loop {self.mac_address}")

            while self._loop:
                if not await self.client.is_connected():
                    await self.connect()

                await self.update_all()
                self.async_update_callback()

                # Maintain connection for 30 seconds until next update
                for _ in range(15):
                    await self.client.is_connected()
                    await asyncio.sleep(2)

        except Exception as e:
            _LOGGER.error(f"An unexpected error occurred during loop {e}. Restarting.")
            self.hass.async_create_task(self.async_run())

    async def _temp_from_bytes(self, temp_bytes: bytearray) -> float:
        """Get temperature from bytearray and convert to fahrenheit if needed."""
        temp = (
            float(int.from_bytes(temp_bytes, byteorder="little", signed=False)) * 0.01
        )
        if self.use_metric is False:
            # Convert to fahrenheit
            temp = (temp * 9 / 5) + 32
        return round(temp, 2)

    async def update_battery(self) -> None:
        """Get Battery percent from mug gatt."""
        current_battery = await self.client.read_gatt_char(BATTERY_UUID)
        battery_percent = float(current_battery[0])
        _LOGGER.debug(f"Battery is at {battery_percent}")
        self.battery = round(battery_percent, 2)

    async def update_led_colour(self) -> None:
        """Get RGBA colours from mug gatt."""
        r, g, b, _ = await self.client.read_gatt_char(LED_COLOUR_UUID)
        self.led_colour_rgb = [r, g, b]

    async def update_target_temp(self) -> None:
        """Get target temp form mug gatt."""
        temp_bytes = await self.client.read_gatt_char(TARGET_TEMP_UUID)
        self.target_temp = await self._temp_from_bytes(temp_bytes)
        _LOGGER.debug(f"Target temp {self.target_temp}")

    async def update_current_temp(self) -> None:
        """Get current temp from mug gatt."""
        temp_bytes = await self.client.read_gatt_char(CURRENT_TEMP_UUID)
        self.current_temp = await self._temp_from_bytes(temp_bytes)
        _LOGGER.debug(f"Current temp {self.current_temp}")

    async def update_uuid_debug(self) -> None:
        """Not sure what all these UUIDs do, so fetch and log them for future investigation."""
        for uuid in self.uuid_debug:
            try:
                value = await self.client.read_gatt_char(uuid)
                _LOGGER.debug(f"Current value of {uuid}: {value}")
                self.uuid_debug[uuid] = str(value)
            except BleakError as e:
                _LOGGER.error(f"Failed to update {uuid}: {e}")

    async def connect(self) -> None:
        """Try 10 times to connect and if we fail wait five minutes and try again. If connected also subscribe to state notifications."""
        connected = False
        for i in range(1, 10 + 1):
            try:
                await self.client.connect()
                await self.client.pair()
                connected = True
                _LOGGER.info(f"Connected to {self.mac_address}")
                continue
            except BleakError as e:
                _LOGGER.error(f"Init: {e} on attempt {i}. waiting 30sec")
                asyncio.sleep(30)

        if connected is False:
            # self.available = False
            self.async_update_callback()
            _LOGGER.warning(
                f"Failed to connect to {self.mac_address} after 10 tries. Will try again in 5min"
            )
            await asyncio.sleep(5 * 60)
            await self.connect()

        try:
            _LOGGER.info("Try to subscribe to STATE")
            await self.client.start_notify(STATE_UUID, self.state_notify)
        except BleakError:
            _LOGGER.warning("Failed to subscribe to state attr")
        except Exception as e:
            _LOGGER.error(f"Unexpected error occurred connecting to notify {e}")

    def state_notify(self, sender: int, data: bytearray):
        """
        Not 100% certain what all the state numbers mean.

        https://github.com/orlopau/ember-mug/blob/master/docs/mug-state.md
        """
        new_state = data[0]
        if new_state not in [1, self.state]:
            _LOGGER.info(f"State changed from {self.state} to {new_state}")
            self.state = new_state

    async def update_all(self) -> bool:
        """Update all attributes."""
        update_attrs = ["led_colour", "current_temp", "target_temp", "battery"]
        try:
            if not await self.client.is_connected():
                await self.connect()
            for attr in update_attrs:
                await getattr(self, f"update_{attr}")()
            success = True
        except BleakError as e:
            _LOGGER.error(str(e))
            success = False
        return success

    async def disconnect(self) -> None:
        """Stop Loop and disconnect."""
        self._loop = False

        with contextlib.suppress(BleakError):
            await self.client.stop_notify(STATE_UUID)

        with contextlib.suppress(BleakError):
            if self.client and await self.client.is_connected():
                await self.client.disconnect()
