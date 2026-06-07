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
