# Tests for the MIDI source module.
#  - StubMIDISource and the real MIDISource conform to the Protocol.
#  - The notify callback enqueues messages onto the asyncio loop thread-safely.
#  - stream_messages drives callbacks into the queue against a fake mido backend,
#    resolving an explicit port name or falling back to the first available one.

import asyncio
import sys
import types
from types import SimpleNamespace

from src.midi.midi_source import MIDISource, MIDISourceProtocol
from stubs.midi_source_stub import StubMIDISource


def test_stub_conforms_to_protocol():
    assert isinstance(StubMIDISource(), MIDISourceProtocol)


def test_real_source_conforms_to_protocol():
    assert isinstance(MIDISource(), MIDISourceProtocol)


def _inject_fake_mido(monkeypatch, holder, names=("IAC Driver Bus 1", "Dubler Virtual In")):
    class FakePort:
        def __init__(self, name, callback=None):
            holder["port_name"] = name
            holder["callback"] = callback

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            holder["closed"] = True
            return False

    fake = types.ModuleType("mido")
    fake.get_input_names = lambda: list(names)
    fake.open_input = lambda name, callback=None: FakePort(name, callback)
    monkeypatch.setitem(sys.modules, "mido", fake)


async def _run_until(predicate, task=None):
    for _ in range(200):
        if predicate():
            return
        await asyncio.sleep(0)
    if task is not None:
        task.cancel()
    raise AssertionError("condition never became true")


async def _cancel(task):
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def test_stream_messages_drives_callback_into_queue(monkeypatch):
    holder: dict = {}
    _inject_fake_mido(monkeypatch, holder)
    queue: asyncio.Queue = asyncio.Queue()
    source = MIDISource(port_name="Dubler Virtual In")

    task = asyncio.create_task(source.stream_messages(queue, interval=0.01))
    await _run_until(lambda: "callback" in holder, task)
    assert holder["port_name"] == "Dubler Virtual In"

    msg1 = SimpleNamespace(type="note_on", note=60, velocity=100)
    msg2 = SimpleNamespace(type="control_change", control=1, value=64)
    holder["callback"](msg1)
    holder["callback"](msg2)
    await _run_until(lambda: queue.qsize() >= 2, task)

    await _cancel(task)
    received = [queue.get_nowait() for _ in range(queue.qsize())]
    assert received == [msg1, msg2]
    assert holder["closed"]


async def test_stream_messages_falls_back_to_first_available_port(monkeypatch):
    holder: dict = {}
    _inject_fake_mido(monkeypatch, holder)
    queue: asyncio.Queue = asyncio.Queue()
    source = MIDISource()  # no port_name given

    task = asyncio.create_task(source.stream_messages(queue, interval=0.01))
    await _run_until(lambda: "port_name" in holder, task)
    await _cancel(task)

    assert holder["port_name"] == "IAC Driver Bus 1"


async def test_stream_messages_raises_when_no_ports_available(monkeypatch):
    holder: dict = {}
    _inject_fake_mido(monkeypatch, holder, names=())
    queue: asyncio.Queue = asyncio.Queue()
    source = MIDISource()

    try:
        await source.stream_messages(queue, interval=0.01)
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "No MIDI input ports" in str(exc)
