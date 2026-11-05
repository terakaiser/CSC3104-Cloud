from pathlib import Path
from types import SimpleNamespace

import pytest

from app import scheduled


def test_scheduled_run_targets_the_coordinator_service_and_streams(monkeypatch):
    calls = []
    monkeypatch.setattr(scheduled, "stage_bundle", lambda output, root: output / "package")
    monkeypatch.setattr(
        scheduled.subprocess,
        "run",
        lambda args, check: calls.append(args) or SimpleNamespace(returncode=0),
    )
    assert scheduled.main(["--rounds", "5", "--mu", "0.1"]) == 0
    (args,) = calls
    assert Path(args[0]).stem == "flwr"
    assert args[1] == "run" and "--stream" in args
    assert args[args.index("--federation-config") + 1] == 'address="coordinator:9093"'
    run_config = args[args.index("--run-config") + 1]
    assert "rounds=5" in run_config and "mu=0.1" in run_config


def test_invalid_settings_fail_before_starting_a_run(monkeypatch):
    monkeypatch.setattr(scheduled.subprocess, "run", lambda *a, **k: pytest.fail("run started"))
    with pytest.raises(ValueError):
        scheduled.main(["--rounds", "0"])
