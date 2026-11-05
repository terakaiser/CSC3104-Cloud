import io
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import demo
from app.cli import main


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    demo.ROOT.mkdir()
    demo.save("settings.json", {"data": str(tmp_path / "data"), "synthetic": True})
    Path("k8s").mkdir()
    Path("k8s/deployment.yaml").write_text("")
    return tmp_path


def test_demo_cli_routes_defaults(workspace, monkeypatch):
    calls = []
    monkeypatch.setattr(demo, "start", lambda *args: calls.append(args))
    main(["demo", "start"])
    main(["demo", "start", "--mu", "0.01"])
    assert calls == [(30, 30, 0.0), (30, 30, 0.01)]


def test_demo_dashboard_cli_routes_port(workspace, monkeypatch):
    from app import dashboard

    calls = []
    monkeypatch.setattr(dashboard, "serve", lambda port: calls.append(port))
    main(["demo", "dashboard", "--port", "9000"])
    assert calls == [9000]


def test_missing_tools_fail_before_dataset_or_cluster_changes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(demo.shutil, "which", lambda name: None if name == "kind" else name)
    with pytest.raises(ValueError, match="Install kind"):
        demo.setup(False)
    assert not demo.ROOT.exists()


def test_demo_kubeconfig_does_not_change_parent_environment(workspace, monkeypatch):
    monkeypatch.setenv("KUBECONFIG", "personal-config")
    assert demo.environment()["KUBECONFIG"] == str((demo.ROOT / "kubeconfig").resolve())
    assert os.environ["KUBECONFIG"] == "personal-config"
    calls = []
    monkeypatch.setattr(demo, "command", lambda *args, **kwargs: calls.append(args))
    demo.kubectl("get", "pods")
    assert calls[0][:5] == ("kubectl", "--context", "kind-bank-fl-demo", "-n", "bank-fl")


def test_fail_allows_repeated_kills_but_one_at_a_time(workspace, monkeypatch):
    monkeypatch.setattr(demo, "active", lambda: False)
    with pytest.raises(ValueError, match="Start the demo"):
        demo.fail("bank-3")
    monkeypatch.setattr(demo, "active", lambda: True)
    output = workspace / "result"
    output.mkdir()
    demo.save("latest.json", {"output": str(output)})
    calls = []
    monkeypatch.setattr(demo, "command", lambda *args: calls.append(args))
    first = demo.fail("bank-2")
    assert first.name == "fault-1.json" and "bank-2" in calls[0]
    with pytest.raises(ValueError, match="previous bank pod"):
        demo.fail("bank-3")  # the first kill has not finished recovering
    first.write_text(json.dumps({"bank": "bank-2", "status": "ready"}))
    second = demo.fail("bank-3")
    assert second.name == "fault-2.json" and "bank-3" in calls[1]
    assert demo.fault_records(output) == [first, second]


def test_failed_injection_never_blocks_the_next_kill(workspace, monkeypatch):
    monkeypatch.setattr(demo, "active", lambda: True)
    output = workspace / "result"
    output.mkdir()
    demo.save("latest.json", {"output": str(output)})

    def broken(*args):
        raise demo.subprocess.CalledProcessError(1, "fault")

    monkeypatch.setattr(demo, "command", broken)
    with pytest.raises(demo.subprocess.CalledProcessError):
        demo.fail("bank-1")
    failed = json.loads((output / "fault-1.json").read_text())
    assert failed["status"] == "failed" and "CalledProcessError" in failed["error"]
    monkeypatch.setattr(demo, "command", lambda *args: None)
    assert demo.fail("bank-1").name == "fault-2.json"


def test_bundle_contains_code_not_training_data(workspace):
    Path("pyproject.toml").write_text("[project]\nname='test'\n")
    for name in ("app", "experiments", "data"):
        Path(name).mkdir()
        Path(name, "example.py").write_text("")
    Path("app/__pycache__").mkdir()
    Path("app/__pycache__/old.pyc").write_bytes(b"old")
    output = Path("output")
    output.mkdir()
    package = demo.stage_bundle(output)
    assert (package / "app/example.py").exists()
    assert not (package / "app/__pycache__").exists()
    assert not (package / "data").exists()


