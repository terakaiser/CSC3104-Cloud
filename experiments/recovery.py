"""Join recorded Kubernetes faults with the first subsequently accepted update."""

import argparse
import json
from pathlib import Path

from app.data import write_json


def _events(directory: Path):
    return [
        json.loads(line)
        for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def _recovery(fault, events, until=float("inf")):
    """Recovery of one fault. A bank killed again before rejoining counts as not recovered."""
    ready_delay = fault.get("fault_to_ready_seconds")
    ready_time = fault["unix_time"] + ready_delay if ready_delay is not None else float("inf")
    fresh_requests = {
        e["request_id"]
        for e in events
        if e["event"] == "dispatched"
        and e["bank"] == fault["bank"]
        and e["unix_time"] >= ready_time
        and "request_id" in e
    }
    returned = [
        e["unix_time"]
        for e in events
        if e["event"] == "reply"
        and e["bank"] == fault["bank"]
        and e["outcome"] == "accepted"
        and fault["unix_time"] <= e["unix_time"] < until
        and e.get("request_id") in fresh_requests
    ]
    return {
        **fault,
        "fault_to_accepted_update_seconds": min(returned) - fault["unix_time"]
        if returned
        else None,
        "participation_recovery_censored": not returned,
        "definition": "first accepted reply dispatched after replacement pod readiness",
        "clock_note": "Requires synchronized operator/coordinator wall clocks (e.g. NTP).",
    }


def summarize(directory: Path, fault_path: Path):
    result = _recovery(json.loads(fault_path.read_text(encoding="utf-8")), _events(directory))
    write_json(directory / "recovery.json", result)
    return result


def summarize_all(directory: Path, fault_paths: list[Path]):
    """Recovery for every kill in a run, written to one recovery.json."""
    events = _events(directory)
    faults = [json.loads(path.read_text(encoding="utf-8")) for path in fault_paths]
    results = []
    for index, fault in enumerate(faults):
        # A recovery must happen before the same bank is killed again.
        later = [
            other["unix_time"] for other in faults[index + 1 :] if other["bank"] == fault["bank"]
        ]
        results.append(_recovery(fault, events, min(later, default=float("inf"))))
    # Top-level fields describe the first kill, so single-fault readers (plots) keep working.
    result = {**results[0], "faults": results}
    write_json(directory / "recovery.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("faults", type=Path, nargs="+")
    args = parser.parse_args()
    print(json.dumps(summarize_all(args.directory, args.faults), indent=2))


if __name__ == "__main__":
    main()
