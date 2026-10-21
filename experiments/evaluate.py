import json
from pathlib import Path

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)

from app.data import pooled, read_manifest, read_partition, write_json
from app.model import predict


def metrics(y, probabilities, threshold):
    predictions = probabilities >= threshold
    tn, fp, fn, tp = confusion_matrix(y, predictions, labels=[0, 1]).ravel()
    return {
        "precision": float(precision_score(y, predictions, zero_division=0)),
        "recall": float(recall_score(y, predictions, zero_division=0)),
        "f1": float(f1_score(y, predictions, zero_division=0)),
        "pr_auc_average_precision": float(average_precision_score(y, probabilities)),
        "roc_auc": float(roc_auc_score(y, probabilities)),
        "false_positive_rate": float(fp / (fp + tn)),
        "tn": int(tn),
        "fp": int(fp),
        "fn": int(fn),
        "tp": int(tp),
    }


def checkpoint_weights(path):
    with np.load(path, allow_pickle=False) as arrays:
        return [arrays[f"arr_{i}"] for i in range(len(arrays.files))]


def evaluate(directory: Path, data: Path):
    metadata = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    manifest = read_manifest(data)
    if manifest != metadata["dataset"]:
        raise ValueError("evaluation dataset does not match the run's prepared manifest")
    banks = manifest["banks"]
    vx, vy = pooled(data, "validation", banks)
    tx, ty = pooled(data, "test", banks)
    checkpoints = sorted(directory.glob("model-*.npz"))
    if not checkpoints:
        raise ValueError("no checkpoints found")
    curves = []
    # Test metrics are computed only in this explicit offline evaluation command.
    for checkpoint in checkpoints:
        weights = checkpoint_weights(checkpoint)
        precision, recall, thresholds = precision_recall_curve(vy, predict(weights, vx))
        f1 = 2 * precision[:-1] * recall[:-1] / np.maximum(precision[:-1] + recall[:-1], 1e-12)
        threshold = float(thresholds[int(np.argmax(f1))])
        curves.append(
            {
                "version": int(checkpoint.stem.split("-")[-1]),
                "threshold": threshold,
                **metrics(ty, predict(weights, tx), threshold),
            }
        )
    final_weights = checkpoint_weights(checkpoints[-1])
    threshold = curves[-1]["threshold"]
    per_bank = {}
    for i in range(banks):
        bank = f"bank-{i + 1}"
        x, y = read_partition(data / "evaluation" / f"test-{bank}.npz")
        per_bank[bank] = metrics(y, predict(final_weights, x), threshold)
    result = {
        "synthetic_data": manifest["synthetic"],
        "threshold_rule": "maximum validation F1 for each checkpoint; no test tuning",
        "pr_auc_definition": "sklearn average_precision_score (non-interpolated AP)",
        "curve": curves,
        "final": curves[-1],
        "per_bank": per_bank,
    }
    write_json(directory / "evaluation.json", result)
    return result
