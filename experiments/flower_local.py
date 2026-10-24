"""Launch real Flower infrastructure on loopback, without requiring Docker."""

import json
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import psutil

from app.bundle import stage_bundle
from app.config import RunConfig
from app.data import read_manifest


def stop_process(process):
    if process.poll() is not None:
        return
    try:
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        for child in reversed(children):
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        parent.terminate()
        _, alive = psutil.wait_procs([parent, *children], timeout=5)
        for child in alive:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
    except psutil.NoSuchProcess:
        pass


def executable(name):
    suffix = ".exe" if os.name == "nt" else ""
    return str(Path(sys.executable).parent / (name + suffix))


def launch(config: RunConfig, data: Path, output: Path):
    data = data.resolve()
    output = output.resolve()
    manifest = read_manifest(data)
    if manifest["banks"] != config.banks:
        raise ValueError("bank count must match the dataset")
    for port in [9091, 9092, 9093, *range(9101, 9101 + config.banks)]:
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError as exc:
                raise ValueError(f"local Flower port {port} is already in use") from exc
    runtime = output / ("flower-runtime-" + uuid.uuid4().hex[:8])
    runtime.mkdir(parents=True)
    root = Path(__file__).resolve().parents[1]
    package = stage_bundle(runtime, root)
    env = os.environ.copy()
    env.update(
        {
            "BANK_FL_DATA": str(data),
            "BANK_FL_OUTPUT": str(runtime / "runs"),
            "FLWR_TELEMETRY_ENABLED": "0",
            "PYTHONUNBUFFERED": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "OMP_NUM_THREADS": "1",
        }
    )
    # Subprocess-mode Flower locates its app runners on PATH.
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    processes, streams = [], []
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    def start(name, arguments):
        stream = (runtime / f"{name}.log").open("w", encoding="utf-8")
        streams.append(stream)
        process = subprocess.Popen(
            arguments,
            env={**env, "FLWR_HOME": str(runtime / f"{name}-home")},
            cwd=root,
            stdout=stream,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
        processes.append(process)
        return process

    try:
        superlink = start(
            "coordinator",
            [
                executable("flower-superlink"),
                "--insecure",
                "--serverappio-api-address",
                "127.0.0.1:9091",
                "--fleet-api-address",
                "127.0.0.1:9092",
                "--control-api-address",
                "127.0.0.1:9093",
                "--flwr-dir",
                str(runtime / "server-apps"),
            ],
        )
        until = time.monotonic() + 30
        while True:
            if superlink.poll() is not None:
                raise RuntimeError(f"SuperLink exited; see {runtime / 'coordinator.log'}")
            try:
                with socket.create_connection(("127.0.0.1", 9093), timeout=1):
                    break
            except OSError as exc:
                if time.monotonic() > until:
                    raise TimeoutError("SuperLink did not start within 30 seconds") from exc
                time.sleep(0.2)
        for i, bank in enumerate(config.bank_ids):
            if config.scenario == "unavailable" and bank == config.slow_bank:
                continue
            node_config = (
                f"bank-id={json.dumps(bank)} data-path={json.dumps(str(data / bank / 'train.npz'))}"
            )
            start(
                bank,
                [
                    executable("flower-supernode"),
                    "--insecure",
                    "--superlink",
                    "127.0.0.1:9092",
                    "--clientappio-api-address",
                    f"127.0.0.1:{9101 + i}",
                    "--node-config",
                    node_config,
                    "--flwr-dir",
                    str(runtime / bank),
                ],
            )
        values = {
            k.replace("_", "-"): v for k, v in config.to_dict().items() if k != "poll_interval"
        }
        overrides = " ".join(f"{k}={json.dumps(v)}" for k, v in values.items())
        run_process = start(
            "submission",
            [
                executable("flwr"),
                "run",
                str(package),
                "local",
                "--stream",
                "--run-config",
                overrides,
            ],
        )
        limit = (
            time.monotonic()
            + config.startup_timeout
            + (config.rounds + config.max_failures) * config.deadline
            + config.work_timeout
            + 120
        )
        while run_process.poll() is None:
            if time.monotonic() > limit:
                raise TimeoutError(f"Flower run exceeded its wall-clock guard; logs: {runtime}")
            time.sleep(0.5)
        if run_process.returncode:
            raise RuntimeError(f"Flower submission failed; see {runtime / 'submission.log'}")
        runs = list((runtime / "runs").glob("*/summary.json"))
        if len(runs) != 1:
            raise RuntimeError(f"Expected one completed run; inspect logs in {runtime}")
        return runs[0].parent
    finally:
        for process in reversed(processes):
            stop_process(process)
        for stream in streams:
            stream.close()
