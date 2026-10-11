# Run the three banks with Docker

Run these commands from the repository root in PowerShell. Start Docker Desktop with Linux containers. Allow roughly 4 CPUs and 8 GB memory.

Flower 1.28's Deployment Runtime runs one coordinator (SuperLink) and three banks (SuperNodes), each starting its training handler in a subprocess. Ray is not used. They share a CPU image but mount separate datasets: each bank gets only its own CSV, and the coordinator gets only validation data. No test data is mounted.

New checkout? First complete the root README's [Python environment setup](../README.md#environment) for the data preparation commands. An **image** is the packaged code and dependencies; a **container** is a running copy; a **volume** keeps stored files after containers are removed. You do not need Kubernetes to follow this guide.

## Files and settings

For everyday use, [project.ps1](../project.ps1) wraps the commands below:

| Shortcut (run from repository root) | When / what it does |
| --- | --- |
| `.\project.ps1 docker setup` | Once: prepare artificial smoke data and separate deployment folders; refuses to overwrite existing deployment data. |
| `.\project.ps1 docker build` | First time or after code/settings changes: build the shared image. |
| `.\project.ps1 docker start` | Start services and wait for health checks; does not train. |
| `.\project.ps1 docker train` | Submit a new run and show logs. |
| `.\project.ps1 docker results` | Copy results locally and print the newest saved status/summary; requires services running. |
| `.\project.ps1 docker status` | List service state. |
| `.\project.ps1 docker logs` | Show the last 100 log lines per service. |
| `.\project.ps1 docker stop` | Stop services while keeping volumes; interrupts active training. |

Skip `setup` and `build` on repeat runs with existing data and an unchanged image. For PaySim, use the explicit preparation instructions below instead of the smoke-data shortcut. The full commands remain below for troubleshooting.

| File | Purpose / when to edit it |
| --- | --- |
| [Dockerfile](Dockerfile) | Image recipe: installs packages and application code, then runs as a non-root user. Edit when changing packaging. |
| [.dockerignore](../.dockerignore) | Allows only build inputs into Docker's build context; excludes datasets, credentials, results and the local environment. |
| [requirements.in](requirements.in) | Short dependency list to edit when intentionally updating packages. |
| [requirements.txt](requirements.txt) | Generated exact versions and hashes; Docker installs from it. Regenerate instead of editing by hand. |
| [compose.yaml](compose.yaml) | Defines services, commands, connections, data mounts, CPU/memory limits, health checks and volumes. |
| [flower-config.toml](flower-config.toml) | Tells the submission tool to connect to `coordinator:9093`. |
| [run-config.toml](run-config.toml) | Training overrides shared by Docker and Kubernetes. Rebuild after editing. |
| [check_health.py](check_health.py) | Automatically checks Flower's health endpoint; you do not normally run it yourself. |
| [prepare_deployment_data.py](../scripts/prepare_deployment_data.py) | Copies each required CSV into its role's separate mount folder. |
| [test_deployment_data.py](../tests/test_deployment_data.py) | Checks data separation, smoke labels, missing inputs and overwrite protection. Run with the project test suite. |
| [pyproject.toml](../pyproject.toml) | Registers the Flower app and restricts its distributed bundle to application code and required metadata. |
| [.gitignore](../.gitignore) | Keeps deployment CSV copies and generated Flower bundles out of Git. |

| Run setting | Default | Meaning |
| --- | --- | --- |
| `num-server-rounds` | 2 | Number of cycles of local training and combining bank updates. |
| `local-epochs` | 1 | Passes through selected training rows at each bank per round. |
| `batch-size` | 64 | Transactions processed together; the local PaySim simulation defaults to 1024 instead. |
| `max-samples` | 100000 | Maximum training rows per bank; tiny smoke fixtures use fewer. |
| `round-timeout` | 300 seconds | Reply deadline after clients are selected; startup still waits for three banks. |
| `data-dir` / `output-dir` | `/data` / `/results` | Paths inside containers, not Windows folders. |

Learning rate and seed retain the defaults in `pyproject.toml` unless overridden. All three bank replies remain mandatory. Keeping checkpoints does not mean a failed round will resume automatically.

## Prepare data

```powershell
.\.venv\Scripts\python.exe scripts/testing/create_smoke_data.py
.\.venv\Scripts\python.exe scripts/prepare_deployment_data.py
```

