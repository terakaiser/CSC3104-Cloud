# Run the three banks on local Kubernetes

First follow the [Docker guide](../docker/README.md) to build `crossbank-fl:local` and prepare `data/deployment/`. Enable Kubernetes in Docker Desktop. Commands explicitly target `docker-desktop` rather than your current cloud context.

This setup targets a single-node Docker Desktop cluster with roughly 4 CPUs and 8 GB memory. It uses the local image (`imagePullPolicy: IfNotPresent`) and default storage class. Other clusters need an image registry/import and suitable storage configuration.

Run all commands from the repository root in PowerShell. You need the Docker image and prepared data folders, but Compose containers do not need to be running.

## Terms, files and command flags

For everyday use, [project.ps1](../project.ps1) wraps the detailed commands below:

| Shortcut (run from repository root) | When / what it does |
| --- | --- |
| `.\project.ps1 k8s setup` | Once after preparing data/building the image: create storage and upload data to fresh volumes. Skip when already loaded. |
| `.\project.ps1 k8s build` | Build the shared Docker image; same as `docker build` shortcut. Follow the image-refresh instructions below for existing pods. |
| `.\project.ps1 k8s start` | Apply workloads and wait for all four services to be ready. |
| `.\project.ps1 k8s train` | Submit training and follow logs; replaces the previous Job only if it completed. |
| `.\project.ps1 k8s results` | Copy results locally and print the newest saved status/summary; coordinator must be running. |
| `.\project.ps1 k8s status` | List pods. |
| `.\project.ps1 k8s logs` | Show recent coordinator and bank logs. |
| `.\project.ps1 k8s stop` | Scale services to zero while retaining storage; interrupts active training. |

Run `.\project.ps1 help` for the first-time sequence. These shortcuts do not create or reset the cluster. A missing `docker-desktop` context requires configuring Docker Desktop Kubernetes first. An active/failed submission Job is kept for investigation; inspect logs and actual training status before manually changing it. Submit only one experiment at a time.

A **pod** runs a container. A **Deployment** keeps the requested number of pods running. A **Service** gives pods a stable network address. A **namespace** groups this project's resources. A **persistent volume claim (PVC)** requests storage that survives pod replacement. A **Job** runs a task to completion; ours submits training.

