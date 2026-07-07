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


class _FakeDevice:
    def __init__(self, name, address="AA:BB"):
        self.name = name
        self.address = address


def _fake_bleak(monkeypatch, devices):
    import sys
    import types

    fake = types.ModuleType("bleak")

    class _Scanner:
        @staticmethod
        async def discover(timeout=None):
            return devices

    fake.BleakScanner = _Scanner
    monkeypatch.setitem(sys.modules, "bleak", fake)


def test_check_ble_no_monitor_in_range_warns(monkeypatch):
    _fake_bleak(monkeypatch, [_FakeDevice("SomeSpeaker")])
    result = check_ble(DoctorConfig(scan_seconds=0.01))
    assert result.status is CheckStatus.WARN


def test_check_ble_finds_monitor_by_prefix(monkeypatch):
    _fake_bleak(monkeypatch, [_FakeDevice("OTbeat Burn 123")])
    result = check_ble(DoctorConfig(scan_seconds=0.01))
    assert result.status is CheckStatus.PASS
    assert "OTbeat Burn 123" in result.detail


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


# --- rt2-model / audio branch behavior (fake backends, same technique as
# --- the audio-sink and MRT2 client tests) ----------------------------------


def _fake_magenta_paths(monkeypatch, models_dir):
    import sys
    import types

    fake_pkg = types.ModuleType("magenta_rt")
    fake_paths = types.ModuleType("magenta_rt.paths")
    fake_paths.models_dir = lambda: models_dir
    fake_pkg.paths = fake_paths
    monkeypatch.setitem(sys.modules, "magenta_rt", fake_pkg)
    monkeypatch.setitem(sys.modules, "magenta_rt.paths", fake_paths)


def test_rt2_missing_package_fails_on_engine_host(monkeypatch):
    import builtins
    import sys

    from src.diagnostics import doctor

    monkeypatch.delitem(sys.modules, "magenta_rt", raising=False)
    monkeypatch.delitem(sys.modules, "magenta_rt.paths", raising=False)
    real_import = builtins.__import__

    def _no_magenta(name, *args, **kwargs):
        if name.startswith("magenta_rt"):
            raise ImportError("nope")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_magenta)
    # On the engine host a missing engine stack is broken, not informational.
    monkeypatch.setattr(doctor, "_is_engine_host", lambda: True)
    assert check_rt2_model(DoctorConfig()).status is CheckStatus.FAIL
    monkeypatch.setattr(doctor, "_is_engine_host", lambda: False)
    assert check_rt2_model(DoctorConfig()).status is CheckStatus.SKIP


def test_rt2_weights_missing_warns_with_real_download_hint(monkeypatch, tmp_path):
    _fake_magenta_paths(monkeypatch, tmp_path)
    result = check_rt2_model(DoctorConfig(model_size="mrt2_small"))
    assert result.status is CheckStatus.WARN
    # `--load-model` does NOT download; the package's own CLI does.
    assert "mrt models download" in result.hint


def test_rt2_empty_model_dir_is_not_weights_present(monkeypatch, tmp_path):
    _fake_magenta_paths(monkeypatch, tmp_path)
    (tmp_path / "mrt2_small").mkdir()  # exists but empty (aborted download)
    result = check_rt2_model(DoctorConfig(model_size="mrt2_small"))
    assert result.status is CheckStatus.WARN


def test_rt2_model_files_present_passes(monkeypatch, tmp_path):
    _fake_magenta_paths(monkeypatch, tmp_path)
    model_dir = tmp_path / "mrt2_small"
    model_dir.mkdir()
    (model_dir / "graph.mlxfn").touch()
    (model_dir / "graph_state.safetensors").touch()
    result = check_rt2_model(DoctorConfig(model_size="mrt2_small"))
    assert result.status is CheckStatus.PASS


def test_slower_than_realtime_budget_warns():
    from src.diagnostics.doctor import classify_budget

    status, label = classify_budget(1.2, chunk_seconds=2.0)
    assert status is CheckStatus.PASS and "OK" in label
    status, label = classify_budget(2.4, chunk_seconds=2.0)
    assert status is CheckStatus.WARN and "SLOWER" in label


def test_osc_port_fail_hint_mentions_running_engine():
    import socket as socket_mod

    sock = socket_mod.socket(socket_mod.AF_INET, socket_mod.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    try:
        result = check_osc_port(DoctorConfig(osc_port=port))
        assert result.status is CheckStatus.FAIL
        assert "engine" in result.hint  # might just be the engine, mid-session
    finally:
        sock.close()


def test_rt2_graph_without_state_file_is_not_weights_present(monkeypatch, tmp_path):
    # A partial download (graph exported, state weights missing) must WARN,
    # not PASS — the model can't load without both artifacts.
    _fake_magenta_paths(monkeypatch, tmp_path)
    model_dir = tmp_path / "mrt2_small"
    model_dir.mkdir()
    (model_dir / "graph.mlxfn").touch()
    result = check_rt2_model(DoctorConfig(model_size="mrt2_small"))
    assert result.status is CheckStatus.WARN
