# Tests for the MRT2 client module. For now: the stub conforms to the Protocol.

from src.engine.mrt2_client import MRT2ClientProtocol
from stubs.mrt2_client_stub import StubMRT2Client


def test_stub_conforms_to_protocol():
    assert isinstance(StubMRT2Client(), MRT2ClientProtocol)