| File | Purpose / when used |
| --- | --- |
| [storage.yaml](storage.yaml) | Creates the namespace and six storage claims before the first deployment. |
| [data-loaders.yaml](data-loaders.yaml) | Temporary upload pods; normally managed by the upload script rather than manually. |
| [load-data.ps1](load-data.ps1) | Uploads each role's CSV into fresh storage and removes the temporary pods. |
| [workloads.yaml](workloads.yaml) | Coordinator and three bank Deployments, read-only data mounts, health checks, resource limits and a coordinator Service. |
| [training-job.yaml](training-job.yaml) | Submits one training experiment; no automatic submission retries. |
| [Docker run settings](../docker/run-config.toml) | Training settings embedded in the shared image; see the [settings table](../docker/README.md#files-and-settings). |

`--context docker-desktop` selects the local cluster. `-n crossbank` selects our namespace. `apply -f <file>` creates or updates resources described by that file. `-f` on a **logs** command instead means follow new log messages. Commands that change resources below affect this project; there is no need to reset the cluster.

## Create storage and upload data

```powershell
kubectl --context docker-desktop get nodes
kubectl --context docker-desktop apply -f k8s/storage.yaml
.\k8s\load-data.ps1
```

The manifest creates namespace `crossbank` and six persistent volume claims: one per bank, validation data, results, and coordinator state. The script uses temporary loader pods to copy the matching CSV and synthetic-data marker to each data volume, then removes those pods. It uploads no test data and refuses to overwrite a nonempty data volume. Use fresh volumes and load data before starting the deployments; never mix datasets or upload during training. Skip the upload step when restarting an existing deployment with data already loaded.

`get nodes` checks that the cluster is reachable and its node is Ready. `apply` requests storage; a claim may remain Pending until a pod needs it. `load-data.ps1` defaults to `data/deployment/` and the `docker-desktop` context. If upload fails halfway, some volumes may already contain data; inspect the error and volumes before retrying rather than deleting storage blindly.

## Start the services

```powershell
kubectl --context docker-desktop apply -f k8s/workloads.yaml
kubectl --context docker-desktop -n crossbank rollout status deployment/coordinator --timeout=180s
kubectl --context docker-desktop -n crossbank rollout status deployment/bank-a --timeout=180s
kubectl --context docker-desktop -n crossbank rollout status deployment/bank-b --timeout=180s
kubectl --context docker-desktop -n crossbank rollout status deployment/bank-c --timeout=180s
kubectl --context docker-desktop -n crossbank get pods
```

Each bank mounts only its own data, read-only. The coordinator mounts validation data and writable results/state. Containers use a non-root user, resource requests/limits, and gRPC startup/readiness/liveness probes. A ClusterIP Service connects the banks to the coordinator; nothing is publicly exposed.

Each `rollout status` command waits up to 180 seconds for that Deployment to become ready. Stop and inspect the problem if one fails. `get pods` shows the running units: expect `1/1` ready for all four service pods. This starts services, not training. Use this step again after scaling them to zero.

## Train

```powershell
kubectl --context docker-desktop apply -f k8s/training-job.yaml
kubectl --context docker-desktop -n crossbank logs -f job/training-run
```

If the job is still starting, wait for its pod to run and repeat the logs command. The job submits two rounds and streams logs. It does not retry automatically, avoiding duplicate submissions. Submit one experiment at a time. Settings come from `docker/run-config.toml` in the image.

Applying an already completed Job does not start another experiment; use the delete-and-apply commands below after the previous training finishes. The Job's 1,200-second deadline bounds its submission/log-stream process, not a reliable cancellation deadline for server-side training.

## Read results

```powershell
New-Item -ItemType Directory -Force results/runs/kubernetes | Out-Null
$coordinatorPod = kubectl --context docker-desktop -n crossbank get pod -l app=coordinator -o jsonpath='{.items[0].metadata.name}'
kubectl --context docker-desktop -n crossbank cp "${coordinatorPod}:/results/." results/runs/kubernetes/
```

Open the newest `results_summary.txt` and confirm `training_status.json` says `completed`. Both training rows in `validation_results.json` should report three responding banks. A completed submission job alone is not proof of successful training.

`New-Item` creates the local destination if necessary; `Out-Null` hides routine output. The `$coordinatorPod` command finds the generated pod name using the `app=coordinator` label; `jsonpath` extracts just that name. `cp` copies the pod's results to your computer and requires the coordinator pod to be running. Existing local copies with matching filenames may be replaced.

After the previous experiment finishes, start another with:

```powershell
kubectl --context docker-desktop -n crossbank delete job training-run
kubectl --context docker-desktop apply -f k8s/training-job.yaml
```

Deleting the submission job preserves results and does not cancel an already-submitted run. To change code/settings, rebuild the image and restart all four deployments between runs.

For Docker Desktop, after rebuilding with the Docker guide's build command:

```powershell
kubectl --context docker-desktop -n crossbank rollout restart deployment/coordinator deployment/bank-a deployment/bank-b deployment/bank-c
```

This replaces the service pods. Repeat the four `rollout status` checks before submitting training. If your cluster caches the old `:local` image rather than refreshing it from Docker Desktop, use a new image tag, make it available to that cluster, and update all image references in the manifests. Never restart service pods in the middle of an experiment you want to preserve.

## Stop while preserving data

```powershell
kubectl --context docker-desktop -n crossbank scale deployment coordinator bank-a bank-b bank-c --replicas=0
```

Apply `k8s/workloads.yaml` again to restart them. Deleting the namespace or storage manifests can remove datasets, results, and coordinator state.

`scale ... --replicas=0` requests zero running copies of each service, while retaining their Deployments and storage. For another session, skip data upload, apply workloads, wait for readiness, then recreate the completed submission Job.

## Current limits

Connections are unencrypted and unauthenticated for trusted local development. TLS, bank authentication, network policies, and cloud storage remain future work. Separate mounts demonstrate data separation, not protection against cluster administrators or malicious application code. Kubernetes restarts processes, but training still requires all three banks and cannot automatically resume an interrupted round.

Docker Desktop's kind cluster uses a local image mirror. Keep `imagePullPolicy: IfNotPresent`; `Never` prevented this machine from loading the image from Docker's separate image store. For `ImagePullBackOff`, confirm the image was built and the mirror is available. Other local clusters may require explicitly importing the image. For `Pending`, inspect PVCs and `kubectl describe pod`. For a failed round, inspect bank/coordinator logs and saved status before submitting again.

Useful read-only diagnostic commands:

```powershell
kubectl --context docker-desktop -n crossbank get pvc
kubectl --context docker-desktop -n crossbank describe pods
kubectl --context docker-desktop -n crossbank logs deployment/coordinator --tail=100
kubectl --context docker-desktop -n crossbank logs deployment/bank-a --tail=100
```

`get pvc` shows whether storage is Bound. `describe pods` includes scheduling/startup events. `logs` shows application output; substitute `bank-b` or `bank-c` to inspect another bank.

Read [deployment verification](../docs/DEPLOYMENT_VERIFICATION.md) for checks already performed, [output explanations](../README.md#outputs-and-final-evaluation) for saved results, and the [reliability roadmap](../src/crossbank/reliability/README.md) for failure handling that is not implemented yet.
