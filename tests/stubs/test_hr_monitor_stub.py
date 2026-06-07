# Tests for the HR monitor stub. Proves the class interface and the
# deterministic 60→180 ramp contract.

import asyncio

from stubs.hr_monitor_stub import StubHRMonitor


async def test_stream_hr_fills_queue_with_ramp():
    queue: asyncio.Queue = asyncio.Queue()
    monitor = StubHRMonitor()
    # interval=0 so the test does not actually sleep
    await monitor.stream_hr(queue, interval=0)
    readings = []
    while not queue.empty():
        readings.append(queue.get_nowait())
    assert readings[0] == 60
    assert readings[-1] == 180
    assert readings == list(range(60, 181, 2))


async def test_all_readings_are_ints():
    queue: asyncio.Queue = asyncio.Queue()
    await StubHRMonitor().stream_hr(queue, interval=0)
    assert all(isinstance(r, int) for r in list(queue._queue))
