import json

from app.data import write_json
from experiments.recovery import summarize


def test_buffered_pre_fault_response_is_not_recovery(tmp_path):
    events = [
        {"event": "dispatched", "bank": "bank-3", "unix_time": 99, "request_id": "old"},
        {
            "event": "reply",
            "bank": "bank-3",
            "unix_time": 112,
            "outcome": "accepted",
            "request_id": "old",
        },
        {"event": "dispatched", "bank": "bank-3", "unix_time": 113, "request_id": "new"},
        {
            "event": "reply",
            "bank": "bank-3",
            "unix_time": 118,
            "outcome": "accepted",
            "request_id": "new",
        },
    ]
    (tmp_path / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events), encoding="utf-8"
    )
    fault = tmp_path / "fault.json"
    write_json(fault, {"bank": "bank-3", "unix_time": 100, "fault_to_ready_seconds": 10})
    assert summarize(tmp_path, fault)["fault_to_accepted_update_seconds"] == 18


def test_no_ready_pod_is_censored(tmp_path):
    (tmp_path / "events.jsonl").write_text("", encoding="utf-8")
    fault = tmp_path / "fault.json"
    write_json(fault, {"bank": "bank-3", "unix_time": 100, "fault_to_ready_seconds": None})
    assert summarize(tmp_path, fault)["participation_recovery_censored"]
