# Stub for src/ble/hr_monitor.py.
# Emits a deterministic synthetic HR sequence (ramp 60→180 over 60 steps)
# via asyncio.Queue. Implemented as a class so it matches the stateful real
# HRMonitor interface (HRMonitorProtocol) exactly.

import asyncio


class StubHRMonitor:
    """Deterministic HR source for tests. No hardware, no BLE.

    Mirrors the real HRMonitor interface: a single async `stream_hr` coroutine
    that pushes integer BPM readings into a queue.
    """

    async def stream_hr(self, queue: asyncio.Queue, interval: float = 1.0) -> None:
        """Emit HR readings into queue. Ramps from 60 to 180 bpm over 60 steps."""
        for bpm in range(60, 181, 2):
            await queue.put(bpm)
            await asyncio.sleep(interval)
