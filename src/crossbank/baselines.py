"""Command-line local and pooled MLP baselines using the FL feature contract."""
import argparse
from pathlib import Path
from time import perf_counter

import numpy as np

from crossbank.data.fl_preprocessing import BANKS, load_bank_data, load_fl_data
from crossbank.experiments import create_run, save_checkpoint, validation_metrics, write_json
from crossbank.models.mlp import FraudMLP
from crossbank.models.training import seed_everything, train_model
from crossbank.reporting import readable_metrics, save_summary


def training_parser(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--data-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--output-dir", type=Path, default=Path("results/runs"))
    parser.add_argument("--batch-size", type=int, default=1024)
    parser.add_argument("--learning-rate", type=float, default=0.001)
    parser.add_argument("--max-samples", type=int, default=100000, help="Per-bank cap; 0 uses all rows")
    parser.add_argument("--seed", type=int, default=42)
    return parser


def baseline_main(*, bank_only):
    parser = training_parser("Train a bank-local MLP" if bank_only else "Train a pooled MLP")
    parser.add_argument("--epochs", type=int, default=2)
    if bank_only:
        parser.add_argument("--bank", choices=BANKS, default="a")
    args = parser.parse_args()
    config = {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()}
    banks = [args.bank] if bank_only else BANKS
    parts = [load_bank_data(args.data_dir, bank, max_samples=args.max_samples, seed=args.seed) for bank in banks]
    X = np.concatenate([part[0] for part in parts])
    y = np.concatenate([part[1] for part in parts])
    X_val, y_val = load_fl_data(args.data_dir / "validation.csv")
    seed_everything(args.seed)
    model = FraudMLP()
    started = perf_counter()
    losses = train_model(model, X, y, epochs=args.epochs, batch_size=args.batch_size,
                         learning_rate=args.learning_rate, seed=args.seed)
    training_seconds = perf_counter() - started
    metrics = validation_metrics(model, X_val, y_val)
    directory = create_run(args.output_dir, f"bank_{args.bank}_only" if bank_only else "all_banks_pooled", config)
    write_json(directory / "validation_results.json", readable_metrics({
        "split": "validation", "training_rows": len(y), "fraud_rows": int(y.sum()),
        "epoch_losses": losses, "training_seconds": training_seconds, **metrics,
    }))
    save_checkpoint(directory / "final_model.pt", model, threshold=metrics["threshold"], config=config, round_number=0)
    save_summary(directory, metrics, title=f"Bank {args.bank.upper()} validation results" if bank_only else "Pooled banks validation results")
    print(f"Results folder: {directory.resolve()}")
