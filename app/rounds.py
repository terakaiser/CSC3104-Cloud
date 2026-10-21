"""Pure round validation and aggregation, independent of the transport."""

from dataclasses import dataclass, field

import numpy as np

from app.protocol import Reply, Weights


@dataclass
class Round:
    run_id: str
    attempt: int
    version: int
    weights: Weights
    expected_counts: dict[str, int]
    requests: dict[str, str] = field(default_factory=dict)
    accepted: dict[str, Reply] = field(default_factory=dict)
    closed: bool = False

    def accept(self, reply: Reply) -> str:
        if self.closed:
            return "closed"
        if reply.run_id != self.run_id:
            return "wrong_run"
        if reply.attempt != self.attempt or reply.version != self.version:
            return "stale"
        if reply.bank_id not in self.requests:
            return "unknown_bank"
        if reply.request_id != self.requests[reply.bank_id]:
            return "wrong_request"
        if reply.bank_id in self.accepted:
            return "duplicate"
        if reply.error:
            return "client_error"
        if type(reply.samples) is not int or reply.samples != self.expected_counts[reply.bank_id]:
            return "invalid_samples"
        if reply.samples <= 0 or len(reply.weights) != len(self.weights):
            return "invalid_model"
        for actual, expected in zip(reply.weights, self.weights, strict=True):
            if (
                not isinstance(actual, np.ndarray)
                or actual.shape != expected.shape
                or actual.dtype != expected.dtype
                or not np.isfinite(actual).all()
            ):
                return "invalid_model"
        self.accepted[reply.bank_id] = reply
        return "accepted"

    def aggregate(self, required: int) -> Weights:
        if self.closed:
            raise ValueError("round already closed")
        if len(self.accepted) < required:
            raise ValueError("insufficient quorum")
        total = sum(r.samples for r in self.accepted.values())
        averaged = []
        for i, reference in enumerate(self.weights):
            # Accumulate in float64, then retain the model's original dtype.
            value = sum(
                r.weights[i].astype(np.float64) * (r.samples / total)
                for r in self.accepted.values()
            )
            value = value.astype(reference.dtype)
            if not np.isfinite(value).all():
                raise ValueError("non-finite aggregate")
            averaged.append(value)
        self.closed = True
        return averaged
