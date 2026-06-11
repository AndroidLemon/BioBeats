# Tests for the run_doctor.py entrypoint: --only/--skip resolution and a fast
# env-only smoke run (no hardware, no BLE scan).

from run_doctor import main, selected_names
from src.diagnostics.doctor import CHECK_ORDER


def test_selected_names_defaults_to_all():
    assert selected_names(None, None) == CHECK_ORDER


def test_selected_names_only():
    assert selected_names("audio,env", None) == ["audio", "env"]


def test_selected_names_skip_filters():
    got = selected_names(None, "ble,rt2-model")
    assert "ble" not in got and "rt2-model" not in got
    assert "env" in got


def test_selected_names_only_then_skip():
    assert selected_names("env,audio,ble", "ble") == ["env", "audio"]


def test_main_env_only_smoke(capsys):
    # env always passes on a supported interpreter -> exit 0, report printed.
    code = main(["--only", "env"])
    assert code == 0
    assert "overall: PASS" in capsys.readouterr().out
