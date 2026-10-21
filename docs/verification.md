# Implementation verification

Verified on 21 October 2026 in `C:\SIT_Projects\CSC3104-Cloud`.
The training and recovery checks below used **synthetic software-test data**.
The later real-dataset setup check is documented separately below. These checks
establish working software, not fraud-detection quality or a research speedup.

## Automated checks

- Python 3.12.13; dependencies installed from `uv.lock`.
- `ruff check app experiments tests k8s`: passed.
- `ruff format --check app experiments tests k8s`: passed (31 files).
- `pytest`: **38 passed**. Two upstream protobuf deprecation warnings; no failures.
- Coverage includes weighted aggregation, invalid/duplicate/stale updates,
  quorum loss, strict and timeout modes, delayed-client rejoin, next-round dispatch,
  deterministic data splits, configuration validation, message serialization,
  evaluation metrics, pod data isolation and recovery measurement.

## Integration checks

| Check | Observed outcome |
|---|---|
| Separate-process local Flower | Eight committed versions; saved checkpoints evaluated successfully |
| Five-bank local harness (Q=3) | Three of three rounds committed; all five banks contributed; no unresolved requests |
| Missing bank with Q=3 | Explicit `startup_timeout`, zero committed rounds; bounded by configured startup timeout |
| Small repeat matrix | Centralized plus eight federated runs; healthy, slow and unavailable scenarios; all outputs evaluated and plotted |
| Failure retention | The unavailable synchronous run remains in comparison CSV/plots with zero completed rounds |
| Plot output | `comparison.png`, `systems.png`, individual CSV and grouped CSV generated; figures visually checked |
| Docker | Locked CPU image `bank-fl:0.1.0` built successfully |
| Kubernetes | Four non-root pods started and became Ready with the generated manifest |

The small matrix used one seed, three target rounds and a three-second deadline.
It is a functional check, not the three-seed research study. The synchronous slow
run needed five attempts for three commits; resilient and timeout modes each
committed three versions. These timings come from the local threaded harness and
must not be presented as distributed performance results.

The initial local Flower check exposed late-dispatch starvation: a returning bank
could repeatedly start work near the end of an attempt. Dispatch now happens only
at the next round boundary; an additional regression test protects that behavior.
Early quorum can still underrepresent a consistently slower bank, so participation
counts remain part of every result.

## Kubernetes pod-replacement check

Environment: Docker Desktop, kind 0.33.0, Kubernetes 1.37.0; one coordinator and
three bank pods, each limited to one CPU and 1 GiB. Image ID:
`sha256:62c04bcece0742f7c2920775e9187f26f6250d26886e2e7266a0a2aafb666195`.

Run `20261021T134539-b7647126` used 30 rounds, Q=2 and a 30-second deadline.
Bank 1's pod was deleted during attempt 4. The stored event log shows:

- **30/30 attempts committed**, with no unresolved requests.
- Attempts 4 and 5 committed using banks 2 and 3 while bank 1 recovered.
- Bank 1's replacement became Ready after **3.203 seconds**.
- A request dispatched after readiness produced an accepted update in attempt 6,
  **29.830 seconds** after the fault.
- Final participation: bank 1 = 22, bank 2 = 21, bank 3 = 19 committed rounds.
- Thirteen stale updates and one unavailable-node error were rejected; one
  outstanding response was discarded after the final commit.
- Training took 378.965 seconds including startup/discovery;
  this is one synthetic functional test, not a performance comparison.

Results, all 31 checkpoints (including initialization), recovery measurements and
plots were exported to `results/k8s-verification/` before cluster cleanup.
The single-node kind setup used a repository-local kubeconfig; it did not replace
the user's default context. The temporary cluster was removed after export.

## Evidence on this workstation

Generated files are ignored by Git. Preserve/export them separately when preparing
submission evidence:

- `results/verification/matrix/`: nine evaluated runs and comparison figures.
- `results/verification/five-banks/`: five-bank harness check.
- `results/verification/startup-failure/`: zero-round failure plus evaluation/plots.
- `results/verification/flower-runtime-69810246/`: earlier local Flower run and logs.
- `results/verification/centralized/`: eight-version pooled baseline check.
- `results/k8s-verification/`: cluster configuration, versions, fault record and logs.

## Remaining research work

On a fresh clone, use `uv run --python 3.12 bank-fl setup-data` to obtain the real
ULB CSV. It has now been prepared locally at `data/ulb`. Freeze pilot-derived
deadlines, run the documented repeated
matrix on one consistent deployment/hardware configuration, and report quality,
participation and resource measurements. Do not pool Windows-process and Linux-pod
measurements as interchangeable repeats. Five-bank deployment generation and local
execution were checked; a five-bank Kubernetes experiment was not run.

Minikube and cloud-VM commands are provided but were not executed here. The actual
cluster verification uses kind on Docker Desktop. This does not establish
multi-machine/cloud performance, production privacy, coordinator failover or a
statistical benefit. The final report, testing PDF and video remain team deliverables.

## Real-dataset setup addition

`bank-fl setup-data` downloads Kaggle dataset `mlg-ulb/creditcardfraud`, version 3,
checks the CSV SHA-256 and prepares bank partitions. It adds no package dependencies.
The official public endpoint returned the dataset without credentials during verification.

The raw CSV is 150,828,752 bytes. Its pinned SHA-256 is:
`76274b691b16a6c49d3f159c883398e03ccd6d1ee12d9d8ee38f4b4b98551a89`.
Preparation with three banks and seed 42 produced training partitions of
53,444 / 91,585 / 53,579 rows, with 93 / 146 / 92 fraud examples respectively.
These are prepared real-data partitions, not completed real-data training experiments.

The expanded automated suite has **43 passing tests**. New checks cover checksum
validation, cache reuse without network access, extracting only the expected CSV,
refusing to overwrite conflicting data, and cleanup after interrupted preparation.
Lint and formatting pass. Original training/recovery evidence above remains unchanged.
