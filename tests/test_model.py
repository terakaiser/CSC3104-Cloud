import time

import numpy as np

from app.model import initial_weights, train


def _train(weights, **extra):
    rng = np.random.default_rng(0)
    x = rng.normal(size=(512, 29)).astype(np.float32)
    y = (rng.random(512) < 0.1).astype(np.int64)
    settings = dict(epochs=3, batch_size=64, learning_rate=0.1, pos_weight=5.0, seed=1)
    return train(weights, x, y, expires=time.monotonic() + 60, **settings, **extra)[0]


def _distance(a, b):
    return sum(float(np.sum((p - q) ** 2)) for p, q in zip(a, b, strict=True))


def test_fedprox_mu_zero_is_fedavg_and_mu_pulls_toward_global():
    start = initial_weights(42)
    fedavg = _train(start)
    assert all(np.array_equal(p, q) for p, q in zip(_train(start, mu=0.0), fedavg, strict=True))
    assert _distance(_train(start, mu=1.0), start) < _distance(fedavg, start)
