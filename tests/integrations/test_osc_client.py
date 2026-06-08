# Tests for the OSC sender: the loopback client the MIDI bridge uses to forward
# translated control messages into the running OSCBridge (or any OSC listener).
# The real OSCClient is exercised end-to-end over a real loopback UDP socket —
# no mocking of python-osc — since UDP sends need no bound listener and stay
# CI-safe on an ephemeral port.

import socket

from pythonosc.osc_message import OscMessage

from src.integrations.osc_client import OSCClient, OSCSenderProtocol
from stubs.osc_client_stub import StubOSCClient


def test_stub_conforms_to_protocol():
    assert isinstance(StubOSCClient(), OSCSenderProtocol)


def test_real_client_conforms_to_protocol():
    assert isinstance(OSCClient(), OSCSenderProtocol)


def test_stub_client_records_sent_messages():
    client = StubOSCClient()
    client.send("/rt2/prompt", "ambient drone")
    client.send("/rt2/intensity", 0.5)
    assert client.sent == [("/rt2/prompt", "ambient drone"), ("/rt2/intensity", 0.5)]


def _listen_on_loopback() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(2.0)
    return sock


def test_osc_client_sends_real_udp_packet_to_loopback():
    sock = _listen_on_loopback()
    try:
        host, port = sock.getsockname()
        client = OSCClient(host=host, port=port)

        client.send("/rt2/intensity", 0.5)

        data, _ = sock.recvfrom(1024)
        message = OscMessage(data)
        assert message.address == "/rt2/intensity"
        assert message.params == [0.5]
    finally:
        sock.close()


def test_osc_client_sends_string_argument():
    sock = _listen_on_loopback()
    try:
        host, port = sock.getsockname()
        client = OSCClient(host=host, port=port)

        client.send("/rt2/prompt", "techno bass")

        data, _ = sock.recvfrom(1024)
        message = OscMessage(data)
        assert message.address == "/rt2/prompt"
        assert message.params == ["techno bass"]
    finally:
        sock.close()
