import json
import threading
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from app import dashboard, demo
from app.config import RunConfig


def test_dashboard_without_setup_reports_setup_needed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(demo, "active", lambda: False)

    result = dashboard.dashboard_data()

    assert not result["prepared"]
    assert not result["active"]
    assert result["kubernetes"]["pods"] == []
    assert result["alerts"][0]["title"] == "Demo not set up"


def test_kubernetes_snapshot_summarizes_workloads_and_logs(monkeypatch):
    payload = {
        "items": [
            {
                "kind": "Pod",
                "metadata": {"name": "bank-1-abc", "labels": {"app": "bank-1"}},
                "status": {
                    "phase": "Running",
                    "containerStatuses": [
                        {
                            "name": "bank-1",
                            "ready": True,
                            "restartCount": 1,
                            "state": {"running": {}},
                        }
                    ],
                },
                "spec": {"nodeName": "kind-control-plane"},
            },
            {
                "kind": "Pod",
                "metadata": {"name": "scheduled-run-xyz", "labels": {"app": "scheduled-training"}},
                "status": {"phase": "Succeeded", "containerStatuses": [{"ready": False}]},
            },
            {
                "kind": "Deployment",
                "metadata": {"name": "bank-1"},
                "spec": {
                    "replicas": 1,
                    "template": {"spec": {"containers": [{"image": "bank-fl:demo"}]}},
                },
                "status": {"readyReplicas": 1, "availableReplicas": 1},
            },
            {
                "kind": "Service",
                "metadata": {"name": "coordinator"},
                "spec": {"clusterIP": "10.0.0.1", "ports": [{"port": 9092}]},
            },
            {
                "kind": "Event",
                "metadata": {"name": "warning-1", "creationTimestamp": "2026-10-25T10:00:00Z"},
                "type": "Warning",
                "reason": "BackOff",
                "involvedObject": {"name": "bank-2-abc"},
                "message": "container restart backoff",
            },
        ]
    }
    calls = []

    metrics = {
        "items": [
            {
                "metadata": {"name": "bank-1-abc", "labels": {"app": "bank-1"}},
                "timestamp": "2026-11-10T08:00:00Z",
                "containers": [{"usage": {"cpu": "125m", "memory": "210Mi"}}],
            }
        ]
    }

    def kubectl(*args):
        calls.append(args)
        if args[:2] == ("get", "--raw"):
            return json.dumps(metrics)
        if args[0] == "get":
            return json.dumps(payload)
        return "\x1b[92mpod log line\x1b[0m\n"

    monkeypatch.setattr(dashboard, "_kubectl", kubectl)
    result = dashboard._kubernetes()

    assert [pod["name"] for pod in result["pods"]] == ["bank-1-abc"]  # finished job pod hidden
    assert result["pods"][0]["ready"]
    assert result["pods"][0]["restarts"] == 1
    assert result["deployments"][0]["images"] == ["bank-fl:demo"]
    assert result["services"][0]["ports"] == ["9092/TCP"]
    assert result["events"][0]["reason"] == "BackOff"
    assert result["events"][0]["time"] == "2026-10-25 18:00:00 SGT"
    assert result["logs"] == "pod log line"
    assert result["pods"][0]["cpu_millicores"] == 125
    assert result["pods"][0]["memory_mib"] == 210
    assert len(calls) == 3


def test_event_timestamp_conversion_is_dynamic_and_handles_offsets():
    assert dashboard._age("2026-10-25T10:00:00Z") == "2026-10-25 18:00:00 SGT"
    assert dashboard._age("2026-10-25T23:30:00-04:00") == "2026-10-26 11:30:00 SGT"
    assert dashboard._age("not-a-timestamp") == "not-a-timestamp"


