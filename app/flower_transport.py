"""Flower 1.22 Message API adapter. No legacy NumPyClient/server API is mixed in."""

import json
import time

from flwr.common import ArrayRecord, ConfigRecord, Message, RecordDict

from app.config import RunConfig
from app.protocol import Reply, Request


def request_content(request: Request):
    return RecordDict(
        {
            "weights": ArrayRecord(numpy_ndarrays=request.weights),
            "task": ConfigRecord(
                {
                    "run_id": request.run_id,
                    "attempt": request.attempt,
                    "version": request.version,
                    "bank_id": request.bank_id,
                    "request_id": request.request_id,
                    "config": json.dumps(request.config.to_dict()),
                    "pos_weight": request.pos_weight,
                }
            ),
        }
    )


def decode_request(content):
    task = content["task"]
    return Request(
        str(task["run_id"]),
        int(task["attempt"]),
        int(task["version"]),
        str(task["bank_id"]),
        str(task["request_id"]),
        content["weights"].to_numpy_ndarrays(),
        RunConfig(**json.loads(str(task["config"]))),
        float(task["pos_weight"]),
    )


def reply_content(reply: Reply):
    return RecordDict(
        {
            "weights": ArrayRecord(numpy_ndarrays=reply.weights),
            "result": ConfigRecord(
                {
                    "run_id": reply.run_id,
                    "attempt": reply.attempt,
                    "version": reply.version,
                    "bank_id": reply.bank_id,
                    "request_id": reply.request_id,
                    "samples": reply.samples,
                    "metrics": json.dumps(reply.metrics),
                    "error": reply.error or "",
                }
            ),
        }
    )


def decode_metrics(text):
    """Reject metrics that would crash the coordinator's counters or its strict-JSON event log."""
    metrics = json.loads(text)
    if not isinstance(metrics, dict):
        raise ValueError("metrics must be a JSON object")
    json.dumps(metrics, allow_nan=False)  # Raises ValueError on NaN or infinity anywhere.
    examples = metrics.get("processed_examples", 0)
    if type(examples) is not int or examples < 0:
        raise ValueError("processed_examples must be a non-negative integer")
    return metrics


def decode_reply(content):
    result = content["result"]
    # Preserve sample type so protocol validation can reject malformed counts.
    return Reply(
        str(result["run_id"]),
        result["attempt"],
        result["version"],
        str(result["bank_id"]),
        str(result["request_id"]),
        content["weights"].to_numpy_ndarrays(),
        result["samples"],
        decode_metrics(str(result["metrics"])),
        str(result["error"]) or None,
    )


class FlowerTransport:
    def __init__(self, grid, bank_ids):
        self.grid = grid
        self.allowed = set(bank_ids)
        self.nodes = {}  # bank ID -> current runtime node ID
        self.identifying = {}  # message ID -> (node ID, expiry)
        self.pending = {}  # message ID -> (request, node ID, expiry)
        self.last_discovery = -float("inf")

    def _discover(self):
        now = time.monotonic()
        if now - self.last_discovery < 1:
            return
        self.last_discovery = now
        live = set(self.grid.get_node_ids())
        self.nodes = {bank: node for bank, node in self.nodes.items() if node in live}
        known = set(self.nodes.values()) | {node for node, _ in self.identifying.values()}
        for node in sorted(live - known):
            message = Message(
                content=RecordDict(),
                dst_node_id=node,
                message_type="query.identify",
                ttl=30,
            )
            ids = list(self.grid.push_messages([message]))
            if ids and ids[0]:
                self.identifying[ids[0]] = (node, now + 30)

    def online_banks(self):
        self._discover()
        return set(self.nodes)

    @staticmethod
    def _error(request, text):
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

    def submit(self, request):
        node = self.nodes.get(request.bank_id)
        if node is None or any(
            req.bank_id == request.bank_id for req, _, _ in self.pending.values()
        ):
            return False
        ttl = request.config.work_timeout + 5
        message = Message(
            content=request_content(request),
            dst_node_id=node,
            message_type="train",
            group_id=str(request.attempt),
            ttl=ttl,
        )
        ids = list(self.grid.push_messages([message]))
        if not ids or not ids[0]:
            return False
        self.pending[ids[0]] = (request, node, time.monotonic() + ttl)
        return True

    def poll(self):
        self._discover()
        replies = []
        ids = list(self.identifying) + list(self.pending)
        if ids:
            for message in self.grid.pull_messages(ids):
                original_id = message.metadata.reply_to_message_id
                if original_id in self.identifying:
                    node, _ = self.identifying.pop(original_id)
                    if message.has_error() or message.metadata.src_node_id != node:
                        continue
                    try:
                        bank = str(message.content["identity"]["bank_id"])
                        if bank in self.allowed and bank not in self.nodes:
                            self.nodes[bank] = node
                    except (KeyError, TypeError):
                        continue
                elif original_id in self.pending:
                    request, node, _ = self.pending.pop(original_id)
                    if message.has_error():
                        replies.append(self._error(request, str(message.error)))
                        continue
                    if message.metadata.src_node_id != node:
                        replies.append(self._error(request, "wrong source node"))
                        continue
                    try:
                        reply = decode_reply(message.content)
                        if reply.bank_id != request.bank_id:
                            reply = self._error(request, "bank identity mismatch")
                        replies.append(reply)
                    except (KeyError, TypeError, ValueError) as exc:
                        replies.append(self._error(request, f"malformed reply: {exc}"))
        now = time.monotonic()
        for key, (_, expires) in list(self.identifying.items()):
            if now >= expires:
                del self.identifying[key]
        for key, (request, _, expires) in list(self.pending.items()):
            if now >= expires:
                del self.pending[key]
                replies.append(self._error(request, "transport TTL expired"))
        return replies

    def close(self):
        pass  # The Flower runtime, not this adapter, owns the network connection.
