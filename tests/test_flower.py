import json
from types import SimpleNamespace

import numpy as np
import pytest

from app.config import RunConfig
from app.flower_transport import (
    FlowerTransport,
    decode_reply,
    decode_request,
    reply_content,
    request_content,
)
from app.protocol import Reply, Request
from app.rounds import Round


def test_flower_records_preserve_protocol_and_arrays():
    weights = [np.ones((16, 29), dtype=np.float32), np.zeros(16, dtype=np.float32)]
    request = Request("run", 7, 3, "bank-1", "request", weights, RunConfig(), 10.0)
    decoded = decode_request(request_content(request))
    assert decoded.run_id == "run"
    assert decoded.attempt == 7
    assert decoded.config == request.config
    for expected, actual in zip(weights, decoded.weights, strict=True):
        np.testing.assert_array_equal(expected, actual)
    reply = Reply("run", 7, 3, "bank-1", "request", weights, 123, {"loss": 0.1})
    restored = decode_reply(reply_content(reply))
    assert restored.samples == 123
    assert restored.metrics == {"loss": 0.1}


@pytest.mark.parametrize(
    "metrics",
    [
        {"processed_examples": float("nan")},
        {"processed_examples": "many"},
        {"processed_examples": None},
        {"processed_examples": -1},
        {"loss": float("inf")},
        {"nested": [1.0, float("nan")]},
        [1, 2],
    ],
)
def test_malformed_reply_metrics_become_a_rejected_client_error(metrics):
    # One bank's bad metrics must not abort the coordinator for every bank.
    reply = Reply("run", 1, 0, "bank-1", "request", [], 10)
    content = reply_content(reply)
    content["result"]["metrics"] = json.dumps(metrics)
    with pytest.raises(ValueError):
        decode_reply(content)

    class Grid:
        def get_node_ids(self):
            return [5]

        def push_messages(self, messages):
            return ["message"]

        def pull_messages(self, ids):
            return [
                SimpleNamespace(
                    metadata=SimpleNamespace(reply_to_message_id="message", src_node_id=5),
                    has_error=lambda: False,
                    content=content,
                )
            ]

    transport = FlowerTransport(Grid(), ["bank-1"])
    transport.nodes = {"bank-1": 5}
    transport.last_discovery = float("inf")  # Skip identity discovery in this test.
    request = Request("run", 1, 0, "bank-1", "request", [], RunConfig(), 1.0)
    assert transport.submit(request)
    (decoded,) = transport.poll()
    assert decoded.error.startswith("malformed reply")
    assert Round("run", 1, 0, [], {"bank-1": 10}, {"bank-1": "request"}).accept(decoded) == (
        "client_error"
    )


def test_flower_entrypoints_are_loadable():
    from flwr.clientapp import ClientApp
    from flwr.serverapp import ServerApp

    from app.client import app as client
    from app.server import app as server

    assert isinstance(client, ClientApp)
    assert isinstance(server, ServerApp)


def test_flower_app_config_accepts_every_run_setting():
    from pathlib import Path

    from flwr.common.config import get_fused_config_from_dir

    # Mirrors experiments/flower_local.py; Flower rejects keys missing from pyproject.toml.
    values = {k.replace("_", "-"): v for k, v in RunConfig().to_dict().items()}
    values.pop("poll-interval")
    get_fused_config_from_dir(Path(__file__).parents[1], values)
