import time
import uuid
from pathlib import Path

from app.config import RunConfig
from app.data import pooled, read_manifest
from app.model import initial_weights, train
from app.telemetry import ResourceSample, RunLog


def run_centralized(config: RunConfig, data: Path, output: Path):
    manifest = read_manifest(data)
    if config.banks != manifest["banks"]:
        raise ValueError("bank count must match prepared data")
    x, y = pooled(data, "train", config.banks)
    logger = RunLog(
        output,
        "centralized-" + uuid.uuid4().hex[:10],
        {**config.to_dict(), "mode": "centralized"},
        manifest,
        "centralized",
    )
    weights = initial_weights(config.seed)
    logger.checkpoint(0, weights)
    started = time.monotonic()
    try:
        with ResourceSample() as resources:
            for version in range(1, config.rounds + 1):
                before = time.monotonic()
                weights, loss = train(
                    weights,
                    x,
                    y,
                    epochs=config.epochs,
                    batch_size=config.batch_size,
                    learning_rate=config.learning_rate,
                    pos_weight=manifest["pos_weight"],
                    seed=config.seed + version,
                    expires=float("inf"),
                )
                logger.checkpoint(version, weights)
                logger.round(
                    attempt=version,
                    version=version,
                    status="committed",
                    seconds=time.monotonic() - before,
                    elapsed_seconds=time.monotonic() - started,
                    accepted="pooled",
                    samples=len(x),
                    tensor_bytes_sent=0,
                    tensor_bytes_received=0,
                )
                logger.event("committed", version=version, loss=loss)
        logger.finish(
            {
                "status": "completed",
                "committed_rounds": config.rounds,
                "attempts": config.rounds,
                "successful_round_rate": 1.0,
                "training_seconds": time.monotonic() - started,
                "processed_examples_returned": len(x) * config.rounds * config.epochs,
                "tensor_bytes_sent": 0,
                "tensor_bytes_received": 0,
                "synthetic_data": manifest["synthetic"],
                "resources": resources.metrics,
            }
        )
        return logger.directory
    finally:
        logger.close()
