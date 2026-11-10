"""Concurrent local harness; use Flower deployment for distributed-system measurements."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.protocol import Request, error_reply
from app.worker import execute


class LocalTransport:
    def __init__(self, data_root: Path, bank_ids, unavailable=()):
        self.data_root = data_root
        self.banks = set(bank_ids) - set(unavailable)
        self.executor = ThreadPoolExecutor(max_workers=len(bank_ids))
        self.pending = {}

    def online_banks(self):
        return self.banks.copy()

    def submit(self, request: Request):
        if request.bank_id not in self.banks or request.bank_id in self.pending:
            return False
        future = self.executor.submit(
            execute, request, self.data_root / request.bank_id / "train.npz"
        )
        self.pending[request.bank_id] = (request, future)
        return True

    def poll(self):
        replies = []
        for bank, (request, future) in list(self.pending.items()):
            if not future.done():
                continue
            del self.pending[bank]
            try:
                replies.append(future.result())
            except Exception as exc:
                replies.append(error_reply(request, f"{type(exc).__name__}: {exc}"))
        return replies

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)
