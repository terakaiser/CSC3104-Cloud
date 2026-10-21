import os
from pathlib import Path

import torch
from flwr.common import Context
from flwr.serverapp import Grid, ServerApp

from app.config import RunConfig
from app.coordinator import run
from app.data import read_manifest
from app.flower_transport import FlowerTransport

app = ServerApp()


@app.main()
def main(grid: Grid, context: Context):
    torch.set_num_threads(1)
    config = RunConfig(**{k.replace("-", "_"): v for k, v in context.run_config.items()})
    root = Path(os.environ.get("BANK_FL_DATA", "data/processed")).resolve()
    output = Path(os.environ.get("BANK_FL_OUTPUT", "results")).resolve()
    directory = run(
        config,
        read_manifest(root),
        FlowerTransport(grid, config.bank_ids),
        output,
        "flower",
    )
    print(f"Results saved to {directory}", flush=True)
