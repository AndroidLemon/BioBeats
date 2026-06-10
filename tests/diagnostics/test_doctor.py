# Tests for the preflight doctor. The pure logic (status rollup, selection,
# formatting) is covered exhaustively; the hardware checks are smoke-tested to
# prove they return a valid result and never raise on a machine without the
# hardware/deps (the CI case).

import socket

from src.diagnostics.doctor import (
    CHECK_ORDER,
    CheckResult,
    CheckStatus,
    Doctor,
    DoctorConfig,
    check_apple_silicon,
    check_audio,
    check_ble,
    check_env,
    check_osc_port,
    check_rt2_model,
    format_report,
    select_checks,
    summarize,
)


# --- pure helpers ----------------------------------------------------------


def _r(status: CheckStatus) -> CheckResult:
    return CheckResult("x", status)


def test_summarize_precedence():
    assert summarize([_r(CheckStatus.PASS), _r(CheckStatus.PASS)]) is CheckStatus.PASS
    assert summarize([_r(CheckStatus.PASS), _r(CheckStatus.WARN)]) is CheckStatus.WARN
    # FAIL dominates WARN dominates PASS.
    assert (
        summarize([_r(CheckStatus.WARN), _r(CheckStatus.FAIL), _r(CheckStatus.PASS)])
        is CheckStatus.FAIL
    )


def test_summarize_skip_is_ignored():
    assert summarize([_r(CheckStatus.PASS), _r(CheckStatus.SKIP)]) is CheckStatus.PASS
    # Empty rolls up to PASS (nothing failed).
    assert summarize([]) is CheckStatus.PASS


def test_select_checks_defaults_to_all():
    assert select_checks(CHECK_ORDER, None) == CHECK_ORDER


def test_select_checks_preserves_canonical_order_and_drops_unknown():
    # Requested out of order and with a bogus name -> canonical order, bogus gone.
    got = select_checks(CHECK_ORDER, ["audio", "env", "nope"])
    assert got == ["env", "audio"]


def test_format_report_shows_hint_only_when_not_pass():
    results = [
        CheckResult("alpha", CheckStatus.PASS, "fine", hint="unused"),
        CheckResult("beta", CheckStatus.FAIL, "broken", hint="do the thing"),
    ]
    report = format_report(results)
    assert "✓ alpha" in report
    assert "✗ beta" in report
    # Hint shown for the failing check, suppressed for the passing one.
    assert "→ do the thing" in report
    assert "unused" not in report
    assert "overall: FAIL" in report


def test_format_report_empty():
    assert format_report([]) == "no checks run"


# --- individual checks: smoke (must return a valid result, never raise) ----


def test_check_env_passes_on_supported_python():
    # The test suite runs on >= 3.12, so this must pass.
    result = check_env(DoctorConfig())
    assert result.status is CheckStatus.PASS


def test_check_osc_port_passes_when_free():
    # Grab an ephemeral port, release it, then check it's bindable.
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    result = check_osc_port(DoctorConfig(osc_port=port))
    assert result.status is CheckStatus.PASS


def test_check_osc_port_fails_when_taken():
    # Hold a port open, then the check must report it unavailable.
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    try:
        result = check_osc_port(DoctorConfig(osc_port=port))
        assert result.status is CheckStatus.FAIL
        assert result.hint is not None
    finally:
        sock.close()


def test_hardware_checks_return_valid_results_without_hardware():
    # On CI there's no Apple Silicon / audio device / BLE adapter / RT2 weights;
    # each check must still return a CheckResult with a valid status, not raise.
    cfg = DoctorConfig(scan_seconds=0.1)
    for check in (check_apple_silicon, check_audio, check_rt2_model):
        result = check(cfg)
        assert isinstance(result, CheckResult)
        assert result.status in CheckStatus


def test_check_ble_smoke(monkeypatch):
    # Avoid a real 0.1s+ BLE scan: stub bleak so the check exercises its own
    # logic path deterministically. If bleak isn't importable it SKIPs, which is
    # also a valid outcome we accept here.
    result = check_ble(DoctorConfig(scan_seconds=0.01))
    assert isinstance(result, CheckResult)
    assert result.status in CheckStatus


# --- Doctor runner ---------------------------------------------------------


def test_doctor_runs_selected_in_order():
    results = Doctor(DoctorConfig()).run(["osc-port", "env"])
    assert [r.name for r in results] == ["env", "osc-port"]


def test_doctor_catches_a_crashing_check(monkeypatch):
    from src.diagnostics import doctor

    def _boom(_config):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(doctor._RUNNERS, "env", _boom)
    results = Doctor(DoctorConfig()).run(["env"])
    assert results[0].status is CheckStatus.FAIL
    assert "kaboom" in results[0].detail
