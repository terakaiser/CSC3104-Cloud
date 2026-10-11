"""Shared validation, checkpoint format, and experiment output management."""
from importlib.metadata import version
import json
from pathlib import Path
import platform

import torch

from crossbank.data.fl_preprocessing import FEATURES, PREPROCESSING_VERSION
from crossbank.models.metrics import evaluate, select_threshold
from crossbank.models.mlp import FraudMLP
from crossbank.models.training import scores
from crossbank.reporting import create_run_directory


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def create_run(output_dir, name, config):
    reserved = config.get("run-directory")
    directory = Path(reserved) if reserved else create_run_directory(output_dir, name)
    if reserved and (not directory.is_dir() or (directory / "run_settings.json").exists()):
        raise ValueError("Reserved run directory must exist and must not contain a previous run")
    data_dir = Path(config.get("data-dir", config.get("data_dir", "data/processed")))
    write_json(directory / "run_settings.json", {
        "experiment": name, "config": config, "preprocessing": PREPROCESSING_VERSION,
        "features": FEATURES, "python": platform.python_version(), "platform": platform.platform(),
        "packages": {name: version(name) for name in ("torch", "numpy", "pandas", "scikit-learn", "flwr")},
        "evaluation_split": "validation", "test_evaluated": False,
        "dataset_kind": "synthetic-smoke" if (data_dir / "SYNTHETIC_SMOKE_ONLY.txt").exists() else "user-provided-paysim",
    })
    return directory


def validation_metrics(model, X, y):
    probabilities = scores(model, X)
    threshold = select_threshold(y, probabilities)
    return {"threshold": threshold, **evaluate(y, probabilities, threshold)}


def save_checkpoint(path, model, *, threshold, config, round_number):
    """Save weights and inference metadata atomically; this is not a resume controller."""
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    torch.save({
        "format_version": 1, "model_state": model.state_dict(),
        "features": FEATURES, "preprocessing": PREPROCESSING_VERSION,
        "threshold": float(threshold), "round": int(round_number), "config": config,
    }, temporary)
    temporary.replace(path)


def load_checkpoint(path):
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    if (checkpoint.get("format_version") != 1 or checkpoint.get("features") != FEATURES
            or checkpoint.get("preprocessing") != PREPROCESSING_VERSION):
        raise ValueError("Unsupported checkpoint/preprocessing; old bank-scaled models are incompatible")
    model = FraudMLP(input_size=len(FEATURES))
    model.load_state_dict(checkpoint["model_state"])
    return model, checkpoint
