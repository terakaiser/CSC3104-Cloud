"""Per-pod CPU and memory, read from the Kubernetes metrics API (metrics-server).

These are the cluster's own measurements of each pod, unlike the process-level
numbers in telemetry.py. metrics-server refreshes them about every 15 seconds.
"""

import csv
import json
import threading
import time
from datetime import datetime
from pathlib import Path

METRICS_PATH = "/apis/metrics.k8s.io/v1beta1/namespaces/bank-fl/pods"
FIELDS = ["unix_time", "elapsed_seconds", "pod", "role", "cpu_millicores", "memory_mib"]
CPU_UNITS = {"n": 1e-6, "u": 1e-3, "m": 1.0}  # to millicores; no suffix means whole cores
MEMORY_UNITS = {"Ki": 1 / 1024, "Mi": 1.0, "Gi": 1024.0}  # to MiB; no suffix means bytes


def parse_cpu(quantity: str) -> float:
    """Kubernetes CPU quantity ("2845341n", "3m", "1") in millicores."""
    if quantity[-1] in CPU_UNITS:
        return float(quantity[:-1]) * CPU_UNITS[quantity[-1]]
    return float(quantity) * 1000


def parse_memory(quantity: str) -> float:
    """Kubernetes memory quantity ("215040Ki", "210Mi", bytes) in MiB."""
    if quantity[-2:] in MEMORY_UNITS:
        return float(quantity[:-2]) * MEMORY_UNITS[quantity[-2:]]
    return float(quantity) / 1024**2


def pod_usage(kubectl) -> list[dict]:
    """Current usage of every pod in the namespace; kubectl is a callable returning stdout."""
    usage = []
    for item in json.loads(kubectl("get", "--raw", METRICS_PATH)).get("items", []):
        metadata = item["metadata"]
        containers = item.get("containers", [])
        usage.append(
            {
                "unix_time": datetime.fromisoformat(
                    item["timestamp"].replace("Z", "+00:00")
                ).timestamp(),
                "pod": metadata["name"],
                # The app label survives pod replacement, so a killed bank keeps one role.
                "role": metadata.get("labels", {}).get("app", metadata["name"]),
                "cpu_millicores": sum(parse_cpu(c["usage"]["cpu"]) for c in containers),
                "memory_mib": sum(parse_memory(c["usage"]["memory"]) for c in containers),
            }
        )
    return usage


class Sampler:
    """Background thread that appends each new pod measurement to a CSV file."""

    def __init__(self, kubectl, path: Path, interval=5.0):
        self.kubectl, self.path, self.interval = kubectl, path, interval
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self):
        self.started = time.time()
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join(timeout=30)

    def _run(self):
        seen = set()  # metrics-server repeats a measurement until its next scrape
        with self.path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            while True:
                try:
                    rows = pod_usage(self.kubectl)
                except Exception:  # noqa: BLE001 - metrics are optional; never stop training
                    rows = []
                for row in rows:
                    key = (row["pod"], row["unix_time"])
                    if key not in seen:
                        seen.add(key)
                        writer.writerow(
                            {**row, "elapsed_seconds": round(row["unix_time"] - self.started, 1)}
                        )
                stream.flush()
                if self.stop.wait(self.interval):
                    return


def summarize(path: Path) -> dict:
    """Mean and peak CPU/memory per role (coordinator, bank-1, ...) from a sampler CSV."""
    by_role = {}
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            by_role.setdefault(row["role"], []).append(
                (float(row["cpu_millicores"]), float(row["memory_mib"]))
            )
    return {
        role: {
            "samples": len(values),
            "cpu_millicores_mean": sum(cpu for cpu, _ in values) / len(values),
            "cpu_millicores_peak": max(cpu for cpu, _ in values),
            "memory_mib_mean": sum(memory for _, memory in values) / len(values),
            "memory_mib_peak": max(memory for _, memory in values),
        }
        for role, values in sorted(by_role.items())
    }
