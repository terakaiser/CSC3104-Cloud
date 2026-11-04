import pytest

from app.config import RunConfig


@pytest.mark.parametrize(
    "change",
    [
        {"quorum": 0},
        {"quorum": 4},
        {"deadline": float("nan")},
        {"poll_interval": 0},
        {"rounds": 0},
        {"banks": 3.5},
        {"rounds": True},
        {"scenario": "slow", "slow_bank": "bank-99"},
        {"learning_rate": -1},
        {"mu": -0.1},
        {"mu": float("inf")},
    ],
)
def test_invalid_config_fails_before_launch(change):
    with pytest.raises(ValueError):
        RunConfig(**change)