Skip the first command if `data/smoke/` already exists. The second copies four CSVs into separate folders under `data/deployment/` and refuses to overwrite that directory. These artificial fixtures test execution, not fraud performance. For PaySim, use `--data-dir data/processed` when preparing a fresh deployment folder. Never replace data during training.

## Build and start

```powershell
docker compose -f docker/compose.yaml build coordinator
docker compose -f docker/compose.yaml up -d --wait
docker compose -f docker/compose.yaml ps
```

The first build downloads hash-locked Linux dependencies, including CPU PyTorch. The image contains no datasets, models, credentials, or results. Four healthy services mean Flower is ready, not that training has completed.

`build coordinator` builds the shared image used by all four services. `up -d --wait` starts them in the background and waits for health checks. `ps` lists their current state. Run the build on first setup and after code/dependency/settings changes; run `up` whenever services are stopped. After rebuilding an existing deployment, run `up -d --wait` again between experiments so services use the new image.

## Train

```powershell
docker compose -f docker/compose.yaml run --rm submit
```

This submits the application and streams the coordinator output. It runs two rounds with one local epoch, requiring all three banks to reply. Settings are in `docker/run-config.toml`; rebuild after editing settings or source code. Each submission starts a new experiment. Submit only one run at a time.

`run --rm submit` starts the temporary submission container and removes it when the command finishes. It does not remove saved models or stop the four training services. The `submit` service is optional, so ordinary `up` does not launch training.

The `fab-include` allowlist in `pyproject.toml` bundles only application Python files plus Flower's required project configuration. Other banks' CSVs are never bundled.

## Read results

```powershell
docker compose -f docker/compose.yaml logs --tail 100 coordinator bank-a bank-b bank-c
New-Item -ItemType Directory -Force results/runs/docker | Out-Null
docker compose -f docker/compose.yaml cp coordinator:/results/. results/runs/docker/
```

Open the newest run's `results_summary.txt`. Expect `status: completed` and `completed_rounds: 2` in `training_status.json`, three responding banks in both training rows of `validation_results.json`, and `final_model.pt`. Check these even if submission exits successfully; submission alone does not prove training succeeded.

Results and Flower's database use named volumes and survive container replacement. Saved checkpoints do not provide automatic recovery of interrupted rounds yet.

`logs --tail 100` prints recent messages from each named service. `New-Item -ItemType Directory -Force` ensures the destination folder exists; `Out-Null` hides that command's routine output. `cp` copies results out of the running coordinator. Run these after training or when investigating a problem. Copies with the same filenames may be replaced; the original run volumes remain intact.

## Stop

```powershell
docker compose -f docker/compose.yaml down
```

This preserves result and state volumes. Adding `--volumes` would erase them.

In every Compose command, `-f docker/compose.yaml` selects our configuration file. `down` stops/removes its containers and network; run it when finished. For another session with existing data and an unchanged image, start at **Build and start**, skipping the build command, then **Train**. Do not rerun dataset preparation into the existing directory.

## Scope and troubleshooting

- This is trusted local development: Flower connections are unencrypted and unauthenticated. No host ports are published. Add TLS and bank authentication before running across machines or with sensitive data.
- Missing mount folder: prepare deployment data first. Failed round: inspect bank and coordinator logs. The synchronous strategy stops if a bank is missing.
- Health probes check Flower services, not training progress or bank registration.
- Flower may warn that the recommended project `license` field is missing. This does not stop training; the team still needs to choose a license. The `fraction_evaluate=0` warning means bank-side evaluation is disabled; the coordinator still evaluates validation data after each round.
- Linux deployment dependencies use CPU PyTorch and omit Ray, so they have a separate lock from Windows development. Regenerate with `uv pip compile docker/requirements.in --python-version 3.12 --python-platform linux --torch-backend cpu --generate-hashes --output-file docker/requirements.txt`.

See [Flower's network architecture](https://flower.ai/docs/framework/1.22/en/ref-flower-network-communication.html). Commands here are checked against the installed 1.28.0 CLI.

For recorded test evidence, read [deployment verification](../docs/DEPLOYMENT_VERIFICATION.md). For metric meanings and model files, read [outputs and final evaluation](../README.md#outputs-and-final-evaluation). Continue to the [Kubernetes guide](../k8s/README.md) when testing pod orchestration.
