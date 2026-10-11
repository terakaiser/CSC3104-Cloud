"""Explicit final evaluation using the validation-selected checkpoint threshold."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from crossbank.data.fl_preprocessing import load_fl_data
from crossbank.experiments import load_checkpoint, write_json
from crossbank.models.metrics import evaluate
from crossbank.models.training import scores, seed_everything


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--test-data", type=Path, default=Path("data/processed/test.csv"))
    args = parser.parse_args()
    seed_everything(42)
    model, checkpoint = load_checkpoint(args.checkpoint)
    X, y = load_fl_data(args.test_data)
    metrics = {"split": "test", "checkpoint": str(args.checkpoint.resolve()),
               "test_data": str(args.test_data.resolve()), "threshold": checkpoint["threshold"],
               **evaluate(y, scores(model, X), checkpoint["threshold"])}
    write_json(args.checkpoint.with_suffix(".test.json"), metrics)
    print(metrics)


if __name__ == "__main__":
    main()
