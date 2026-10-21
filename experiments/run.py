"""Repeat local-harness or real Flower experiments from a small YAML configuration."""

import argparse
from pathlib import Path

import torch
import yaml

from app.config import RunConfig
from app.coordinator import run
from app.data import read_manifest
from app.local import LocalTransport
from experiments.centralized import run_centralized
from experiments.evaluate import evaluate
from experiments.flower_local import launch
from experiments.plot import plot_runs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/processed"))
    parser.add_argument("--output", type=Path, default=Path("results/study"))
    parser.add_argument("--config", type=Path, default=Path("experiments/scenarios.yaml"))
    parser.add_argument("--runtime", choices=["local", "flower"], default="flower")
    parser.add_argument("--scenarios", nargs="+", default=["healthy", "slow", "unavailable"])
    args = parser.parse_args()
    torch.set_num_threads(1)
    settings = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    manifest = read_manifest(args.data)
    banks = manifest["banks"]
    quorum = banks // 2 + 1
    directories = []
    for seed in settings["seeds"]:
        base = dict(
            banks=banks,
            quorum=quorum,
            seed=seed,
            rounds=settings["rounds"],
            deadline=settings["deadline"],
        )
        centralized = run_centralized(RunConfig(**base), args.data, args.output)
        evaluate(centralized, args.data)
        directories.append(centralized)
        for scenario in args.scenarios:
            modes = ["synchronous", "resilient"]
            if scenario in {"healthy", "slow"}:
                modes.append("timeout")
            for mode in modes:
                config = RunConfig(
                    **base,
                    **settings["scenarios"][scenario],
                    mode=mode,
                    slow_bank=f"bank-{seed % banks + 1}",
                    label=f"{scenario}-{seed}",
                )
                if args.runtime == "flower":
                    directory = launch(config, args.data, args.output)
                else:
                    absent = [config.slow_bank] if scenario == "unavailable" else []
                    directory = run(
                        config,
                        manifest,
                        LocalTransport(args.data, config.bank_ids, absent),
                        args.output,
                        "local_threads",
                    )
                evaluate(directory, args.data)
                directories.append(directory)
    plot_runs(directories, args.output / "figures")


if __name__ == "__main__":
    main()