def test_local_run_results_are_loaded_and_rejections_are_flagged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    demo.ROOT.mkdir()
    run_dir = tmp_path / "results" / "demo" / "20261025-120000" / "run-123"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps({"config": {"rounds": 3, "mu": 1.0}, "dataset": {"synthetic": False}}),
        encoding="utf-8",
    )
    (run_dir / "summary.json").write_text(
        json.dumps(
            {
                "status": "insufficient_quorum",
                "committed_rounds": 1,
                "attempts": 3,
                "successful_round_rate": 1 / 3,
                "participation": {"bank-1": 1, "bank-2": 0, "bank-3": 0},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "rounds.csv").write_text(
        "attempt,version,status,seconds,elapsed_seconds,accepted,samples,tensor_bytes_sent,tensor_bytes_received\n"
        "1,1,committed,2.5,2.5,bank-1;bank-2,20,100,100\n",
        encoding="utf-8",
    )
    (run_dir / "events.jsonl").write_text(
        '{"event":"reply","outcome":"stale","attempt":2}\n', encoding="utf-8"
    )
    demo.save("settings.json", {"synthetic": False})
    monkeypatch.setattr(demo, "active", lambda: False)
    monkeypatch.setattr(
        dashboard,
        "_kubectl",
        lambda *args: json.dumps({"items": []}) if args[0] == "get" else "",
    )

    result = dashboard.dashboard_data()

    assert result["run"]["run_id"] == "run-123"
    assert result["runs"] == [{"id": "run-123", "label": "run-123 · FedProx μ=1"}]
    assert result["run"]["summary"]["committed_rounds"] == 1
    assert result["run"]["rounds"][0]["seconds"] == 2.5
    assert any(alert["title"] == "Training replies rejected" for alert in result["alerts"])
    assert any(
        alert["title"] == "Training ended: insufficient_quorum" for alert in result["alerts"]
    )


def test_dashboard_http_serves_page_and_json_api(monkeypatch):
    monkeypatch.setattr(
        dashboard,
        "dashboard_data",
        lambda selected: {"selected": selected, "alerts": []},
    )
    server = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.DashboardHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base) as response:
            page = response.read().decode("utf-8")
        with urlopen(f"{base}/api/dashboard?run=run-1") as response:
            api = json.loads(response.read())
        assert "Bank Federation Operations" in page
        assert "setInterval(refresh,2000)" in page
        assert 'id="refresh"' not in page
        assert "events.slice(-80).map(formatEvent)" in page
        assert "Simulate Self-Healing" in page
        assert 'button.classList.contains("armed")' in page
        assert 'role="tablist"' in page
        assert 'fetch("/api/fail"' in page
        assert 'id="faultTracker"' in page
        assert "Deleted pod:" in page
        assert 'id="muInput"' in page
        assert all(f'<option value="{mu}"' in page for mu in ("0", "0.01", "0.1", "1"))
        assert "FedProx μ=" in page
        assert "Replacement pod:" in page
        assert api == {"selected": "run-1", "alerts": []}
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_dashboard_reads_live_training_files_from_coordinator(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    demo.ROOT.mkdir()
    demo.save("settings.json", {"synthetic": False})
    demo.save(
        "latest.json",
        {"pod": "coordinator-abc", "output": "results/demo/live", "run_id": None},
    )
    demo.save("active.json", {"pid": 123, "created": 1, "started_at": 2})
    monkeypatch.setattr(demo, "active", lambda: True)
    remote = {
        "run_id": "run-live",
        "files": {
            "run.json": json.dumps({"config": {"rounds": 8}}),
            "rounds.csv": (
                "attempt,version,status,seconds,elapsed_seconds,accepted,samples,tensor_bytes_sent,tensor_bytes_received\n"
                "1,1,committed,4.0,4.0,bank-1;bank-2,20,100,100\n"
            ),
            "events.jsonl": '{"event":"committed","attempt":1,"version":1}\n',
        },
    }
    calls = []

    def kubectl(*args):
        calls.append(args)
        if args[0] == "exec":
            compile(args[5], "<remote-run-reader>", "exec")
        return json.dumps(remote) if args[0] == "exec" else json.dumps({"items": []})

    monkeypatch.setattr(dashboard, "_kubectl", kubectl)

    result = dashboard.dashboard_data()

    assert result["active"]
    assert result["run"]["run_id"] == "run-live"
    assert result["run"]["latest_attempt"] == 1
    assert result["run"]["rounds"][0]["version"] == 1
    assert result["run"]["events"][0]["event"] == "committed"
    assert sum(call[0] == "exec" for call in calls) == 1


def test_dashboard_does_not_show_previous_run_during_dashboard_startup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    demo.ROOT.mkdir()
    demo.save("settings.json", {"synthetic": False})
    demo.save(
        "latest.json",
        {"pod": "coordinator-abc", "output": "results/demo/old", "run_id": "run-old"},
    )
    old_run = tmp_path / "results" / "demo" / "20261025-120000" / "run-old"
    old_run.mkdir(parents=True)
    (old_run / "run.json").write_text(json.dumps({"config": {"rounds": 3}}), encoding="utf-8")
    monkeypatch.setattr(demo, "active", lambda: False)
    monkeypatch.setattr(dashboard, "_dashboard_process_active", lambda: True)
    monkeypatch.setattr(
        dashboard,
        "_kubectl",
        lambda *args: json.dumps({"items": []}) if args[0] == "get" else "",
    )

    result = dashboard.dashboard_data()

    assert result["active"]
    assert result["run"]["run_id"] is None


def test_simulate_self_healing_injects_one_selected_bank_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    demo.ROOT.mkdir()
    output = tmp_path / "results" / "demo" / "current"
    output.mkdir(parents=True)
    demo.save("latest.json", {"output": str(output)})
    record = {"bank": "bank-2", "fault_to_ready_seconds": 3.5, "recovery_censored": False}
    monkeypatch.setattr(demo, "active", lambda: True)

    calls = []

    def fail(bank, kind, duration):
        calls.append((bank, kind, duration))
        (output / "fault.json").write_text(json.dumps(record), encoding="utf-8")

    monkeypatch.setattr(demo, "fail", fail)

    assert dashboard.simulate_self_healing("bank-2") == {"bank": "bank-2", "record": record}
    dashboard.simulate_self_healing("bank-1", "absence")
    assert calls == [("bank-2", "kill", 20.0), ("bank-1", "absence", 20.0)]
    with pytest.raises(ValueError, match="bank-1, bank-2, bank-3"):
        dashboard.simulate_self_healing("coordinator")
    with pytest.raises(ValueError, match="bank-1, bank-2, bank-3"):
        dashboard.simulate_self_healing("bank-4")  # only a 5-bank setup has bank-4
    with pytest.raises(ValueError, match="kill or absence"):
        dashboard.simulate_self_healing("bank-1", "explode")
    demo.save("settings.json", {"synthetic": False, "banks": 5})
    dashboard.simulate_self_healing("bank-4")
    assert calls[-1] == ("bank-4", "kill", 20.0)


def test_page_is_drawn_for_the_configured_bank_count(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    demo.ROOT.mkdir()

    def page():
        server = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.DashboardHandler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{server.server_port}/", timeout=5) as response:
                return response.read().decode("utf-8")
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    three = page()  # no settings yet: the original three-bank demo
    assert "NBANKS=3," in three and "repeat(3,120px)" in three
    assert "__BANKS__" not in three and "__OUTAGE__" not in three
    assert "Offline for 20 s" in three
    demo.save("settings.json", {"synthetic": False, "banks": 5})
    assert "NBANKS=5," in page()


def test_launch_training_runs_demo_command_in_background(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    demo.ROOT.mkdir()
    demo.save("settings.json", {"synthetic": False})
    monkeypatch.setattr(dashboard, "_training_active", lambda: False)
    monkeypatch.setattr(
        dashboard.psutil, "Process", lambda pid: SimpleNamespace(create_time=lambda: 12.5)
    )
    calls = []

    class Process:
        pid = 4321

    monkeypatch.setattr(
        dashboard.subprocess,
        "Popen",
        lambda *args, **kwargs: calls.append((args, kwargs)) or Process(),
    )

    result = dashboard.launch_training(8, 45.0, 0.01)

    assert result == {"status": "starting", "pid": 4321}
    args, kwargs = calls[0]
    assert args[0][2:5] == ["app.cli", "demo", "start"]
    assert args[0][-6:] == ["--rounds", "8", "--deadline", "45.0", "--mu", "0.01"]
    assert kwargs["stdout"].name.endswith("dashboard-training.log")
    assert json.loads(dashboard.TRAINING_STATE.read_text()) == {"pid": 4321, "created": 12.5}


def test_dashboard_training_endpoint_validates_origin_and_launches(monkeypatch):
    calls = []
    monkeypatch.setattr(
        dashboard,
        "dashboard_data",
        lambda selected: {"selected": selected, "alerts": []},
    )

    def fake_launch(rounds, deadline, mu):
        RunConfig(rounds=rounds, deadline=deadline, mu=mu)  # validate like the real launch_training
        calls.append((rounds, deadline, mu))
        return {"status": "starting", "pid": 42}

    monkeypatch.setattr(dashboard, "launch_training", fake_launch)
    server = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.DashboardHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    payload = json.dumps({"rounds": 5, "deadline": 40, "mu": 0.01}).encode()
    try:
        request = Request(
            f"{base}/api/train",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Origin": base,
            },
            method="POST",
        )
        with urlopen(request) as response:
            assert response.status == 202
            assert json.loads(response.read())["pid"] == 42
        request = Request(
            f"{base}/api/train",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Origin": "http://attacker.example",
            },
            method="POST",
        )
        try:
            urlopen(request)
        except HTTPError as error:
            assert error.code == 403
        else:
            raise AssertionError("Cross-origin training request should be rejected.")
        for bad_mu in ("0.1", 10**400):
            request = Request(
                f"{base}/api/train",
                data=json.dumps({"rounds": 5, "deadline": 40, "mu": bad_mu}).encode(),
                headers={"Content-Type": "application/json", "Origin": base},
                method="POST",
            )
            try:
                urlopen(request)
            except HTTPError as error:
                assert error.code == 400
            else:
                raise AssertionError(f"mu={bad_mu!r} should be rejected.")
        assert calls == [(5, 40, 0.01)]
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_dashboard_failure_endpoint_accepts_local_simulation(monkeypatch):
    calls = []
    expected = {
        "bank": "bank-3",
        "record": {
            "bank": "bank-3",
            "fault_to_ready_seconds": 2.0,
            "recovery_censored": False,
        },
    }
    monkeypatch.setattr(
        dashboard,
        "simulate_self_healing",
        lambda bank, kind: calls.append((bank, kind)) or expected,
    )
    server = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.DashboardHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    request = Request(
        f"{base}/api/fail",
        data=json.dumps({"bank": "bank-3", "kind": "absence"}).encode(),
        headers={"Content-Type": "application/json", "Origin": base},
        method="POST",
    )
    try:
        with urlopen(request) as response:
            assert response.status == 200
            assert json.loads(response.read()) == expected
        assert calls == [("bank-3", "absence")]
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
