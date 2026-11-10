"""Repeat local-harness or real Flower experiments from a small YAML configuration."""

import argparse
import json
import time
from pathlib import Path

import torch
import yaml

from app.config import RunConfig, majority
from app.coordinator import run
from app.data import read_manifest
from app.local import LocalTransport
from experiments.centralized import run_centralized
from experiments.evaluate import evaluate
from experiments.flower_local import launch
from experiments.plot import plot_runs


def plan(settings, banks, scenarios, fedprox):
    """Every run of the study as (key, RunConfig); key is None-safe JSON for resuming."""
    quorum = majority(banks)
    for seed in settings["seeds"]:
        base = dict(
            banks=banks,
            quorum=quorum,
            seed=seed,
            rounds=settings["rounds"],
            deadline=settings["deadline"],
        )
        yield {"kind": "centralized", "seed": seed, **base}, RunConfig(**base)
        for scenario in scenarios:
            modes = ["synchronous", "resilient"]
            if scenario in {"healthy", "slow"}:
                modes.append("timeout")
            # FedProx is compared with FedAvg where nothing else differs: healthy, resilient.
            strengths = {mode: [0.0] for mode in modes}
            if scenario == "healthy":
                strengths["resilient"] = [0.0, *fedprox]
            for mode in modes:
                for mu in strengths[mode]:
                    config = RunConfig(
                        **base,
                        **settings["scenarios"][scenario],
                        mode=mode,
                        mu=mu,
                        slow_bank=f"bank-{seed % banks + 1}",
                        label=f"{scenario}-{seed}",
                    )
                    key = {"kind": "federated", "scenario": scenario, "mode": mode, "mu": mu}
                    yield {**key, **base}, config


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/processed"))
    parser.add_argument("--output", type=Path, default=Path("results/study"))
    parser.add_argument("--config", type=Path, default=Path("experiments/scenarios.yaml"))
    parser.add_argument("--runtime", choices=["local", "flower"], default="flower")
    parser.add_argument("--scenarios", nargs="+", default=["healthy", "slow", "unavailable"])
    parser.add_argument("--seeds", type=int, nargs="+", help="override the configured seeds")
    parser.add_argument("--rounds", type=int, help="override the configured rounds")
    parser.add_argument(
        "--fedprox",
        type=float,
        nargs="*",
        default=[0.1],
        help="FedProx strengths (mu) also run in the healthy resilient setting",
    )
    args = parser.parse_args(argv)
    torch.set_num_threads(1)
    settings = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    if args.seeds:
        settings["seeds"] = args.seeds
    if args.rounds:
        settings["rounds"] = args.rounds
    manifest = read_manifest(args.data)
    banks = manifest["banks"]
    args.output.mkdir(parents=True, exist_ok=True)
    # One line per finished run. An interrupted study resumes from here, and a failed run
    # is recorded and skipped rather than discarding the hours of runs before it.
    progress = args.output / "progress.jsonl"
    finished = {}
    if progress.exists():
        for line in progress.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            if entry.get("directory") and Path(entry["directory"], "evaluation.json").exists():
                finished[json.dumps(entry["key"], sort_keys=True)] = Path(entry["directory"])
    runs = list(plan(settings, banks, args.scenarios, args.fedprox))
    directories = []
    for number, (key, config) in enumerate(runs, 1):
        name = json.dumps(key, sort_keys=True)
        label = " ".join(
            f"{k}={key[k]}" for k in ("kind", "scenario", "mode", "mu", "seed") if k in key
        )
        if name in finished:
            print(f"[{number}/{len(runs)}] already done: {label}", flush=True)
            directories.append(finished[name])
            continue
        print(f"[{number}/{len(runs)}] starting: {label}", flush=True)
        started = time.time()
        entry = {"key": key}
        try:
            if key["kind"] == "centralized":
                directory = run_centralized(config, args.data, args.output)
            elif args.runtime == "flower":
                try:
                    directory = launch(config, args.data, args.output)
                except TimeoutError as error:  # retry one SuperLink stall before giving up
                    print(f"    retrying: {error}", flush=True)
                    directory = launch(config, args.data, args.output)
            else:
                absent = [config.slow_bank] if config.scenario == "unavailable" else []
                directory = run(
                    config,
                    manifest,
                    LocalTransport(args.data, config.bank_ids, absent),
                    args.output,
                    "local_threads",
                )
            evaluate(directory, args.data)
            directories.append(directory)
            entry["directory"] = str(directory)
        except Exception as exc:  # noqa: BLE001 - keep the rest of a long study
            entry["error"] = f"{type(exc).__name__}: {exc}"
            print(f"    FAILED: {entry['error']}", flush=True)
        entry["seconds"] = round(time.time() - started, 1)
        with progress.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry) + "\n")
        print(f"    finished in {entry['seconds']:.0f} s", flush=True)
    if not directories:
        raise SystemExit("No run finished; see progress.jsonl.")
    plot_runs(directories, args.output / "figures")
    print(f"Study complete: {len(directories)} of {len(runs)} runs. {args.output / 'figures'}")


if __name__ == "__main__":
    main()
