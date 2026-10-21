import time
from pathlib import Path

from app.data import read_partition
from app.model import train
from app.protocol import Reply, Request
from app.telemetry import ResourceSample


def execute(request: Request, data_path: Path) -> Reply:
    config = request.config
    expires = time.monotonic() + config.work_timeout
    metadata = dict(
        run_id=request.run_id,
        attempt=request.attempt,
        version=request.version,
        bank_id=request.bank_id,
        request_id=request.request_id,
    )
    try:
        with ResourceSample() as resources:
            if (
                config.scenario == "slow"
                and request.bank_id == config.slow_bank
                and request.attempt == config.fault_attempt
            ):
                time.sleep(min(config.delay, config.work_timeout))
            x, y = read_partition(data_path)
            weights, loss = train(
                request.weights,
                x,
                y,
                epochs=config.epochs,
                batch_size=config.batch_size,
                learning_rate=config.learning_rate,
                pos_weight=request.pos_weight,
                seed=config.seed + request.attempt * 100 + int(request.bank_id.split("-")[-1]),
                expires=expires,
            )
        if (
            config.scenario == "stale"
            and request.bank_id == config.slow_bank
            and request.attempt == config.fault_attempt
        ):
            metadata["version"] -= 1
        return Reply(
            **metadata,
            weights=weights,
            samples=len(x),
            metrics={
                **resources.metrics,
                "loss": loss,
                "processed_examples": len(x) * config.epochs,
            },
        )
    except (ValueError, OSError, TimeoutError) as exc:
        return Reply(**metadata, weights=[], samples=0, error=str(exc))
