"""Start one federated training run from inside the cluster.

The Kubernetes CronJob in k8s/deployment.yaml runs this on a schedule (weekly
retraining). It reaches the coordinator through its Service name, so it needs no
port-forward, and it streams the run's log so the Job's own log shows progress.
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from app.bundle import stage_bundle
from app.config import RunConfig


def command(package: Path, coordinator: str, config: RunConfig):
    flwr = str(Path(sys.executable).parent / "flwr")
    return [
        flwr,
        "run",
        str(package),
        "local",
        "--stream",
        # Point the "local" federation from pyproject.toml at the in-cluster Service.
        "--federation-config",
        f'address="{coordinator}"',
        "--run-config",
        f'rounds={config.rounds} deadline={config.deadline} mu={config.mu} label="scheduled"',
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coordinator", default="coordinator:9093")
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--deadline", type=float, default=30.0)
    parser.add_argument("--mu", type=float, default=0.0, help="FedProx strength (0 = FedAvg)")
    args = parser.parse_args(argv)
    # Validate before contacting the cluster, so a bad schedule fails fast and clearly.
    config = RunConfig(rounds=args.rounds, deadline=args.deadline, mu=args.mu)
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as temporary:
        package = stage_bundle(Path(temporary), root)
        return subprocess.run(command(package, args.coordinator, config), check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
