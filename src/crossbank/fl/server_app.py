"""Three-client synchronous baseline with validation and per-round artifacts."""
from pathlib import Path
from time import perf_counter

from flwr.server import ServerApp
from flwr.serverapp import Grid
from flwr.common import Context, ArrayRecord, ConfigRecord, MetricRecord
from flwr.serverapp.strategy import FedAvg

from crossbank.data.fl_preprocessing import load_fl_data
from crossbank.experiments import create_run, save_checkpoint, validation_metrics, write_json
from crossbank.models.mlp import FraudMLP
from crossbank.models.training import seed_everything
from crossbank.reporting import readable_metrics, save_summary

app = ServerApp()


class SynchronousFedAvg(FedAvg):
    """Require all selected banks; this baseline intentionally aborts on failure."""

    def __init__(self):
        super().__init__(fraction_train=1.0, fraction_evaluate=0.0,
                         min_train_nodes=3, min_available_nodes=3,
                         weighted_by_key="num-examples")
        self.expected_nodes = set()
        self.round_training = {}
        self.started = None

    def configure_train(self, server_round, arrays, config, grid):
        self.started = perf_counter()
        messages = list(super().configure_train(server_round, arrays, config, grid))
        self.expected_nodes = {message.metadata.dst_node_id for message in messages}
        if len(messages) != 3 or len(self.expected_nodes) != 3:
            raise RuntimeError("Synchronous baseline requires exactly three distinct bank nodes")
        return messages

    def aggregate_train(self, server_round, replies):
        replies = list(replies)
        received = {message.metadata.src_node_id for message in replies}
        if (len(replies) != 3 or received != self.expected_nodes
                or any(message.has_error() for message in replies)):
            raise RuntimeError(f"Round {server_round}: expected successful replies from all three banks")
        arrays, metrics = super().aggregate_train(server_round, replies)
        if arrays is None or metrics is None:
            raise RuntimeError(f"Round {server_round}: aggregation produced no model")
        self.round_training[server_round] = {
            "round_training_seconds": perf_counter() - self.started,
            "training_rows": sum(int(message.content["metrics"]["num-examples"]) for message in replies),
            "clients": len(replies), **dict(metrics),
        }
        return arrays, metrics


@app.main()
def main(grid: Grid, context: Context):
    config = dict(context.run_config)
    rounds = int(config["num-server-rounds"])
    timeout = float(config["round-timeout"])
    if rounds < 1 or timeout <= 0:
        raise ValueError("Round count and timeout must be positive")
    seed_everything(int(config["seed"]))
    model = FraudMLP()
    X_val, y_val = load_fl_data(Path(str(config["data-dir"])) / "validation.csv")
    directory = create_run(str(config["output-dir"]), "three_bank_federated", config)
    write_json(directory / "training_status.json", {"status": "running", "completed_rounds": 0})
    print("Evaluation runs on the server's validation data; bank-side evaluation is intentionally disabled.", flush=True)
    strategy = SynchronousFedAvg()
    history = []
    started = perf_counter()

    def evaluate_global(round_number, arrays):
        model.load_state_dict(arrays.to_torch_state_dict())
        metrics = validation_metrics(model, X_val, y_val)
        row = {"round": round_number, "elapsed_seconds": perf_counter() - started,
               **strategy.round_training.get(round_number, {}), **metrics}
        history.append(row)
        write_json(directory / "validation_results.json", [readable_metrics(row) for row in history])
        model_filename = "untrained_model.pt" if round_number == 0 else f"model_after_round_{round_number:03d}.pt"
        save_checkpoint(directory / model_filename, model,
                        threshold=metrics["threshold"], config=config, round_number=round_number)
        write_json(directory / "training_status.json", {"status": "running", "completed_rounds": round_number})
        save_summary(directory, metrics, title="Before training - validation results" if round_number == 0 else f"Round {round_number} - validation results")
        return MetricRecord({key: value for key, value in readable_metrics(metrics).items() if value is not None})

    try:
        result = strategy.start(
            grid=grid, initial_arrays=ArrayRecord(model.state_dict()),
            train_config=ConfigRecord(config), num_rounds=rounds, timeout=timeout,
            evaluate_fn=evaluate_global,
        )
        model.load_state_dict(result.arrays.to_torch_state_dict())
        save_checkpoint(directory / "final_model.pt", model,
                        threshold=history[-1]["threshold"], config=config, round_number=rounds)
        write_json(directory / "training_status.json", {
            "status": "completed", "completed_rounds": rounds,
            "total_seconds": perf_counter() - started,
        })
    except Exception as exc:
        write_json(directory / "training_status.json", {
            "status": "failed", "completed_rounds": max(0, len(history) - 1), "error": str(exc),
        })
        raise
    print(f"Flower artifacts saved to {directory.resolve()}")
