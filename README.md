# Cross-Bank Federated Fraud Detection

CSC3104 Cloud & Distributed Computing - Team 18

A research prototype for collaborative fraud classification using **PaySim synthetic transactions**. Three simulated banks train the same PyTorch MLP through Flower. The current milestone is a measurable, synchronous baseline; Docker, Kubernetes, and resilient quorum/timeout/version management are future work.

## Current implementation

- Chronological PaySim train/validation/test preparation and three disjoint amount-skewed bank partitions.
- Shared nine-feature preprocessing and MLP training for bank-local, pooled, sequential FedAvg, and Flower experiments.
- Validation-selected thresholds, precision/recall/F1, average precision (`average_precision`), ROC-AUC, false-positive rate and confusion counts.
- Three-client Flower execution, round timings, run manifests, per-round checkpoints, and final global checkpoint.
- An all-client baseline that rejects missing/error/duplicate replies instead of silently aggregating a partial round.
- Separate explicit final-test evaluation; training commands never load `test.csv`.

See [baseline verification and initial PaySim results](docs/BASELINE_VERIFICATION.md) for the recorded checks and run artifacts.

This is transaction-level classification, not identity linking or cross-bank money-laundering graph detection. Sending model updates instead of rows is not a mathematical privacy guarantee. Local simulations do not establish independent bank data isolation.

## Start here: which command should I run?

Open the project folder in VS Code, then open **Terminal > New Terminal**. Run these commands from the repository root, the folder containing this README and `pyproject.toml`.

