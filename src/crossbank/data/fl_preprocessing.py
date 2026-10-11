
import numpy as np
import pandas as pd

# All banks must use the same features in the same order
FEATURES = [
    "step",
    "amount",
    "oldbalanceOrg",
    "oldbalanceDest",
    "type_CASH_IN",
    "type_CASH_OUT",
    "type_DEBIT",
    "type_PAYMENT",
    "type_TRANSFER",
]

TRANSACTION_TYPES = [
    "CASH_IN",
    "CASH_OUT",
    "DEBIT",
    "PAYMENT",
    "TRANSFER",
]

PREPROCESSING_VERSION = "paysim-fixed-nine-v1"
BANKS = ("a", "b", "c")


def load_fl_data(path):
    """
    Load PaySim transactions and apply identical
    preprocessing for every federated-learning bank.

    Returns:
        X: Transaction features
        y: Fraud labels (0 or 1)
    """

    # 1. Read transaction data
    df = pd.read_csv(
        path,
        usecols=[
            "step",
            "type",
            "amount",
            "oldbalanceOrg",
            "oldbalanceDest",
            "isFraud",
        ],
    )

    if df.empty:
        raise ValueError(f"Empty dataset: {path}")
    if not df["type"].isin(TRANSACTION_TYPES).all():
        raise ValueError(f"Unknown or missing transaction type in {path}")
    if not df["isFraud"].isin([0, 1]).all():
        raise ValueError(f"Fraud labels must be binary in {path}")
    numeric = df[["step", "amount", "oldbalanceOrg", "oldbalanceDest"]].to_numpy(dtype=float)
    if not np.isfinite(numeric).all():
        raise ValueError(f"Non-finite numeric features in {path}")

    # 2. Create a feature table
    x = pd.DataFrame(index=df.index)

    # 3. Scale transaction time
    x["step"] = (
        df["step"].astype("float32") / 743.0
    )

    # 4. Scale transaction amounts and balances
    for column in [
        "amount",
        "oldbalanceOrg",
        "oldbalanceDest",
    ]:
        x[column] = (
            np.log1p(df[column].clip(lower=0)) / 20.0
        ).astype("float32")

    # 5. Convert transaction types into numbers
    for transaction_type in TRANSACTION_TYPES:
        x[f"type_{transaction_type}"] = (
            df["type"] == transaction_type
        ).astype("float32")

    # 6. Extract features (X)
    X = x[FEATURES].to_numpy(dtype=np.float32)

    # 7. Extract correct fraud labels (y)
    y = df["isFraud"].to_numpy(dtype=np.float32)

    return X, y


def load_bank_data(data_dir, bank, *, max_samples=100000, seed=42):
    """Use identical reproducible bank subsets for local, pooled and FL runs.

    A cap of zero means all rows. Sampling is deliberately not label-stratified;
    small smoke samples are not suitable for estimating fraud performance.
    """
    from pathlib import Path
    if bank not in BANKS or max_samples < 0:
        raise ValueError("Expected bank a/b/c and a nonnegative sample cap")
    X, y = load_fl_data(Path(data_dir) / f"bank_{bank}.csv")
    if max_samples and len(y) > max_samples:
        indices = np.random.default_rng(seed).choice(len(y), max_samples, replace=False)
        X, y = X[indices], y[indices]
    return X, y
