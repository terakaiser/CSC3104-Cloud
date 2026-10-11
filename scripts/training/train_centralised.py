"""Train one pooled MLP on the same bank subsets used by Flower."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from crossbank.baselines import baseline_main

if __name__ == "__main__":
    baseline_main(bank_only=False)
