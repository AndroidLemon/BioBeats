# Session control-stream recording + replay format.
#
# Records the /rt2/* control stream a source adapter emits as a timestamped JSONL
# log, so a take can be replayed (replay.py) to reproduce the performance and so
# real sessions become regression material for free. RecordingOSCSender is a thin
# OSCSenderProtocol decorator — pure composition, exactly like FanoutOSCSender —
# so it drops in front of any sender (or a FanoutOSCSender) with no changes to the
# adapter or the engine.
#
# Log format: one JSON object per line — {"t": seconds-since-first-send,
# "address": "/rt2/...", "value": <str|number>}. Each line is flushed immediately
# so a log survives an unclean shutdown (Ctrl-C ending a live take).

import json
import time
from dataclasses import dataclass
from typing import Callable

from src.integrations.osc_client import OSCSenderProtocol


@dataclass(frozen=True)
class ControlEvent:
    """One recorded OSC control message: seconds-since-start, address, value."""

    t: float
    address: str
    value: object


class RecordingOSCSender:
    """OSCSenderProtocol decorator: log every send to JSONL, then forward it.

    Timestamps are seconds since the first send, so a log replays with its
    original timing regardless of when recording started. Lines are flushed
    immediately (crash-safe). close() releases the file; also usable as a
    context manager.
    """

    def __init__(
        self,
        inner: OSCSenderProtocol,
        path,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._clock = clock
        self._start: float | None = None
        self._fh = open(path, "w", encoding="utf-8")

    def send(self, address: str, value) -> None:
        """Append (t, address, value) to the log, then forward to the inner sender."""
        now = self._clock()
        if self._start is None:
            self._start = now
        record = {"t": round(now - self._start, 6), "address": address, "value": value}
        self._fh.write(json.dumps(record) + "\n")
        self._fh.flush()
        self._inner.send(address, value)

    def close(self) -> None:
        """Close the log file. Idempotent."""
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> "RecordingOSCSender":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def read_control_log(path) -> list[ControlEvent]:
    """Read a JSONL control log into ControlEvents, in file order. Blank lines skipped."""
    events: list[ControlEvent] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            events.append(
                ControlEvent(t=data["t"], address=data["address"], value=data["value"])
            )
    return events
