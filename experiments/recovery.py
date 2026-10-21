"""Join a recorded Kubernetes fault with the first subsequently accepted update."""

import argparse
import json
from pathlib import Path

from app.data import write_json


def summarize(directory: Path, fault_path: Path):
    fault = json.loads(fault_path.read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
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
        and e["unix_time"] >= fault["unix_time"]
        and e.get("request_id") in fresh_requests
    ]
    result = {
        **fault,
        "fault_to_accepted_update_seconds": min(returned) - fault["unix_time"]
        if returned
        else None,
        "participation_recovery_censored": not returned,
        "definition": "first accepted reply dispatched after replacement pod readiness",
        "clock_note": "Requires synchronized operator/coordinator wall clocks (e.g. NTP).",
    }
    write_json(directory / "recovery.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("fault", type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(args.directory, args.fault), indent=2))


if __name__ == "__main__":
    main()
