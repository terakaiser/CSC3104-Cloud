"""Prepare an auditable benchmark, without placing raw data in the application image."""

import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

FEATURES = [f"V{i}" for i in range(1, 29)] + ["Amount"]


def write_json(path: Path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def replace_file(source: Path, target: Path, attempts=40, wait=0.05):
    """Atomically move source onto target, retrying for up to about 2 s.

    Windows refuses to replace a file while another process has it open, and the
    dashboard reads the demo's state and fault files every few seconds. A brief
    retry turns that collision into a short wait instead of a failed write.
    """
    for attempt in range(attempts):
        try:
            return source.replace(target)
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(wait)


def partition_path(root: Path, split: str, bank: str) -> Path:
    if split == "train":
        return root / bank / "train.npz"
    return root / "evaluation" / f"{split}-{bank}.npz"


def synthetic_frame(rows: int, seed: int) -> pd.DataFrame:
    """Deliberately synthetic fixture for software checks, never research evidence."""
    if rows < 1000:
        raise ValueError("use at least 1,000 synthetic rows")
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(rows, 28))
    amount = rng.lognormal(3.5, 1.4, rows)
    score = 1.6 * x[:, 0] - x[:, 1] + 0.3 * np.log1p(amount) + rng.normal(0, 0.7, rows)
    y = (score > np.quantile(score, 0.94)).astype(int)
    frame = pd.DataFrame(x, columns=FEATURES[:-1])
    frame["Amount"] = amount
    frame["Class"] = y
    return frame


def partition_indices(frame, indices, banks, rng):
    """Stratify by class; favour different amount ranks while retaining overlap."""
    allocations = [[] for _ in range(banks)]
    for label in (0, 1):
        subset = indices[frame.iloc[indices]["Class"].to_numpy() == label]
        order = subset[np.argsort(frame.iloc[subset]["Amount"].to_numpy())]
        centres = np.linspace(0, 1, banks)
        for rank, index in enumerate(order):
            position = rank / max(1, len(order) - 1)
            scores = np.exp(-(((position - centres) / 0.35) ** 2)) + 0.08
            bank = rng.choice(banks, p=scores / scores.sum())
            allocations[bank].append(index)
    return [np.array(sorted(a), dtype=np.int64) for a in allocations]


def prepare(output: Path, *, csv: Path | None = None, rows=6000, banks=3, seed=42):
    if not 2 <= banks <= 10:
        raise ValueError("banks must be between 2 and 10")
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"{output} is not empty; choose a new dataset directory")
    frame = pd.read_csv(csv) if csv else synthetic_frame(rows, seed)
    if not set(FEATURES + ["Class"]).issubset(frame.columns):
        raise ValueError("CSV must contain V1..V28, Amount, and Class")
    before = len(frame)
    frame = frame.drop_duplicates().reset_index(drop=True)
    x = frame[FEATURES].to_numpy(dtype=np.float32)
    labels = frame["Class"].to_numpy()
    if not np.isfinite(x).all() or not np.isin(labels, [0, 1]).all():
        raise ValueError("features must be finite and Class must be 0 or 1")
    if (x[:, -1] < 0).any():
        raise ValueError("Amount must be non-negative")
    x[:, -1] = np.log1p(x[:, -1])
    y = labels.astype(np.int64)
    all_indices = np.arange(len(frame))
    train, heldout = train_test_split(all_indices, test_size=0.3, stratify=y, random_state=seed)
    validation, test = train_test_split(
        heldout, test_size=0.5, stratify=y[heldout], random_state=seed
    )
    splits = {"train": train, "validation": validation, "test": test}
    rng = np.random.default_rng(seed)
    partitions = {
        name: partition_indices(frame, indices, banks, rng) for name, indices in splits.items()
    }
    # Validate all partitions before writing any files.
    for name, groups in partitions.items():
        for i, indices in enumerate(groups):
            if len(indices) == 0 or np.unique(y[indices]).size != 2:
                raise ValueError(f"{name}/bank-{i + 1} lacks both classes; use more data")
    output.mkdir(parents=True, exist_ok=True)
    checksum = (
        hashlib.sha256(csv.read_bytes()).hexdigest()
        if csv
        else hashlib.sha256(frame.to_csv(index=False).encode()).hexdigest()
    )
    manifest = {
        "schema": 1,
        "source": "ULB-compatible CSV" if csv else "SYNTHETIC SOFTWARE TEST DATA",
        "synthetic": csv is None,
        "sha256": checksum,
        "seed": seed,
        "banks": banks,
        "removed_duplicates": before - len(frame),
        "features": FEATURES,
        "transform": "V1..V28 unchanged; log1p(Amount)",
        "pos_weight": float((y[train] == 0).sum() / (y[train] == 1).sum()),
        "partitions": {},
    }
    for name, groups in partitions.items():
        manifest["partitions"][name] = {}
        for i, indices in enumerate(groups):
            bank = f"bank-{i + 1}"
            # Only train.npz is mounted into each training bank.
            path = partition_path(output, name, bank)
            path.parent.mkdir(exist_ok=True)
            np.savez_compressed(path, x=x[indices], y=y[indices], ids=indices)
            manifest["partitions"][name][bank] = {
                "samples": len(indices),
                "fraud": int(y[indices].sum()),
                "amount_mean": float(frame.iloc[indices]["Amount"].mean()),
            }
    write_json(output / "manifest.json", manifest)
    return manifest


def read_partition(path: Path):
    with np.load(path, allow_pickle=False) as data:
        return data["x"].copy(), data["y"].copy()


def read_manifest(root: Path):
    return json.loads((root / "manifest.json").read_text(encoding="utf-8"))


def pooled(root: Path, split: str, banks: int):
    paths = [partition_path(root, split, f"bank-{i + 1}") for i in range(banks)]
    parts = [read_partition(path) for path in paths]
    return np.concatenate([p[0] for p in parts]), np.concatenate([p[1] for p in parts])
