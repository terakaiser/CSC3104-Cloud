# Cross-Bank Federated Fraud Detection

CSC3104 Cloud & Distributed Computing - Team 18

A research prototype for collaborative fraud classification using **PaySim synthetic transactions**. Three simulated banks train the same PyTorch MLP through Flower. The current milestone is a measurable, synchronous baseline; Docker, Kubernetes, and resilient quorum/timeout/version management are future work.

## Current implementation

- Chronological PaySim train/validation/test preparation and three disjoint amount-skewed bank partitions.
- Shared nine-feature preprocessing and MLP training for bank-local, pooled, sequential FedAvg, and Flower experiments.
- Validation-selected thresholds, precision/recall/F1, average precision (`pr_auc`), ROC-AUC, false-positive rate and confusion counts.
- Three-client Flower execution, round timings, run manifests, per-round checkpoints, and final global checkpoint.
- An all-client baseline that rejects missing/error/duplicate replies instead of silently aggregating a partial round.
- Separate explicit final-test evaluation; training commands never load `test.csv`.

See [baseline verification and initial PaySim results](docs/BASELINE_VERIFICATION.md) for the recorded checks and run artifacts.

This is transaction-level classification, not identity linking or cross-bank money-laundering graph detection. Sending model updates instead of rows is not a mathematical privacy guarantee. Local simulations do not establish independent bank data isolation.

## Environment

Use Python 3.12. Dependencies and the compatible Flower version are defined in `pyproject.toml`; `uv.lock` records resolved versions.

```powershell
uv venv --python 3.12 .venv
.\.venv\Scripts\Activate.ps1
uv sync --locked --extra dev --extra data
python -m pytest -q
```

Optional archived XGBoost/plotting dependencies: add `--extra research` to the sync command. A pip-compatible alternative is `pip install -e ".[dev,data]"`; `pip install -r requirements.txt` installs all extras. These pip commands use version ranges rather than the lockfile.

Run commands below from the repository root. Activation is optional if you use `.venv/Scripts/python.exe` explicitly.

## Quick execution smoke test

These fixtures are **artificial, not PaySim**, and must not be used as fraud-quality evidence. The fixture generator refuses to overwrite an existing directory.

```powershell
python scripts/testing/create_smoke_data.py
python scripts/run_flower.py --data-dir data/smoke --batch-size 64
```

The launcher runs exactly three Ray-backed Flower clients, two rounds, and one local epoch per round. It exits unsuccessfully unless the server's saved status confirms completion. It uses absolute data/output paths and writes into a unique folder under `results/runs/`.

Flower 1.28's direct `run_simulation` API is used for this local launcher. Flower marks this API deprecated; the dependency is pinned, and migration to the managed CLI/deployment runtime remains necessary before upgrading it. The managed `flwr run` launcher failed to start its SuperLink on the reviewed Windows machine. Ray's Windows support is experimental; use a separate Linux environment under WSL2 if native execution fails. Do not reuse the Windows virtual environment in WSL.

The registered ClientApp/ServerApp also remain available to Flower's CLI on supported setups:

```powershell
flwr run . --federation-config "num-supernodes=3 client-resources-num-cpus=1" --stream
```

For that CLI route, override `data-dir` and `output-dir` with absolute paths using `--run-config`, since the managed runtime can execute in an extracted application directory.

## Prepare PaySim

```powershell
python scripts/data/download_paysim.py
python scripts/data/prepare_banks.py
python scripts/testing/test_fl_preprocessing.py
```

The public dataset is [PaySim on Kaggle](https://www.kaggle.com/datasets/moonknightmarvel/paysim). If download access requires account interaction, download it manually and put the transaction CSV at `data/raw/paysim.csv`. The downloader preserves an existing destination.

Preparation uses:

| Split | Time steps | Output |
| --- | --- | --- |
| Training | <=520 | `bank_a.csv`, `bank_b.csv`, `bank_c.csv` |
| Validation | 521-632 | `validation.csv` |
| Final test | >632 | `test.csv` |

Files are written to `data/processed/` and excluded from Git. Preparation loads the full raw CSV into memory.

## Run the comparable MLP baselines

```powershell
python scripts/training/train_bank.py --bank a
python scripts/training/train_bank.py --bank b
python scripts/training/train_bank.py --bank c
python scripts/training/train_centralised.py
python scripts/run_flower.py
```

Defaults are a reproducible **100,000-row cap per bank**, batch size 1024, learning rate 0.001, seed 42, and two epochs for each standalone model versus two FL rounds of one local epoch. Use `--max-samples 0` for all training rows. Caps apply independently to each bank before pooling, so pooled and federated experiments see the same selected training rows.

All paths use the same nine inputs: scaled step, log-scaled amount and two opening balances, and five one-hot transaction types. All use the same 9 -> 64 -> 32 -> 1 MLP, Adam, and class-weighted binary cross-entropy. Positive-class weights are calculated from each training population; single-class samples use unweighted loss. Flower resets Adam each round, whereas standalone training keeps Adam state across epochs. Record these differences when interpreting comparisons.

Standalone scripts accept `--epochs`; Flower accepts `--rounds`, `--local-epochs`, and `--round-timeout`. Common flags are `--data-dir`, `--output-dir`, `--batch-size`, `--learning-rate`, `--max-samples`, and `--seed`. Use `--help`.

`python scripts/run_federated.py` is a separate educational sequential FedAvg run. It shares preprocessing and training with Flower, but it is not evidence of networked deployment.

## Outputs and final evaluation

Each new run gets its own directory; tracked legacy model files are preserved.

- `manifest.json`: configuration, package versions, platform, feature/preprocessing version, dataset kind.
- `metrics.json`: validation metrics and training timing. Flower includes round 0 and every completed round, reply counts, and training-row counts.
- `round-000.pt`, `round-001.pt`, ...: Flower weights, threshold, round, feature contract, and configuration.
- `global_model.pt`: final FL checkpoint; standalone baselines save `model.pt`.
- `status.json`: Flower running/completed/failed status and completed rounds.

Writes use temporary files and replacement. Checkpoints are reloadable for inference, but **automatic training resumption and coordinator crash recovery are not implemented**. The server's reply timeout applies after client selection; startup still waits for three available clients.

When the experiment design is fixed, evaluate a selected checkpoint on the untouched final test split:

```powershell
python scripts/testing/evaluate_checkpoint.py <path-to-global_model.pt>
```

This uses the saved validation threshold without tuning on test data and writes a sibling `.test.json`. Old `bank_*_pytorch.pt` checkpoints used bank-specific scalers and are rejected by this new loader. Do not average them into a global model.

Run artifacts are ignored by Git; archive the selected experiment directories separately for your report. Small smoke-run scores establish execution only.

## Tests and remaining project work

`python -m pytest -q` covers partitioning, preprocessing, training reproducibility, invalid settings, single-class training, checkpoint round trips, message-config overrides, and two actual Flower strategy rounds through an in-memory test Grid. A separate `run_flower.py` smoke run validates Ray worker execution.

Next: containerise separate bank/coordinator services, deploy Kubernetes workloads with isolated mounts and durable coordinator state, then implement and compare fixed/adaptive quorum, timeout, stale-version and recovery policies. Add controlled failure experiments and repeated-seed systems/ML measurements.

See [architecture](docs/ARCHITECTURE.md), [experiment plan](experiments/PLAN.md), and [report outline](docs/REPORT_NOTES.md). The [initial repository audit](docs/PROJECT_REPO_ANALYSIS.md) describes the state **before this baseline repair**. `configs/default.yaml` is a historical research plan, not active runtime configuration.
