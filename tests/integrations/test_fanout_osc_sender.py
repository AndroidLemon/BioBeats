# TDD tests for fanout_osc_sender.py — write these first, confirm they fail,
# then implement the module until all pass.

from src.integrations.fanout_osc_sender import FanoutOSCSender
from src.integrations.osc_client import OSCSenderProtocol
from stubs.osc_client_stub import StubOSCClient


def test_conforms_to_protocol():
    assert isinstance(FanoutOSCSender([StubOSCClient()]), OSCSenderProtocol)


def test_forwards_one_send_to_every_wrapped_sender():
    a, b = StubOSCClient(), StubOSCClient()
    fanout = FanoutOSCSender([a, b])

    fanout.send("/rt2/intensity", 0.5)

    assert a.sent == [("/rt2/intensity", 0.5)]
    assert b.sent == [("/rt2/intensity", 0.5)]


def test_forwards_each_send_in_order():
    a = StubOSCClient()
    fanout = FanoutOSCSender([a])

    fanout.send("/rt2/prompt", "ambient")
    fanout.send("/rt2/intensity", 0.8)

    assert a.sent == [("/rt2/prompt", "ambient"), ("/rt2/intensity", 0.8)]


def test_empty_fanout_sends_nowhere_without_raising():
    fanout = FanoutOSCSender([])

    fanout.send("/rt2/intensity", 0.5)
