# Docker and Kubernetes verification

Verified on 11 October 2026 using the existing 256-row artificial smoke fixtures. These checks establish deployment execution, not fraud-detection performance or production security.

| Check | Result |
| --- | --- |
| Docker image build | Passed with Python 3.12.15, Flower 1.28.0 and CPU PyTorch 2.14.1 |
| Compose health checks | Coordinator and all three banks healthy |
| Docker networked training | Two rounds completed; three bank replies each round |
| Kubernetes API validation | Storage, deployments, service, loader pods and job accepted |
| Kubernetes training | Four healthy service pods; submission job completed; two rounds with three bank replies |
| Data mounts in both runtimes | Each bank sees only its own CSV and smoke marker; coordinator sees validation CSV and marker |
| Flower application bundle | Only application Python files, project configuration and bundle metadata |
| Checkpoint readback | Initial, both round checkpoints and final model loaded successfully for both runs |
| Coordinator pod replacement | Completed status and final checkpoint remained available after a Kubernetes rollout restart |
| Python tests | Existing 15 tests passed; two new deployment-data tests passed |

The data preparation tests check bank separation, exclusion of final-test data, preservation of the synthetic-data marker, refusal to overwrite existing output, and detection of missing inputs before copying.

Local artifacts (ignored by Git):

- Docker: `results/runs/docker/three_bank_federated__2026-10-11_13-38-09_SGT__9b8288/`, training duration about 25 seconds.
- Kubernetes: `results/runs/kubernetes/three_bank_federated__2026-10-11_13-42-13_SGT__de996e/`, training duration about 25 seconds.

Both `training_status.json` files report `completed` with two completed rounds. Both `run_settings.json` files label the input as `synthetic-smoke`. Scores are intentionally not presented as model-quality evidence.

After verification, Docker Compose services were stopped with volumes preserved. The Kubernetes coordinator and three bank deployments were left running for inspection, with the training job completed and no active training run.

The initial Kubernetes attempt used `imagePullPolicy: Never`, which failed because this Docker Desktop kind cluster has a separate image store. `IfNotPresent` allowed its local image mirror to retrieve the built image, and the full run then passed. No image was published to an external registry.

Expected warnings: Flower recommends project license metadata (the team has not selected a license); `fraction_evaluate=0` skips bank-side evaluation while coordinator validation still runs; existing Python tests report two third-party Typer/Click deprecations. `kubectl cp` may print that tar removed a leading slash; successful copies were read back and checked.

Not established by these checks: recovery from a failure during training, quorum-based continuation, hostile-bank isolation, TLS/authentication, cloud deployment, multi-node storage, or performance on the full PaySim partitions. See the [Docker guide](../docker/README.md) and [Kubernetes guide](../k8s/README.md) for commands and limits.