**First time on this computer?** Follow [Environment](#environment), then [Prepare PaySim](#prepare-paysim). The Python environment and datasets are not included in Git, so a fresh clone needs both steps.

**Already set up the environment and prepared the data?** Activate the environment in each new PowerShell terminal, then run the main project:

```powershell
.\.venv\Scripts\Activate.ps1
python scripts/run_flower.py
```

Activation makes `python` use this project's installed packages. If you prefer not to activate it, run the same program with its full Python path:

```powershell
.\.venv\Scripts\python.exe scripts/run_flower.py
```

### What the main command does

`python scripts/run_flower.py`:

1. Starts three local bank workers: Bank A, Bank B, and Bank C.
2. Selects up to 100,000 training transactions from each bank using the same repeatable sampling settings.
3. Sends the shared model to each bank for local training.
4. Collects all three updated models and combines them into one global model.
5. Checks the global model on validation data and repeats for a total of two rounds.
6. Saves the results and models in a new `results/runs/three_bank_federated__.../` folder.

A **round** is one cycle of sending, training, and combining models. An **epoch** is one pass through a bank's selected training rows. A **batch** is a smaller group processed at a time; the default is 1,024 transactions. Each bank trains for one epoch per round by default.

The terminal prints the results folder when the run finishes. Open **`results_summary.txt` first** for the easiest explanation of its scores. Check `training_status.json` for `"status": "completed"` and `"completed_rounds": 2`. The `.pt` files are saved models, not text reports.

### Compare collaboration with training alone

Run these separately if you want to compare the different approaches:

| Command | What it does |
| --- | --- |
| `python scripts/training/train_bank.py --bank a` | Trains Bank A alone, without collaboration. |
| `python scripts/training/train_bank.py --bank b` | Trains Bank B alone. |
| `python scripts/training/train_bank.py --bank c` | Trains Bank C alone. |
| `python scripts/training/train_centralised.py` | Pools the selected training rows from all three banks and trains one model. |
| `python scripts/run_flower.py` | Trains collaboratively by combining model updates from the three banks. |

These standalone models are comparison experiments. You do not need to train them before starting Flower, and Flower does not load their saved models. Each command creates a separate results folder and evaluates against the same validation dataset.

### Other commands and when to use them

| Command | When to use it |
| --- | --- |
| `uv sync --locked --extra dev --extra data` | Install the recorded dependency versions during setup or after dependency changes. |
| `python scripts/data/download_paysim.py` | Download PaySim. An existing `data/raw/paysim.csv` is preserved. |
| `python scripts/data/prepare_banks.py` | Create the three bank CSVs and validation/test splits. Running it again overwrites those prepared CSVs. |
| `python scripts/testing/test_fl_preprocessing.py` | Check that each bank's data produces nine valid input features. |
| `python -m pytest -q` | Run automated code checks. This does not train on the full PaySim dataset. |
| `python scripts/run_federated.py` | Run a simpler sequential FedAvg demonstration, with all banks handled in one process. |
| `python scripts/testing/create_smoke_data.py` | Create small artificial datasets in `data/smoke/` for quick execution checks. Run once; it refuses to overwrite that folder. |
| `python scripts/run_flower.py --data-dir data/smoke --batch-size 64` | Quickly check three-bank Flower execution after creating the artificial datasets. These scores are not fraud-performance evidence. |
| `python scripts/run_flower.py --help` | Show the available settings without starting training. |

### Try a longer training run

```powershell
python scripts/run_flower.py --rounds 10 --local-epochs 1
```

This runs ten rounds instead of two, keeping the same 100,000-row cap per bank. It creates a new run; it does not resume a previous checkpoint. More rounds take longer and do not guarantee better validation scores.

For comparable standalone runs with ten passes through their selected training data, use `--epochs 10` on the bank-only and centralised commands. Record all settings when comparing experiments; federated and standalone optimisation still differ as explained below.

Use validation results while choosing your settings. Run `scripts/testing/evaluate_checkpoint.py` on the final PaySim test split only after the experiment settings are fixed; see [Outputs and final evaluation](#outputs-and-final-evaluation).

## Environment

Use Python 3.12. Dependencies and the compatible Flower version are defined in `pyproject.toml`; `uv.lock` records resolved versions.

For a new checkout, create the environment, activate it, install dependencies, and check the code:

```powershell
uv venv --python 3.12 .venv
.\.venv\Scripts\Activate.ps1
uv sync --locked --extra dev --extra data
python -m pytest -q
```

If `.venv` already exists, skip `uv venv` and use the activation and sync commands. You do not need to reinstall packages every time you train.

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

Each new run gets one readable directory, such as `three_bank_federated__2026-10-11_13-00-00_SGT__a1b2c3`. Times use Singapore time; the short suffix prevents name clashes. Other prefixes are `bank_a_only`, `all_banks_pooled`, and `sequential_federated_demo`. Existing runs retain their old filenames and saved models remain loadable.

Start with `results_summary.txt` for plain-English results. JSON results use names such as `fraud_precision`, `fraud_recall`, `fraud_f1_score`, `average_precision`, `fraud_detected`, `fraud_missed`, `legitimate_transactions_flagged`, and `banks_responded`. Percentages are displayed in the summary; JSON retains numeric fractions between 0 and 1. Internal metric/checkpoint keys remain compatible with earlier saved models.

- `run_settings.json`: configuration, package versions, platform, feature/preprocessing version, dataset kind.
- `validation_results.json`: validation metrics and training timing. Flower includes round 0 and every completed round, reply counts, and training-row counts.
- `untrained_model.pt`, `model_after_round_001.pt`, ...: Flower weights, threshold, round, feature contract, and configuration.
- `final_model.pt`: final model for both federated and standalone runs.
- `training_status.json`: Flower running/completed/failed status and completed rounds.

Writes use temporary files and replacement. Checkpoints are reloadable for inference, but **automatic training resumption and coordinator crash recovery are not implemented**. The server's reply timeout applies after client selection; startup still waits for three available clients.

When the experiment design is fixed, evaluate a selected checkpoint on the untouched final test split:

```powershell
python scripts/testing/evaluate_checkpoint.py <path-to-final_model.pt>
```

This uses the saved validation threshold without tuning on test data and writes a sibling `.test_results.json`. Old `bank_*_pytorch.pt` checkpoints used bank-specific scalers and are rejected by this new loader. Do not average them into a global model.

Run artifacts are ignored by Git; archive the selected experiment directories separately for your report. Small smoke-run scores establish execution only.

## Tests and remaining project work

`python -m pytest -q` covers partitioning, preprocessing, training reproducibility, invalid settings, single-class training, checkpoint round trips, message-config overrides, and two actual Flower strategy rounds through an in-memory test Grid. A separate `run_flower.py` smoke run validates Ray worker execution.

Next: containerise separate bank/coordinator services, deploy Kubernetes workloads with isolated mounts and durable coordinator state, then implement and compare fixed/adaptive quorum, timeout, stale-version and recovery policies. Add controlled failure experiments and repeated-seed systems/ML measurements.

See [architecture](docs/ARCHITECTURE.md), [experiment plan](experiments/PLAN.md), and [report outline](docs/REPORT_NOTES.md). The [initial repository audit](docs/PROJECT_REPO_ANALYSIS.md) describes the state **before this baseline repair**. `configs/default.yaml` is a historical research plan, not active runtime configuration.

## Understanding warnings

| Warning | Meaning and action |
| --- | --- |
| `run_simulation` is deprecated | Flower plans to remove the older launch function. It works in our pinned version; migrate to the managed CLI when upgrading/deploying. |
| Ray support on Windows is experimental | Native Windows simulation has limited support. Our verification succeeded; use a separate WSL2/Linux environment if workers fail. |
| `fraction_evaluate` is 0 / federated evaluation skipped | Intentional: the banks do not evaluate separately. The server still evaluates the global model on validation data every round. |
| Ray accelerator/GPU environment-variable FutureWarning | Ray is announcing a future change to GPU visibility. This run requests zero GPUs and trains on CPU; it is not a failed training step. |
| `Manually terminating ClientAppActor` | Ray is shutting down a bank worker. At normal shutdown after completed rounds this is cleanup; during a failed round, inspect the error and `training_status.json`. |
| Typer/Click deprecation warnings during pytest | A dependency uses an older command-line API. Tests can still pass; update compatible dependencies when maintained versions are available. |

Warnings are not globally hidden. A real error, missing bank reply, or failed status still requires investigation. Check `training_status.json` for `"status": "completed"` and the expected completed-round count.
