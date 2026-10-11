"""Optional check against prepared PaySim files; safe to import during tests."""
from pathlib import Path
import sys
import argparse
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from crossbank.data.fl_preprocessing import BANKS, load_fl_data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/processed"))
    args = parser.parse_args()
    for bank in BANKS:
        X, y = load_fl_data(args.data_dir / f"bank_{bank}.csv")
        assert X.shape[1] == 9 and np.isfinite(X).all()
        assert set(np.unique(y)).issubset({0.0, 1.0})
        print(f"Bank {bank.upper()}: {len(y)} rows, {int(y.sum())} fraud cases, {X.shape[1]} features")


if __name__ == "__main__":
    main()
