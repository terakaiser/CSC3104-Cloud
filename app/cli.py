import argparse
import json
from pathlib import Path

from app.config import RunConfig


def add_run_arguments(parser):
    parser.add_argument("--data", type=Path, default=Path("data/processed"))
    parser.add_argument("--output", type=Path, default=Path("results"))
    parser.add_argument(
        "--mode", choices=["resilient", "synchronous", "timeout"], default="resilient"
    )
    parser.add_argument("--banks", type=int, default=3)
    parser.add_argument("--quorum", type=int, default=2)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--deadline", type=float, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=0.01)
    parser.add_argument("--max-failures", type=int, default=3)
    parser.add_argument("--startup-timeout", type=float, default=90)
    parser.add_argument(
        "--scenario", choices=["healthy", "slow", "stale", "unavailable"], default="healthy"
    )
    parser.add_argument("--slow-bank", default="bank-3")
    parser.add_argument("--delay", type=float, default=0)
    parser.add_argument("--fault-attempt", type=int, default=2)
    parser.add_argument("--label", default="run")


def config_from_args(args):
    return RunConfig(
        **{key: value for key, value in vars(args).items() if key in RunConfig.__dataclass_fields__}
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="bank-fl", description="Group 18 · client-resilient federated fraud learning"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("setup-data", help="download and prepare the real ULB dataset")
    setup.add_argument("--raw", type=Path, default=Path("data/raw"))
    setup.add_argument("--output", type=Path, default=Path("data/ulb"))
    setup.add_argument("--banks", type=int, default=3)
    setup.add_argument("--seed", type=int, default=42)
    prepare_cmd = commands.add_parser(
        "prepare", help="prepare real CSV or synthetic test partitions"
    )
    source = prepare_cmd.add_mutually_exclusive_group(required=True)
    source.add_argument("--csv", type=Path)
    source.add_argument("--synthetic", action="store_true")
    prepare_cmd.add_argument("--output", type=Path, default=Path("data/processed"))
    prepare_cmd.add_argument("--rows", type=int, default=6000)
    prepare_cmd.add_argument("--banks", type=int, default=3)
    prepare_cmd.add_argument("--seed", type=int, default=42)
    for name, help_text in [
        ("run", "run the concurrent local harness"),
        ("flower", "launch a real local Flower federation, run, and clean up its processes"),
        ("centralized", "run the pooled-data comparison"),
    ]:
        add_run_arguments(commands.add_parser(name, help=help_text))
    evaluation = commands.add_parser("evaluate", help="evaluate saved checkpoints offline")
    evaluation.add_argument("directory", type=Path)
    evaluation.add_argument("--data", type=Path, default=Path("data/processed"))
    plots = commands.add_parser("plot", help="plot and tabulate one or more evaluated runs")
    plots.add_argument("directories", nargs="+", type=Path)
    plots.add_argument("--output", type=Path, default=Path("results/figures"))
    args = parser.parse_args(argv)
    try:
        if args.command == "setup-data":
            from app.download import setup_data

            result = setup_data(args.raw, args.output, banks=args.banks, seed=args.seed)
            print(json.dumps(result["partitions"]["train"], indent=2))
            return
        if args.command == "prepare":
            from app.data import prepare

            result = prepare(
                args.output, csv=args.csv, rows=args.rows, banks=args.banks, seed=args.seed
            )
            print(f"Prepared {result['source']} at {args.output.resolve()}")
            print(json.dumps(result["partitions"]["train"], indent=2))
            return
        import torch

        torch.set_num_threads(1)
        if args.command == "evaluate":
            from experiments.evaluate import evaluate

            print(json.dumps(evaluate(args.directory, args.data)["final"], indent=2))
        elif args.command == "plot":
            from experiments.plot import plot_runs

            print(plot_runs(args.directories, args.output).resolve())
        else:
            config = config_from_args(args)
            if args.command == "flower":
                from experiments.flower_local import launch

                directory = launch(config, args.data, args.output)
            elif args.command == "centralized":
                from experiments.centralized import run_centralized

                directory = run_centralized(config, args.data, args.output)
            else:
                from app.coordinator import run
                from app.data import read_manifest
                from app.local import LocalTransport

                unavailable = [config.slow_bank] if config.scenario == "unavailable" else []
                directory = run(
                    config,
                    read_manifest(args.data),
                    LocalTransport(args.data, config.bank_ids, unavailable),
                    args.output,
                    "local_threads",
                )
            print(f"\nResults: {directory.resolve()}")
    except (ValueError, FileNotFoundError) as exc:
        parser.exit(2, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
