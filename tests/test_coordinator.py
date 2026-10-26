import json
from types import SimpleNamespace

from app import coordinator
from app.config import RunConfig
from app.protocol import Reply


class Clock:
    value = 0.0

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class ScriptedTransport:
    def __init__(self, clock, only_one=False):
        self.clock = clock
        self.pending = []
        self.only_one = only_one
        self.first_commit_pending = False

    def online_banks(self):
        return {"bank-1", "bank-2", "bank-3"}

    def submit(self, request):
        delay = 0.3 if request.bank_id == "bank-3" and request.attempt == 1 else 0.01
        if self.only_one and request.bank_id != "bank-1":
            delay = 1.0
        self.pending.append((self.clock.value + delay, request))
        return True

    def poll(self):
        completed = [(at, r) for at, r in self.pending if at <= self.clock.value]
        self.pending = [(at, r) for at, r in self.pending if at > self.clock.value]
        return [
            Reply(r.run_id, r.attempt, r.version, r.bank_id, r.request_id, r.weights, 10)
            for _, r in completed
        ]

    def close(self):
        pass


class FlakyTransport(ScriptedTransport):
    """Bank 3 disappears between 0.1s and 0.2s, like a killed and replaced pod."""

    def online_banks(self):
        if 0.1 <= self.clock.value < 0.2:
            return {"bank-1", "bank-2"}
        return super().online_banks()


def exercise(tmp_path, monkeypatch, transport=ScriptedTransport, **config):
    clock = Clock()
    monkeypatch.setattr(
        coordinator, "time", SimpleNamespace(monotonic=clock.monotonic, sleep=clock.sleep)
    )
    options = RunConfig(rounds=16, deadline=0.2, poll_interval=0.025, **config)
    manifest = {
        "banks": 3,
        "pos_weight": 1.0,
        "synthetic": True,
        "partitions": {"train": {bank: {"samples": 10} for bank in options.bank_ids}},
    }
    directory = coordinator.run(
        options,
        manifest,
        transport(clock, config.get("label") == "one"),
        tmp_path,
        "scripted_test",
    )
    summary = json.loads((directory / "summary.json").read_text())
    events = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
    return summary, events


def test_early_quorum_stale_rejection_and_rejoin(tmp_path, monkeypatch):
    summary, events = exercise(tmp_path, monkeypatch)
    first = next(event for event in events if event["event"] == "committed")
    assert first["accepted"] == ["bank-1", "bank-2"]
    assert summary["status"] == "completed"
    assert summary["rejections"]["stale"] >= 1
    assert summary["participation"]["bank-3"] > 0
    assert summary["unresolved_requests"] == 0


def test_bank_leaving_and_rejoining_is_logged(tmp_path, monkeypatch, capsys):
    summary, events = exercise(tmp_path, monkeypatch, transport=FlakyTransport)
    changes = [
        (e["event"], e["bank"], e.get("rejoined"))
        for e in events
        if e["event"] in {"bank_left", "bank_joined"}
    ]
    assert changes == [
        ("bank_joined", "bank-1", False),
        ("bank_joined", "bank-2", False),
        ("bank_joined", "bank-3", False),
        ("bank_left", "bank-3", None),
        ("bank_joined", "bank-3", True),
    ]
    assert summary["status"] == "completed"
    output = capsys.readouterr().out
    assert "bank-3 went offline - training continues without it" in output
    assert "bank-3 is back online" in output


def test_below_quorum_is_bounded_and_never_publishes_a_model(tmp_path, monkeypatch):
    summary, _ = exercise(tmp_path, monkeypatch, label="one")
    assert summary["status"] == "insufficient_quorum"
    assert summary["committed_rounds"] == 0
    assert summary["attempts"] == 3
    assert len(list(tmp_path.rglob("model-*.npz"))) == 1


def test_strict_sync_does_not_accept_partial_round(tmp_path, monkeypatch):
    summary, events = exercise(tmp_path, monkeypatch, mode="synchronous")
    assert summary["status"] == "completed"
    assert next(e for e in events if e["event"] == "deadline")["valid"] == 2
    assert all(len(e["accepted"]) == 3 for e in events if e["event"] == "committed")


def test_timeout_mode_keeps_valid_partial_results_until_deadline(tmp_path, monkeypatch):
    summary, events = exercise(tmp_path, monkeypatch, mode="timeout")
    assert summary["status"] == "completed"
    first = next(e for e in events if e["event"] == "committed")
    assert first["accepted"] == ["bank-1", "bank-2"]
    import csv

    rounds_path = next(tmp_path.rglob("rounds.csv"))
    with rounds_path.open(newline="") as stream:
        first_row = next(csv.DictReader(stream))
    assert float(first_row["seconds"]) >= 0.2


def test_returning_bank_waits_for_next_round_boundary(tmp_path, monkeypatch):
    _, events = exercise(tmp_path, monkeypatch)
    active_attempt = 0
    stale_during = None
    rejoined = False
    for event in events:
        if event["event"] == "attempt_started":
            active_attempt = event["attempt"]
        elif (
            event["event"] == "reply" and event["bank"] == "bank-3" and event["outcome"] == "stale"
        ):
            stale_during = active_attempt
        elif (
            event["event"] == "dispatched"
            and event["bank"] == "bank-3"
            and stale_during is not None
        ):
            assert event["attempt"] > stale_during
            rejoined = True
    assert rejoined
