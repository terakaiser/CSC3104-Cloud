"""Tiny artificial fixtures for execution tests only, never fraud benchmarks."""
from pathlib import Path
import numpy as np
import pandas as pd

from crossbank.data.fl_preprocessing import TRANSACTION_TYPES


def create_smoke_data(output_dir, rows=256, seed=42):
    if rows < 20:
        raise ValueError("Use at least 20 rows per fixture")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    rng = np.random.default_rng(seed)
    for name, low, high in [("bank_a", 1, 521), ("bank_b", 1, 521), ("bank_c", 1, 521),
                             ("validation", 521, 633), ("test", 633, 744)]:
        labels = np.zeros(rows, dtype=int)
        labels[::10] = 1
        amount = rng.lognormal(5, 1, rows)
        kinds = rng.choice(TRANSACTION_TYPES, rows)
        kinds[labels == 1] = "TRANSFER"
        pd.DataFrame({
            "step": rng.integers(low, high, rows), "type": kinds, "amount": amount,
            "oldbalanceOrg": np.where(labels, amount, amount * rng.uniform(1.1, 5, rows)),
            "oldbalanceDest": rng.lognormal(6, 2, rows), "isFraud": labels,
        }).to_csv(output_dir / f"{name}.csv", index=False)
    (output_dir / "SYNTHETIC_SMOKE_ONLY.txt").write_text(
        "Artificial execution fixtures; not PaySim and not evidence of fraud-detection performance.\n",
        encoding="utf-8",
    )
