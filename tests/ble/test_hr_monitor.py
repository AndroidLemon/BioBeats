# Tests for the HR monitor module. For now: the stub conforms to the Protocol.

from src.ble.hr_monitor import HRMonitorProtocol
from stubs.hr_monitor_stub import StubHRMonitor


def test_stub_conforms_to_protocol():
    assert isinstance(StubHRMonitor(), HRMonitorProtocol)
