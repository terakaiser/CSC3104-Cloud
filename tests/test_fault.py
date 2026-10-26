import json

from experiments import fault


def test_inject_records_deleted_and_replacement_pods(tmp_path, monkeypatch):
    replacement = {
        "metadata": {"name": "bank-2-new", "uid": "replacement-uid"},
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "True"}],
        },
    }
    calls = []
    pod_reads = iter(
        [
            {"items": [{"metadata": {"name": "bank-2-old", "uid": "deleted-uid"}}]},
            {"items": [replacement]},
        ]
    )

    def kubectl(*args):
        calls.append(args)
        if args[:2] == ("get", "deployment"):
            return json.dumps({"spec": {"replicas": 1}})
        if args[:2] == ("get", "pods"):
            return json.dumps(next(pod_reads))
        return ""

    monkeypatch.setattr(fault, "kubectl", kubectl)
    monkeypatch.setattr(fault.time, "monotonic", lambda: 1.0)
    output = tmp_path / "fault.json"

    record = fault.inject("bank-2", "kill", 0, 10, output)

    saved = json.loads(output.read_text(encoding="utf-8"))
    assert record == saved
    assert record["deleted_pod"] == "bank-2-old"
    assert record["deleted_uid"] == "deleted-uid"
    assert record["replacement_pod"] == "bank-2-new"
    assert record["replacement_uid"] == "replacement-uid"
    assert record["status"] == "ready"
    assert record["fault_to_ready_seconds"] == 0
    assert ("delete", "pod", "bank-2-old", "--wait=false") in calls
