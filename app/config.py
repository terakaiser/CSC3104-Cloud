import math
from dataclasses import asdict, dataclass
from typing import Literal


@dataclass(frozen=True)
class RunConfig:
    mode: Literal["resilient", "synchronous", "timeout"] = "resilient"
    banks: int = 3
    quorum: int = 2
    rounds: int = 20
    deadline: float = 30.0
    # Resilient mode: after the quorum arrives, wait up to this long for the other
    # dispatched banks before closing the round (0 closes on the first quorum).
    grace: float = 3.0
    seed: int = 42
    epochs: int = 1
    batch_size: int = 256
    learning_rate: float = 0.01
    mu: float = 0.0  # FedProx proximal strength; 0 is plain FedAvg
    max_failures: int = 3
    startup_timeout: float = 90.0
    poll_interval: float = 0.05
    scenario: str = "healthy"
    slow_bank: str = "bank-3"
    delay: float = 0.0
    fault_attempt: int = 2
    label: str = "run"

    def __post_init__(self):
        if self.mode not in {"resilient", "synchronous", "timeout"}:
            raise ValueError("mode must be resilient, synchronous, or timeout")
        for key in (
            "banks",
            "quorum",
            "rounds",
            "epochs",
            "batch_size",
            "max_failures",
            "fault_attempt",
            "seed",
        ):
            if type(getattr(self, key)) is not int:
                raise ValueError(f"{key} must be an integer")
        if not 2 <= self.banks <= 10:
            raise ValueError("banks must be between 2 and 10")
        if not 1 <= self.quorum <= self.banks:
            raise ValueError("quorum must be between 1 and banks")
        for key in ("rounds", "epochs", "batch_size", "max_failures", "fault_attempt"):
            if getattr(self, key) < 1:
                raise ValueError(f"{key} must be positive")
        for key in ("deadline", "startup_timeout", "poll_interval", "learning_rate"):
            if not math.isfinite(getattr(self, key)) or getattr(self, key) <= 0:
                raise ValueError(f"{key} must be finite and positive")
        for key in ("delay", "mu", "grace"):
            if getattr(self, key) < 0 or not math.isfinite(getattr(self, key)):
                raise ValueError(f"{key} must be finite and non-negative")
        if self.scenario not in {"healthy", "slow", "stale", "unavailable"}:
            raise ValueError("unknown training scenario")
        if self.scenario != "healthy" and self.slow_bank not in self.bank_ids:
            raise ValueError("selected fault bank must be a configured bank")

    @property
    def bank_ids(self):
        return tuple(f"bank-{i + 1}" for i in range(self.banks))

    @property
    def required(self):
        return self.banks if self.mode == "synchronous" else self.quorum

    @property
    def work_timeout(self):
        # Leave time to observe a late reply, while bounding work and message lifetimes.
        return max(10.0, self.deadline * 3, self.delay + self.deadline)

    def to_dict(self):
        return asdict(self)
