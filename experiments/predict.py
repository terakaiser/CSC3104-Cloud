"""Score one held-out test payment with a run's final model, for live demos."""

import json
from pathlib import Path

import numpy as np

from app.data import pooled, read_manifest
from app.model import predict
from experiments.evaluate import checkpoint_weights


def predict_one(directory: Path, data: Path, kind: str | None = None, rng=None):
    """Pick a random test payment (optionally only fraud/normal) and score it.

    Uses the last saved global model and the cut-off chosen on validation data by
    `bank-fl evaluate`, so the answer matches the reported precision/recall.
    """
    evaluation = directory / "evaluation.json"
    if not evaluation.exists():
        raise ValueError(f"run 'bank-fl evaluate {directory} --data {data}' first")
    metadata = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    manifest = read_manifest(data)
    if manifest != metadata["dataset"]:
        raise ValueError("dataset does not match the run's prepared manifest")
    checkpoint = sorted(directory.glob("model-*.npz"))[-1]
    threshold = json.loads(evaluation.read_text(encoding="utf-8"))["final"]["threshold"]
    # Test payments were never used for training or for choosing the cut-off.
    x, y = pooled(data, "test", manifest["banks"])
    if kind is None:
        candidates = np.arange(len(y))
    else:
        candidates = np.flatnonzero(y == int(kind == "fraud"))
    index = int((rng or np.random.default_rng()).choice(candidates))
    score = float(predict(checkpoint_weights(checkpoint), x[index : index + 1])[0])
    return {
        "model": checkpoint.name,
        "payment": index,
        "amount": float(np.expm1(x[index, -1])),  # Undo the log1p applied in data.prepare.
        "score": score,
        "threshold": threshold,
        "predicted_fraud": score >= threshold,
        "actual_fraud": bool(y[index]),
    }
