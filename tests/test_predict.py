import json

import numpy as np
import pytest

from app.data import prepare, write_json
from app.model import initial_weights
from experiments.predict import predict_one


@pytest.fixture
def run(tmp_path):
    data = tmp_path / "data"
    manifest = prepare(data, rows=6000)
    directory = tmp_path / "run"
    directory.mkdir()
    write_json(directory / "run.json", {"dataset": manifest})
    np.savez(directory / "model-000.npz", *initial_weights(42))
    np.savez(directory / "model-001.npz", *initial_weights(7))
    write_json(directory / "evaluation.json", {"final": {"threshold": 0.5}})
    return directory, data


@pytest.mark.parametrize("kind", ["fraud", "normal"])
def test_predict_scores_requested_kind_with_final_model(run, kind):
    directory, data = run
    result = predict_one(directory, data, kind, np.random.default_rng(0))
    assert result["actual_fraud"] is (kind == "fraud")
    assert result["model"] == "model-001.npz"
    assert 0 <= result["score"] <= 1
    assert result["predicted_fraud"] is (result["score"] >= 0.5)


def test_predict_requires_evaluation_first(run):
    directory, data = run
    (directory / "evaluation.json").unlink()
    with pytest.raises(ValueError, match="evaluate"):
        predict_one(directory, data)


def test_predict_rejects_a_different_dataset(run, tmp_path):
    directory, data = run
    other = json.loads((data / "manifest.json").read_text())
    other["seed"] = 1
    write_json(directory / "run.json", {"dataset": other})
    with pytest.raises(ValueError, match="does not match"):
        predict_one(directory, data)
