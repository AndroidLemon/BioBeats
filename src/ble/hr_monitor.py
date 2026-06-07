# BLE heart-rate monitor.
#
# Defines HRMonitorProtocol, the interface shared by the real bleak-backed
# monitor (added later, lazy-imports bleak) and StubHRMonitor. The pipeline
# depends only on this Protocol.

import asyncio
from typing import Protocol, runtime_checkable


@runtime_checkable
class HRMonitorProtocol(Protocol):
    """Interface shared by the real HR monitor and StubHRMonitor.

    A single long-running coroutine that pushes integer BPM readings into a
    queue. The real implementation holds a BLE connection and feeds the queue
    from start_notify callbacks; `interval` is a fallback cadence hint.
    """

    async def stream_hr(self, queue: asyncio.Queue, interval: float = 1.0) -> None:
        """Stream integer BPM readings into `queue` until cancelled."""
        ...


# Standard GATT Heart Rate Measurement characteristic.
HR_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"
DEFAULT_NAME_PREFIX = "OTbeat"


def parse_hr_measurement(data: bytes | bytearray) -> int:
    """Parse a Heart Rate Measurement payload into a BPM integer.

    Byte 0 is the flags field; its bit 0 selects the value width:
    0 -> uint8 at byte 1, 1 -> uint16 (little-endian) at bytes 1-2.
    """
    flags = data[0]
    if flags & 0x01:
        # print(f"Parsed HR measurement with 16-bit value: {data[1:3].hex()} -> {int.from_bytes(bytes(data[1:3]), 'little')}")
        return int.from_bytes(bytes(data[1:3]), "little")
    # print(f"Parsed HR measurement with 8-bit value: {data[1]:02x} -> {data[1]}")
    return data[1]


class HRMonitor:
    """Real BLE heart-rate monitor (OTBeat Burn) via bleak.

    Connects to a device matched by name prefix (or an explicit address),
    subscribes to HR notifications, and pushes each parsed BPM into the queue.
    bleak is lazy-imported in stream_hr so this module loads without BLE
    available (e.g. CI). The device must be disconnected from the OTF app first.
    """

    def __init__(
        self, name_prefix: str = DEFAULT_NAME_PREFIX, address: str | None = None
    ) -> None:
        self._name_prefix = name_prefix
        self._address = address

    def _make_callback(self, queue: asyncio.Queue):
        """Return a notification handler that parses and enqueues BPM values."""

        def handler(_characteristic, data: bytearray) -> None:
            queue.put_nowait(parse_hr_measurement(data))

        return handler

    async def _discover(self, scanner_cls) -> str:
        """Scan and return the address of the first name-prefix match."""
        prefix = self._name_prefix.lower()
        for device in await scanner_cls.discover():
            if device.name and device.name.lower().startswith(prefix):
                # print(f"Found BLE device {device.name!r} at {device.address}, matching prefix {prefix!r}")
                return device.address
        raise RuntimeError(f"No BLE device found with name prefix {self._name_prefix!r}")

    async def stream_hr(self, queue: asyncio.Queue, interval: float = 1.0) -> None:
        """Connect, subscribe to HR notifications, and stream until cancelled."""
        from bleak import BleakClient, BleakScanner

        address = self._address or await self._discover(BleakScanner)
        async with BleakClient(address) as client:
            await client.start_notify(HR_MEASUREMENT_UUID, self._make_callback(queue))
            try:
                # Notifications drive the queue; just keep the connection alive.
                while True:
                    await asyncio.sleep(interval)
            finally:
                await client.stop_notify(HR_MEASUREMENT_UUID)
