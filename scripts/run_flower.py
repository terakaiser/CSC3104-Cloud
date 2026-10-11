"""Run exactly three local Flower clients using the public Simulation Runtime."""
import json
import os
from pathlib import Path
import sys
import tomllib
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from crossbank.baselines import training_parser


def main():
    parser = training_parser(__doc__)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--local-epochs", type=int, default=1)
    parser.add_argument("--round-timeout", type=float, default=300.0)
    args = parser.parse_args()
    if min(args.rounds, args.local_epochs, args.batch_size) < 1 or args.max_samples < 0:
        parser.error("Rounds, epochs and batch size must be positive; sample cap must be nonnegative")
    if args.learning_rate <= 0 or args.round_timeout <= 0:
        parser.error("Learning rate and timeout must be positive")
    data_dir = args.data_dir.resolve()
    for filename in ("bank_a.csv", "bank_b.csv", "bank_c.csv", "validation.csv"):
        if not (data_dir / filename).is_file():
            parser.error(f"Missing {data_dir / filename}; prepare PaySim or create smoke fixtures first")

    # Set telemetry preferences before importing the runtime.
    os.environ["FLWR_TELEMETRY_ENABLED"] = "0"
    os.environ["RAY_USAGE_STATS_ENABLED"] = "0"
    from flwr.server import ServerApp
    from flwr.simulation import run_simulation
    from crossbank.fl.client_app import app as client_app
    from crossbank.fl.server_app import main as run_server

    launch_dir = args.output_dir.resolve() / f"flower-launch-{uuid4().hex[:8]}"
    launch_dir.mkdir(parents=True)
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["flwr"]["app"]["config"]
    config.update({
        "data-dir": str(data_dir), "output-dir": str(launch_dir),
        "num-server-rounds": args.rounds, "local-epochs": args.local_epochs,
        "batch-size": args.batch_size, "learning-rate": args.learning_rate,
        "max-samples": args.max_samples, "seed": args.seed, "round-timeout": args.round_timeout,
    })
    (launch_dir / "run-config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    server_app = ServerApp()

    @server_app.main()
    def configured_server(grid, context):
        context.run_config.update(config)
        run_server(grid, context)

    run_simulation(
        server_app=server_app, client_app=client_app, num_supernodes=3,
        backend_config={
            "init_args": {"num_cpus": 3, "include_dashboard": False},
            "client_resources": {"num_cpus": 1, "num_gpus": 0.0},
        },
    )
    # Some runtime errors are surfaced in worker logs; require artifact readback.
    statuses = list(launch_dir.glob("flower-*/status.json"))
    completed = [path for path in statuses if json.loads(path.read_text())["status"] == "completed"]
    if len(completed) != 1:
        raise SystemExit(f"Flower run did not complete. Inspect logs and {launch_dir}")
    print(f"Completed three-bank Flower run: {completed[0].parent}")


if __name__ == "__main__":
    main()
