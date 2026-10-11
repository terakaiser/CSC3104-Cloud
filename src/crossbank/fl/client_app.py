"""Flower bank training handler; raw rows stay in the selected client dataset."""
from pathlib import Path
from time import perf_counter

from flwr.clientapp import ClientApp
from flwr.common import ArrayRecord, MetricRecord, RecordDict, Message, Context

from crossbank.data.fl_preprocessing import BANKS, load_bank_data
from crossbank.models.mlp import FraudMLP
from crossbank.models.training import train_model

app = ClientApp()


@app.train()
def train(msg: Message, context: Context) -> Message:
    partition_id = int(context.node_config["partition-id"])
    if not 0 <= partition_id < len(BANKS):
        raise ValueError("This baseline requires exactly three bank partitions (0, 1, 2)")
    bank = BANKS[partition_id]
    # Per-round settings are authoritative, including learning-rate schedules.
    config = {**context.run_config, **dict(msg.content["config"])}
    seed = int(config["seed"])
    X, y = load_bank_data(Path(str(config["data-dir"])), bank,
                         max_samples=int(config["max-samples"]), seed=seed)
    model = FraudMLP()
    model.load_state_dict(msg.content["arrays"].to_torch_state_dict())
    started = perf_counter()
    losses = train_model(
        model, X, y, epochs=int(config["local-epochs"]),
        batch_size=int(config["batch-size"]), learning_rate=float(config["learning-rate"]),
        seed=seed + 1000 * int(config["server-round"]) + partition_id,
    )
    return Message(
        content=RecordDict({
            "arrays": ArrayRecord(model.state_dict()),
            "metrics": MetricRecord({
                "train_loss": losses[-1], "num-examples": len(y),
                "train_seconds": perf_counter() - started,
            }),
        }),
        reply_to=msg,
    )
