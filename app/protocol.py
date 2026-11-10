from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from app.config import RunConfig

Weights = list[np.ndarray]


@dataclass
class Request:
    run_id: str
    attempt: int
    version: int
    bank_id: str
    request_id: str
    weights: Weights
    config: RunConfig
    pos_weight: float


@dataclass
class Reply:
    run_id: str
    attempt: int
    version: int
    bank_id: str
    request_id: str
    weights: Weights
    samples: int
    metrics: dict = field(default_factory=dict)
    error: str | None = None


def error_reply(request: Request, text: str) -> Reply:
    """A failed reply to `request`: no weights, no samples, only the reason."""
    return Reply(
        request.run_id,
        request.attempt,
        request.version,
        request.bank_id,
        request.request_id,
        [],
        0,
        error=text,
    )


def payload_bytes(weights: Weights) -> int:
    """Tensor payload only; excludes envelope, protocol, and network overhead."""
    return sum(a.nbytes for a in weights)


class Transport(Protocol):
    def online_banks(self) -> set[str]: ...
    def submit(self, request: Request) -> bool: ...
    def poll(self) -> list[Reply]: ...
    def close(self) -> None: ...
