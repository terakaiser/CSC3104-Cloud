import json

from app.data import write_json
from experiments.recovery import summarize_all


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
    assert summarize_all(tmp_path, [fault])["fault_to_accepted_update_seconds"] == 18


def test_no_ready_pod_is_censored(tmp_path):
    (tmp_path / "events.jsonl").write_text("", encoding="utf-8")
    fault = tmp_path / "fault.json"
    write_json(fault, {"bank": "bank-3", "unix_time": 100, "fault_to_ready_seconds": None})
    assert summarize_all(tmp_path, [fault])["participation_recovery_censored"]


def test_each_kill_gets_its_own_recovery_and_a_rekill_cuts_the_earlier_one_off(tmp_path):
    def accepted(bank, dispatched, replied, request):
        return [
            {"event": "dispatched", "bank": bank, "unix_time": dispatched, "request_id": request},
            {
                "event": "reply",
                "bank": bank,
                "unix_time": replied,
                "outcome": "accepted",
                "request_id": request,
            },
        ]

    # bank-3 is killed at 100 and again at 130 before it ever rejoins; bank-1 at 200.
    events = accepted("bank-3", 140, 150, "b3") + accepted("bank-1", 210, 222, "b1")
    (tmp_path / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events), encoding="utf-8"
    )
    paths = []
    for number, (bank, at) in enumerate([("bank-3", 100), ("bank-3", 130), ("bank-1", 200)], 1):
        paths.append(tmp_path / f"fault-{number}.json")
        write_json(paths[-1], {"bank": bank, "unix_time": at, "fault_to_ready_seconds": 5})
    result = summarize_all(tmp_path, paths)
    seconds = [f["fault_to_accepted_update_seconds"] for f in result["faults"]]
    assert seconds == [None, 20, 22]  # the first bank-3 kill never recovered before the next
    assert result["fault_to_accepted_update_seconds"] is None  # top level = first kill
    assert json.loads((tmp_path / "recovery.json").read_text())["faults"][2]["bank"] == "bank-1"
