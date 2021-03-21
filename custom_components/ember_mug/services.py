"""Services for updating Mug information."""
from bleak import BleakClient, discover

from . import _LOGGER
from .const import TARGET_TEMP_UUID


async def set_target_temp(self, temp: float) -> None:
    """Set target temp of mug."""
    _LOGGER.debug(f"Set to {temp}")
    target = bytearray(int(temp / 0.01).to_bytes(2, "little"))
    resp = await self.client.write_gatt_char(TARGET_TEMP_UUID, target, False)
    _LOGGER.debug(resp)


async def find_mugs():
    """Find all mugs."""
    try:
        print("Searching..", end="")

        while True:
            print(".", end="")
            devices = await discover()

            for device in devices:
                if device.name == "Ember Ceramic Mug":
                    # We found the ember mug!
                    print(device.address)
                    print(device.name)
                    print(device.details)

                    async with BleakClient(device) as client:
                        x = await client.is_connected()
                        print(f"Connected: {x}")
                        y = await client.pair()
                        print(f"Paired: {y}")
    except Exception as e:
        print(f"Error: {e}")
