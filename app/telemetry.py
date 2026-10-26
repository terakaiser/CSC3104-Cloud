import csv
import importlib.metadata
import json
import os
import platform
import threading
import time
from pathlib import Path

import numpy as np
import psutil

from app.data import write_json


class ResourceSample:
    """Sample this process. Local threaded runs share a process; label that explicitly."""

    def __enter__(self):
        self.process = psutil.Process()
        self.started = time.monotonic()
        self.cpu_start = sum(self.process.cpu_times()[:2])
        self.peak = self.process.memory_info().rss
        self.net_start = psutil.net_io_counters()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._sample, daemon=True)
        self.thread.start()
        return self

    def _sample(self):
        while not self.stop.wait(0.1):
            self.peak = max(self.peak, self.process.memory_info().rss)

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join()
        self.peak = max(self.peak, self.process.memory_info().rss)
        network = psutil.net_io_counters()
        elapsed = time.monotonic() - self.started
        cpu = sum(self.process.cpu_times()[:2]) - self.cpu_start
        self.metrics = {
            "wall_seconds": elapsed,
            "cpu_seconds": cpu,
            "cpu_percent_one_core": 100 * cpu / max(elapsed, 1e-9),
            "peak_process_rss_bytes": self.peak,
            "sampling_interval_seconds": 0.1,
            "network_sent_bytes": network.bytes_sent - self.net_start.bytes_sent,
            "network_received_bytes": network.bytes_recv - self.net_start.bytes_recv,
            "network_scope": "pod" if os.environ.get("KUBERNETES_SERVICE_HOST") else "host_shared",
        }


class RunLog:
    def __init__(self, root: Path, run_id: str, config: dict, manifest: dict, runtime: str):
        self.directory = root / run_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.started = time.monotonic()
        self.events = (self.directory / "events.jsonl").open("w", encoding="utf-8")
        self.round_file = (self.directory / "rounds.csv").open("w", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(
            self.round_file,
            fieldnames=[
                "attempt",
                "version",
                "status",
                "seconds",
                "elapsed_seconds",
                "accepted",
                "samples",
                "tensor_bytes_sent",
                "tensor_bytes_received",
            ],
        )
        self.writer.writeheader()
        versions = {}
        for package in ("flwr", "torch", "numpy", "scikit-learn", "pandas"):
            versions[package] = importlib.metadata.version(package)
        write_json(
            self.directory / "run.json",
            {
                "run_id": run_id,
                "runtime": runtime,
                "config": config,
                "dataset": manifest,
                "versions": versions,
                "python": platform.python_version(),
                "platform": platform.platform(),
                "logical_cpus": os.cpu_count(),
                "memory_bytes": psutil.virtual_memory().total,
            },
        )

    def event(self, name: str, **details):
        record = {
            "event": name,
            "unix_time": time.time(),
            "elapsed_seconds": time.monotonic() - self.started,
            **details,
        }
        self.events.write(json.dumps(record, allow_nan=False) + "\n")
        self.events.flush()
        if name == "committed":
            banks = ", ".join(details.get("accepted", ["pooled training"]))
            message = f"Round {details['version']} committed - {banks} contributed"
        elif name == "deadline":
            message = (
                f"Attempt {details['attempt']} missed its deadline - "
                f"{details['valid']}/{details['required']} required replies; model unchanged"
            )
        elif name == "bank_left":
            message = f"{details['bank']} went offline - training continues without it"
        elif name == "bank_joined":
            message = (
                f"{details['bank']} is back online - it gets work from the next round"
                if details["rejoined"]
                else f"{details['bank']} connected"
            )
        elif name == "startup_failed":
            message = f"Startup failed - need {details['required']} available banks"
        elif name == "finished":
            message = (
                f"Training {details['status']} - {details['committed_rounds']} rounds committed"
            )
        else:
            return
        print(f"[{record['elapsed_seconds']:7.2f}s] {message}", flush=True)

    def round(self, **row):
        self.writer.writerow(row)
        self.round_file.flush()

    def checkpoint(self, version, weights):
        # Atomic replacement keeps a partial write from becoming a valid checkpoint.
        temporary = self.directory / f".model-{version:03d}.npz"
        with temporary.open("wb") as stream:
            np.savez(stream, *weights)
        temporary.replace(self.directory / f"model-{version:03d}.npz")

    def finish(self, summary):
        self.event("finished", **summary)
        write_json(self.directory / "summary.json", summary)

    def close(self):
        self.events.close()
        self.round_file.close()
