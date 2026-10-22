# Resilient Bank Federation

Three simulated banks train a shared fraud-detection model without sharing their
raw training records. Training can continue with two banks when one fails, and a
recovered bank can rejoin. Built with PyTorch, Flower, Docker, and Kubernetes.

## Prepare once

Install **uv**, **Docker Desktop with Linux containers**, **kubectl**, and **kind**.

```text
winget install --exact --id astral-sh.uv
winget install --exact --id Docker.DockerDesktop
winget install --exact --id Kubernetes.kubectl
winget install --exact --id Kubernetes.kind
```

Start Docker and run these commands from the repository root:

```text
uv sync --frozen --extra dev --python 3.12
uv run bank-fl demo setup
```

Setup downloads and verifies the ULB credit-card dataset from Kaggle, prepares
three bank partitions, builds the image, and starts a dedicated local Kubernetes
cluster. The first setup takes several minutes. Your default Kubernetes context
is unchanged. Allow Docker enough resources for four pods (each limited to 1 CPU
and 1 GiB memory), plus Kubernetes overhead.

If Kaggle requires login, download `creditcard.csv` from the
[dataset page](https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud), place it in
`data/raw`, and rerun setup. Follow the dataset's published terms.

## Present the demo

**Terminal 1 — start training:**

```text
uv run bank-fl demo start
```

**Terminal 2 — after a few rounds commit, terminate one bank pod:**

```text
uv run bank-fl demo fail
```

Show that rounds continue with the remaining banks. Kubernetes replaces the failed
pod; watch for the returning bank in a later committed round. The start command
exports results, evaluates the model, and creates charts automatically.

Explain: **local data → shared model → bank failure → continued training → rejoin**.
A ready replacement pod alone does not prove rejoin; show its accepted update.

Useful extras:

```text
uv run bank-fl demo status              # show the four pods
uv run bank-fl demo start --rounds 50   # allow more time to demonstrate recovery
uv run bank-fl demo results             # retry result export/evaluation
```

Results are saved under `results/demo`. Charts describe that run; they do not by
themselves prove a speedup over another training mode.

## Train without Kubernetes

```text
uv run bank-fl setup-data
uv run bank-fl flower --data data/ulb --rounds 5
uv run bank-fl evaluate <run-directory> --data data/ulb
uv run bank-fl plot <run-directory>
```

Use the run directory printed by training. `flower` uses separate local processes;
`run` is a threaded development harness. Always pass `--data data/ulb` for real data.

## Development

```text
uv run pytest
uv run ruff check app experiments k8s tests
uv run ruff format --check app experiments k8s tests
```

- [Demo guide](docs/demo.md): prerequisites, presentation, troubleshooting, cleanup.
- [Design](docs/design.md): model, coordination, recovery, and limitations.
- [Testing](docs/testing.md): correctness checks and repeated experiments.
- [Deployment](docs/deployment.md): manual Docker/Kubernetes commands.
- `uv run bank-fl --help`: all commands; add `--help` to any subcommand.

This is a research prototype with simulated banks. Early quorum can favour faster
banks. It does not provide coordinator failover, secure aggregation, or differential
privacy. Compare model quality and bank participation alongside training time.
