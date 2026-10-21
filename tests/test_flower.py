import numpy as np

from app.config import RunConfig
from app.flower_transport import decode_reply, decode_request, reply_content, request_content
from app.protocol import Reply, Request


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


def test_flower_entrypoints_are_loadable():
    from flwr.clientapp import ClientApp
    from flwr.serverapp import ServerApp

    from app.client import app as client
    from app.server import app as server

    assert isinstance(client, ClientApp)
    assert isinstance(server, ServerApp)