@pytest.mark.parametrize("exit_code", [0, 1])
def test_start_records_exact_run_and_cleans_owned_processes(workspace, monkeypatch, exit_code):
    monkeypatch.setattr(demo, "active", lambda: False)
    monkeypatch.setattr(demo, "stage_bundle", lambda output: output / "package")
    kubectl_calls = []

    def kubectl(*args, **kwargs):
        kubectl_calls.append(args)
        return json.dumps({"items": [{"metadata": {"name": "coordinator-demo"}}]})

    monkeypatch.setattr(demo, "kubectl", kubectl)

    class Socket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def bind(self, address):
            pass

    monkeypatch.setattr(demo.socket, "socket", lambda: Socket())
    monkeypatch.setattr(demo.socket, "create_connection", lambda *a, **k: Socket())

    class Process:
        def __init__(self, submission):
            self.code = None
            self.submission = submission
            self.stdout = io.StringIO("Results saved to /results/20261022-demo\n")

        def poll(self):
            return self.code

        def wait(self, **kwargs):
            self.code = exit_code if self.submission else 0
            return self.code

        def terminate(self):
            self.code = 0

    children = []

    submitted = []

    def popen(args, **kwargs):
        if args[0] == "flwr":
            submitted.append(args)
        child = Process(args[0] == "flwr")
        children.append(child)
        return child

    monkeypatch.setattr(demo.subprocess, "Popen", popen)
    collected = []
    monkeypatch.setattr(demo, "collect", lambda: collected.append(True))
    if exit_code:
        with pytest.raises(ValueError, match="submission failed"):
            demo.start(30, 30)
    else:
        demo.start(30, 30, 0.01)
        assert submitted[0][-1] == 'rounds=30 deadline=30 mu=0.01 label="demo"'
    assert collected == ([] if exit_code else [True])
    # Waiting on every pod would hang on finished CronJob pods, which are never Ready.
    (wait,) = [call for call in kubectl_calls if call[0] == "wait"]
    assert "--all" not in wait
    assert "app in (coordinator,bank-1,bank-2,bank-3)" in wait
    assert not (demo.ROOT / "active.json").exists()
    assert all(child.poll() is not None for child in children)
    assert demo.read("latest.json")["run_id"] == "20261022-demo"


def test_results_rejects_failed_training_after_export(workspace, monkeypatch):
    from experiments import evaluate, plot

    output = workspace / "output"
    run = output / "run-1"
    run.mkdir(parents=True)
    (run / "summary.json").write_text(
        json.dumps(
            {
                "status": "insufficient_quorum",
                "committed_rounds": 2,
            }
        )
    )
    demo.save("latest.json", {"output": str(output), "run_id": "run-1", "pod": "pod-1"})
    monkeypatch.setattr(demo, "kubectl", lambda *args, **kwargs: None)
    monkeypatch.setattr(evaluate, "evaluate", lambda *args: None)
    monkeypatch.setattr(plot, "plot_runs", lambda *args: None)
    with pytest.raises(ValueError, match="did not complete"):
        demo.collect()


def test_dispatch_does_not_collect_while_active(workspace, monkeypatch):
    monkeypatch.setattr(demo, "active", lambda: True)
    with pytest.raises(ValueError, match="Wait for training"):
        demo.dispatch(SimpleNamespace(action="results"))


def test_training_progress_supports_windows_console_encoding(monkeypatch):
    from app.telemetry import RunLog

    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp949")
    monkeypatch.setattr("sys.stdout", stream)
    logger = RunLog.__new__(RunLog)
    logger.started = time.monotonic()
    logger.events = io.StringIO()
    logger.event("committed", version=1, accepted=["bank-1", "bank-2"])
    logger.event("deadline", attempt=2, valid=1, required=2)
    logger.event("finished", status="completed", committed_rounds=1)
    stream.flush()
    output = stream.buffer.getvalue().decode("cp949")
    assert "Round 1 committed - bank-1, bank-2 contributed" in output
    assert "model unchanged" in output
