# Stub for src/ble/hr_monitor.py.
# Emits a deterministic synthetic HR sequence (ramp 60→180 over 60 steps)
# via asyncio.Queue. Interface must match hr_monitor.py exactly.

import asyncio


async def stream_hr(queue: asyncio.Queue, interval: float = 1.0) -> None:
    """Emit HR readings into queue. Ramps from 60 to 180 bpm over 60 steps."""
    for bpm in range(60, 181, 2):
        await queue.put(bpm)
        await asyncio.sleep(interval)
