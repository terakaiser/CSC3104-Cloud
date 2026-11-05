"""Inject one reversible Kubernetes client failure and record recovery."""

import argparse
import json
import subprocess
import time
from pathlib import Path

from app.data import write_json


def kubectl(*args):
    return subprocess.run(
        ["kubectl", "-n", "bank-fl", *args], check=True, capture_output=True, text=True
    ).stdout


def inject(bank: str, kind: str, duration: float, timeout: float, output: Path):
    # Restrict mutations to this project's exact namespace and bank deployments.
    if bank not in {f"bank-{i}" for i in range(1, 6)}:
        raise ValueError("bank must be bank-1 through bank-5")
    deployment = json.loads(kubectl("get", "deployment", bank, "-o", "json"))
    original_replicas = deployment["spec"]["replicas"]
    if original_replicas != 1:
        raise ValueError("expected exactly one bank replica before fault injection")
    pods = json.loads(kubectl("get", "pods", "-l", f"app={bank}", "-o", "json"))["items"]
    if len(pods) != 1:
        raise ValueError("expected one bank pod")
    original_name = pods[0]["metadata"]["name"]
    original_uid = pods[0]["metadata"]["uid"]
    started = time.monotonic()
    record = {
        "bank": bank,
        "kind": kind,
        "unix_time": time.time(),
        "duration": duration,
        "status": "starting",
        "deleted_pod": original_name,
        "deleted_uid": original_uid,
        "replacement_pod": None,
        "replacement_uid": None,
        "fault_to_ready_seconds": None,
    }
    output.parent.mkdir(parents=True, exist_ok=True)

    def save_record():
        temporary = output.with_suffix(output.suffix + ".tmp")
        write_json(temporary, record)
        temporary.replace(output)

    try:
        record["status"] = "deleting"
        save_record()
        if kind == "kill":
            kubectl("delete", "pod", original_name, "--wait=false")
        else:
            kubectl("scale", "deployment", bank, "--replicas=0")
            try:
                time.sleep(duration)
            finally:
                kubectl("scale", "deployment", bank, f"--replicas={original_replicas}")
        record["fault_to_ready_seconds"] = None
        record["status"] = "waiting_for_replacement"
        save_record()
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            replacements = json.loads(kubectl("get", "pods", "-l", f"app={bank}", "-o", "json"))[
                "items"
            ]
            replacement = next(
                (pod for pod in replacements if pod["metadata"]["uid"] != original_uid), None
            )
            if replacement:
                metadata = replacement["metadata"]
                record["replacement_pod"] = metadata["name"]
                record["replacement_uid"] = metadata["uid"]
                conditions = replacement.get("status", {}).get("conditions", [])
                ready = any(
                    condition["type"] == "Ready" and condition["status"] == "True"
                    for condition in conditions
                )
                record["status"] = (
                    "ready"
                    if ready
                    else replacement.get("status", {}).get("phase", "starting").lower()
                )
                if ready:
                    record["fault_to_ready_seconds"] = time.monotonic() - started
                    save_record()
                    break
            save_record()
            time.sleep(0.5)
        record["recovery_censored"] = record["fault_to_ready_seconds"] is None
        if record["recovery_censored"]:
            record["status"] = "timed_out"
        save_record()
    except BaseException as exc:
        record["status"] = "failed"
        record["error"] = str(exc)
        record["recovery_censored"] = True
        save_record()
        raise
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank", default="bank-3")
    parser.add_argument("--kind", choices=["kill", "absence"], required=True)
    parser.add_argument("--duration", type=float, default=20)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--output", type=Path, default=Path("results/fault.json"))
    args = parser.parse_args()
    if args.duration < 0 or args.timeout <= 0:
        parser.error("duration must be non-negative and timeout positive")
    print(
        json.dumps(inject(args.bank, args.kind, args.duration, args.timeout, args.output), indent=2)
    )


if __name__ == "__main__":
    main()
