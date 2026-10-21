import time
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from app.config import RunConfig
from app.model import initial_weights
from app.protocol import Request, Transport, payload_bytes
from app.rounds import Round
from app.telemetry import RunLog


def run(config: RunConfig, manifest: dict, transport: Transport, output: Path, runtime: str):
    if manifest["banks"] != config.banks:
        raise ValueError("configured banks must match the prepared dataset")
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    logger = RunLog(output, run_id, config.to_dict(), manifest, runtime)
    weights = initial_weights(config.seed)
    logger.checkpoint(0, weights)
    counts = {k: v["samples"] for k, v in manifest["partitions"]["train"].items()}
    participation = Counter({bank: 0 for bank in config.bank_ids})
    rejected = Counter()
    version = attempt = failures = sent = received = processed = 0
    outstanding = {}  # bank -> request ID; transport owns expiry and completion.
    started = time.monotonic()
    status = "startup_timeout"
    try:
        # Require the configured Q, not every bank, so a missing bank cannot prevent startup.
        ready_until = time.monotonic() + config.startup_timeout
        while len(transport.online_banks()) < config.required:
            transport.poll()
            if time.monotonic() >= ready_until:
                logger.event("startup_failed", required=config.required)
                break
            time.sleep(config.poll_interval)
        else:
            while version < config.rounds and failures < config.max_failures:
                attempt += 1
                current = Round(run_id, attempt, version, weights, counts)
                round_start = time.monotonic()
                deadline = round_start + config.deadline
                round_sent = round_received = 0
                logger.event("attempt_started", attempt=attempt, version=version)
                committed = False
                dispatched = False
                while True:
                    # Poll every reply in the returned batch before deciding to close.
                    for reply in transport.poll():
                        if outstanding.get(reply.bank_id) == reply.request_id:
                            del outstanding[reply.bank_id]
                        size = payload_bytes(reply.weights)
                        received += size
                        round_received += size
                        processed += int(reply.metrics.get("processed_examples", 0))
                        if time.monotonic() >= deadline:
                            reason = "late_deadline"
                        else:
                            reason = current.accept(reply)
                        logger.event(
                            "reply",
                            bank=reply.bank_id,
                            attempt=reply.attempt,
                            version=reply.version,
                            request_id=reply.request_id,
                            outcome=reason,
                            error=reply.error,
                            metrics=reply.metrics,
                        )
                        if reason != "accepted":
                            rejected[reason] += 1

                    now = time.monotonic()
                    enough = len(current.accepted) >= config.required
                    all_banks = len(current.accepted) == config.banks
                    finish_early = config.mode != "timeout" or all_banks
                    if enough and (finish_early or now >= deadline):
                        weights = current.aggregate(config.required)
                        version += 1
                        failures = 0
                        for bank in current.accepted:
                            participation[bank] += 1
                        logger.checkpoint(version, weights)
                        logger.event(
                            "committed",
                            attempt=attempt,
                            version=version,
                            accepted=sorted(current.accepted),
                        )
                        committed = True
                        break
                    if now >= deadline:
                        failures += 1
                        current.closed = True
                        logger.event(
                            "deadline",
                            attempt=attempt,
                            version=version,
                            valid=len(current.accepted),
                            required=config.required,
                        )
                        break
                    # Dispatch once at the round boundary. A returning bank waits for the
                    # next attempt rather than repeatedly chasing an almost-finished quorum.
                    if not dispatched:
                        dispatched = True
                        for bank in sorted(transport.online_banks()):
                            if (
                                bank not in counts
                                or bank in outstanding
                                or bank in current.requests
                            ):
                                continue
                            request = Request(
                                run_id,
                                attempt,
                                version,
                                bank,
                                uuid.uuid4().hex,
                                weights,
                                config,
                                manifest["pos_weight"],
                            )
                            if transport.submit(request):
                                current.requests[bank] = request.request_id
                                outstanding[bank] = request.request_id
                                size = payload_bytes(weights)
                                sent += size
                                round_sent += size
                                logger.event(
                                    "dispatched",
                                    bank=bank,
                                    attempt=attempt,
                                    version=version,
                                    request_id=request.request_id,
                                )
                    time.sleep(min(config.poll_interval, max(0, deadline - time.monotonic())))
                logger.round(
                    attempt=attempt,
                    version=version,
                    status="committed" if committed else "deadline",
                    seconds=time.monotonic() - round_start,
                    elapsed_seconds=time.monotonic() - started,
                    accepted=";".join(sorted(current.accepted)),
                    samples=sum(r.samples for r in current.accepted.values()) if committed else 0,
                    tensor_bytes_sent=round_sent,
                    tensor_bytes_received=round_received,
                )
            status = "completed" if version == config.rounds else "insufficient_quorum"
        training_seconds = time.monotonic() - started
        # Drain already-dispatched work so stale rejection and processed-example counts are visible.
        drain_until = time.monotonic() + config.work_timeout + 5
        while outstanding and time.monotonic() < drain_until:
            for reply in transport.poll():
                if outstanding.get(reply.bank_id) == reply.request_id:
                    del outstanding[reply.bank_id]
                received += payload_bytes(reply.weights)
                processed += int(reply.metrics.get("processed_examples", 0))
                rejected["closed"] += 1
                logger.event(
                    "reply",
                    bank=reply.bank_id,
                    attempt=reply.attempt,
                    version=reply.version,
                    outcome="closed",
                    error=reply.error,
                    metrics=reply.metrics,
                )
            time.sleep(config.poll_interval)
        summary = {
            "status": status,
            "committed_rounds": version,
            "attempts": attempt,
            "successful_round_rate": version / attempt if attempt else 0.0,
            "training_seconds": training_seconds,
            "total_seconds_including_drain": time.monotonic() - started,
            "participation": dict(participation),
            "rejections": dict(rejected),
            "tensor_bytes_sent": sent,
            "tensor_bytes_received": received,
            "processed_examples_returned": processed,
            "unresolved_requests": len(outstanding),
            "synthetic_data": manifest["synthetic"],
        }
        logger.finish(summary)
        return logger.directory
    except BaseException as exc:
        logger.event("aborted", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        transport.close()
        logger.close()
