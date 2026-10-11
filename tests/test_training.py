from copy import deepcopy
import json
from pathlib import Path
import tomllib

import numpy as np
import pandas as pd
import pytest
import torch
from flwr.common import Context, RecordDict, ArrayRecord, ConfigRecord, Message

from crossbank.data.fl_preprocessing import load_bank_data, load_fl_data
from crossbank.data.smoke import create_smoke_data
from crossbank.experiments import load_checkpoint, save_checkpoint
from crossbank.fl.client_app import train
from crossbank.fl.server_app import main, SynchronousFedAvg
from crossbank.models.metrics import select_threshold
from crossbank.models.mlp import FraudMLP
from crossbank.models.training import seed_everything, train_model, scores


@pytest.fixture
def data_dir(tmp_path):
    directory = tmp_path / "data"
    create_smoke_data(directory, rows=40)
    return directory


def test_shared_sampling_and_feature_contract(data_dir):
    X, y = load_bank_data(data_dir, "a", max_samples=25, seed=7)
    X2, y2 = load_bank_data(data_dir, "a", max_samples=25, seed=7)
    np.testing.assert_array_equal(X, X2)
    np.testing.assert_array_equal(y, y2)
    assert X.shape == (25, 9) and X.dtype == np.float32
    assert (X[:, 4:].sum(axis=1) == 1).all()
    assert len(load_bank_data(data_dir, "a", max_samples=0)[1]) == 40


def test_preprocessing_rejects_bad_input(data_dir):
    path = data_dir / "bank_a.csv"
    df = pd.read_csv(path)
    df.loc[0, "type"] = "UNKNOWN"
    df.to_csv(path, index=False)
    with pytest.raises(ValueError, match="transaction type"):
        load_fl_data(path)


def test_training_reproducible_and_changes_weights(data_dir):
    X, y = load_bank_data(data_dir, "a")
    seed_everything(1)
    model = FraudMLP()
    twin, before = deepcopy(model), deepcopy(model.state_dict())
    losses = train_model(model, X, y, epochs=2, batch_size=16, seed=11)
    assert losses == train_model(twin, X, y, epochs=2, batch_size=16, seed=11)
    assert any(not torch.equal(before[key], value) for key, value in model.state_dict().items())
    np.testing.assert_array_equal(scores(model, X, batch_size=16), scores(twin, X, batch_size=16))


@pytest.mark.parametrize("label", [0, 1])
def test_single_class_training_is_finite(data_dir, label):
    X, y = load_bank_data(data_dir, "a")
    assert np.isfinite(train_model(FraudMLP(), X, np.full_like(y, label))).all()


@pytest.mark.parametrize("options", [{"epochs": 0}, {"batch_size": 0}, {"learning_rate": 0}])
def test_invalid_training_options(data_dir, options):
    X, y = load_bank_data(data_dir, "a")
    with pytest.raises(ValueError):
        train_model(FraudMLP(), X, y, **options)


def test_checkpoint_round_trip_and_threshold(data_dir, tmp_path):
    X, y = load_fl_data(data_dir / "validation.csv")
    model = FraudMLP()
    probabilities = scores(model, X)
    threshold = select_threshold(y, probabilities)
    path = tmp_path / "model.pt"
    save_checkpoint(path, model, threshold=threshold, config={"seed": 42}, round_number=2)
    loaded, checkpoint = load_checkpoint(path)
    np.testing.assert_array_equal(scores(loaded, X), probabilities)
    assert checkpoint["threshold"] == threshold and checkpoint["round"] == 2
    assert select_threshold([0, 0, 1, 1], [0.1, 0.2, 0.7, 0.9]) == 0.7
    with pytest.raises(ValueError, match="both classes"):
        select_threshold([0, 0], [0.1, 0.2])


class LocalGrid:
    """Exercise actual Flower messages/handlers without Ray or network processes."""
    def __init__(self, config, drop_client=False):
        self.config = config
        self.drop_client = drop_client

    def get_node_ids(self):
        return [1, 2, 3]

    def send_and_receive(self, messages, timeout):
        for message in messages:
            node = message.metadata.dst_node_id
            if self.drop_client and node == 3:
                continue
            context = Context(run_id=1, node_id=node, node_config={"partition-id": node - 1},
                              state=RecordDict(), run_config=self.config)
            yield train(message, context)


def run_server(data_dir, output, drop_client=False):
    project = Path(__file__).resolve().parents[1] / "pyproject.toml"
    config = tomllib.loads(project.read_text())["tool"]["flwr"]["app"]["config"]
    config.update({"data-dir": str(data_dir), "output-dir": str(output), "batch-size": 16})
    context = Context(run_id=1, node_id=0, node_config={}, state=RecordDict(), run_config=config)
    main(LocalGrid(config, drop_client), context)


def test_flower_two_rounds_and_validation_only(data_dir, tmp_path):
    # Training must not depend on the final test set.
    (data_dir / "test.csv").unlink()
    output = tmp_path / "runs"
    run_server(data_dir, output)
    run = next(output.iterdir())
    assert json.loads((run / "training_status.json").read_text())["completed_rounds"] == 2
    history = json.loads((run / "validation_results.json").read_text())
    assert [row["training_round"] for row in history] == [0, 1, 2]
    assert history[1]["banks_responded"] == history[2]["banks_responded"] == 3
    assert "average_precision" in history[-1] and "fraud_detected" in history[-1]
    assert "pr_auc" not in history[-1] and "tp" not in history[-1]
    assert "Fraud recall (fraud caught)" in (run / "results_summary.txt").read_text()
    assert (run / "untrained_model.pt").is_file()
    assert (run / "model_after_round_002.pt").is_file()
    model, checkpoint = load_checkpoint(run / "final_model.pt")
    assert checkpoint["round"] == 2
    assert np.isfinite(scores(model, load_fl_data(data_dir / "validation.csv")[0])).all()


def test_synchronous_baseline_fails_without_three_replies(data_dir, tmp_path):
    output = tmp_path / "runs"
    with pytest.raises(RuntimeError, match="all three banks"):
        run_server(data_dir, output, drop_client=True)
    run = next(output.iterdir())
    assert json.loads((run / "training_status.json").read_text())["status"] == "failed"
    assert not (run / "final_model.pt").exists()


def test_client_uses_message_config_and_only_its_bank(data_dir):
    (data_dir / "bank_b.csv").unlink()
    (data_dir / "bank_c.csv").unlink()
    config = {"seed": 42, "data-dir": str(data_dir), "max-samples": 20,
              "local-epochs": 1, "batch-size": 16, "learning-rate": 0.001, "server-round": 1}
    request = Message(content=RecordDict({"arrays": ArrayRecord(FraudMLP().state_dict()),
                                         "config": ConfigRecord(config)}),
                      dst_node_id=1, message_type="train")
    context = Context(run_id=1, node_id=1, node_config={"partition-id": 0}, state=RecordDict(),
                      run_config={"local-epochs": 0, "learning-rate": 0.0})
    reply = train(request, context)
    assert reply.content["metrics"]["num-examples"] == 20
    assert set(reply.content) == {"arrays", "metrics"}


def test_synchronous_baseline_rejects_duplicate_client_replies():
    strategy = SynchronousFedAvg()
    strategy.expected_nodes = {1, 2, 3}
    request = Message(content=RecordDict(), dst_node_id=1, message_type="train")
    reply = Message(content=RecordDict(), reply_to=request)
    with pytest.raises(RuntimeError, match="all three banks"):
        strategy.aggregate_train(1, [reply, reply, reply])
