# Tests for the HR monitor module.
#  - StubHRMonitor and the real HRMonitor conform to the Protocol.
#  - parse_hr_measurement handles 8-bit and 16-bit GATT formats.
#  - The notify callback parses and enqueues BPM values.
#  - stream_hr drives notifications into the queue against a fake bleak backend.

import asyncio
import sys
import types

from src.ble.hr_monitor import (
    HRMonitor,
    HRMonitorProtocol,
    parse_hr_measurement,
)
from stubs.hr_monitor_stub import StubHRMonitor


def test_stub_conforms_to_protocol():
    assert isinstance(StubHRMonitor(), HRMonitorProtocol)


def test_real_monitor_conforms_to_protocol():
    assert isinstance(HRMonitor(), HRMonitorProtocol)


def test_parse_8bit_format():
    # flags bit0 = 0 -> uint8 BPM at byte 1
    assert parse_hr_measurement(bytearray([0x00, 75])) == 75


def test_parse_16bit_format():
    # flags bit0 = 1 -> uint16 little-endian BPM at bytes 1-2 (0x012C = 300)
    assert parse_hr_measurement(bytearray([0x01, 0x2C, 0x01])) == 300


def test_callback_enqueues_parsed_bpm():
    queue: asyncio.Queue = asyncio.Queue()
    handler = HRMonitor()._make_callback(queue)
    handler(object(), bytearray([0x00, 132]))
    assert queue.get_nowait() == 132


def _inject_fake_bleak(monkeypatch, holder):
    class FakeClient:
        def __init__(self, address):
            self.address = address
            holder["client"] = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def start_notify(self, uuid, callback):
            holder["uuid"] = uuid
            holder["callback"] = callback

        async def stop_notify(self, uuid):
            holder["stopped"] = uuid

    fake = types.ModuleType("bleak")
    fake.BleakClient = FakeClient
    fake.BleakScanner = object  # unused: address is provided
    monkeypatch.setitem(sys.modules, "bleak", fake)


async def test_stream_hr_drives_notifications_into_queue(monkeypatch):
    holder: dict = {}
    _inject_fake_bleak(monkeypatch, holder)
    queue: asyncio.Queue = asyncio.Queue()
    monitor = HRMonitor(address="AA:BB:CC:DD:EE:FF")

    task = asyncio.create_task(monitor.stream_hr(queue, interval=0.01))
    # Wait until start_notify has registered the callback.
    for _ in range(100):
        if "callback" in holder:
            break
        await asyncio.sleep(0)
    assert holder["callback"] is not None

    # Simulate two BLE notifications.
    holder["callback"](object(), bytearray([0x00, 60]))
    holder["callback"](object(), bytearray([0x00, 140]))

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    readings = [queue.get_nowait() for _ in range(queue.qsize())]
    assert readings == [60, 140]
    assert holder["stopped"] == "00002a37-0000-1000-8000-00805f9b34fb"
