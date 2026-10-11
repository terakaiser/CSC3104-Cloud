"""Educational sequential FedAvg; use run_flower.py for the Flower runtime."""
from copy import deepcopy
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from crossbank.baselines import training_parser
from crossbank.data.fl_preprocessing import BANKS, load_bank_data, load_fl_data
from crossbank.experiments import create_run, save_checkpoint, validation_metrics, write_json
from crossbank.fl.fedavg import fedavg
from crossbank.models.mlp import FraudMLP
from crossbank.models.training import seed_everything, train_model


def main():
    parser = training_parser(__doc__)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--local-epochs", type=int, default=1)
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("rounds must be positive")
    config = {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()}
    clients = [load_bank_data(args.data_dir, bank, max_samples=args.max_samples, seed=args.seed) for bank in BANKS]
    X_val, y_val = load_fl_data(args.data_dir / "validation.csv")
    seed_everything(args.seed)
    model = FraudMLP()
    directory = create_run(args.output_dir, "in-process-fedavg", config)
    history = []
    for round_number in range(1, args.rounds + 1):
        started = perf_counter()
        states, sizes = [], []
        for partition_id, (X, y) in enumerate(clients):
            local = deepcopy(model)
            train_model(local, X, y, epochs=args.local_epochs, batch_size=args.batch_size,
                        learning_rate=args.learning_rate, seed=args.seed + 1000 * round_number + partition_id)
            states.append(local.state_dict())
            sizes.append(len(y))
        model.load_state_dict(fedavg(states, sizes))
        training_seconds = perf_counter() - started
        metrics = validation_metrics(model, X_val, y_val)
        history.append({"round": round_number, "training_seconds": training_seconds, **metrics})
        write_json(directory / "metrics.json", history)
        save_checkpoint(directory / f"round-{round_number:03d}.pt", model,
                        threshold=metrics["threshold"], config=config, round_number=round_number)
        print(f"Round {round_number}: {metrics}")
    save_checkpoint(directory / "global_model.pt", model, threshold=metrics["threshold"],
                    config=config, round_number=args.rounds)
    print(f"Saved to {directory.resolve()}")


if __name__ == "__main__":
    main()
