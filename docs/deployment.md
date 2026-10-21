# Docker and Kubernetes

## Build

From the repository root with Docker running:

```text
docker build -t bank-fl:0.1.0 .
```

The image uses the locked CPU dependencies and runs as UID/GID 10001. It contains
application code, not datasets or course documents. The cluster examples use
unencrypted Flower connections inside a trusted private environment. Do not
expose the service to the public internet; configure Flower TLS first if the
deployment crosses an untrusted network.

## Minikube

Prepare data on the workstation, then start the cluster:

```text
uv run bank-fl prepare --synthetic --output data/cluster
minikube start --cpus=4 --memory=6144
minikube image load bank-fl:0.1.0
```

Keep a separate terminal open for the data mount. Replace the example path with
the absolute prepared-data directory:

```text
minikube mount "C:\SIT_Projects\CSC3104-Cloud\data\cluster:/mnt/bank-fl"
```

The mount must expose readable directories and files to UID 10001. Then:

```text
kubectl apply -f k8s/deployment.yaml
kubectl -n bank-fl rollout status deployment/coordinator
kubectl -n bank-fl get pods
kubectl -n bank-fl port-forward service/coordinator 9093:9093
```

Keep port-forward running and use another terminal to submit:

```text
uv run flwr run . local --stream --run-config "rounds=8 deadline=30.0"
```

The coordinator mounts only `/mnt/bank-fl/manifest.json`. Each bank mounts only
`/mnt/bank-fl/bank-N`. Outputs go to a 1 GiB persistent volume claim. A default
storage class is required. Data is mounted read-only. The manifest is deliberately
for a single-node coursework cluster; hostPath data must exist on the worker.

On a Linux cloud VM, place prepared data at `/mnt/bank-fl`, ensure it is readable
by UID 10001, and use the same manifest. Load the image into that cluster's
container runtime or specify a reachable image. Retain the cluster internally;
use an SSH tunnel for the control port.

## Five banks

```text
uv run bank-fl prepare --synthetic --banks 5 --output data/cluster-five
uv run python k8s/render.py --banks 5 --output k8s/five-banks.yaml
```

Mount the five-bank directory at `/mnt/bank-fl`, then apply the generated manifest:

```text
kubectl apply -f k8s/five-banks.yaml
uv run flwr run . local --stream --run-config "banks=5 quorum=3 rounds=8"
```

Use one matching dataset/manifest per experiment. When returning to three banks,
remove the two extra bank Deployments explicitly or use a fresh test cluster;
applying a smaller manifest does not delete omitted resources.

## Inject a fault while a run is active

Start an experiment long enough for recovery (for example, 20 rounds). From a
second terminal:

```text
uv run python -m experiments.fault --kind kill --bank bank-3 --output results/kill.json
uv run python -m experiments.fault --kind absence --bank bank-3 --duration 20 --output results/absence.json
```

Run these as separate experiments, not simultaneously. The script only mutates
bank Deployments/pods in namespace `bank-fl`; it checks the initial replica count.
Temporary absence restores the original replica count in a `finally` block.
If the operator forcibly kills the script or machine during absence, restore with:

```text
kubectl -n bank-fl scale deployment bank-3 --replicas=1
```

Fault-to-ready measures a newly created pod becoming Ready. Fault-to-accepted-update
must be calculated separately: process health is not proof of useful participation.
The recovery command counts only accepted replies to requests dispatched after
the replacement pod became Ready, excluding buffered work from the old pod.
Use synchronized operator/coordinator clocks.

## Retrieve and evaluate results

The streamed log prints a run directory under `/results`. Find the coordinator
pod name, then copy its results (replace `<pod>`):

```text
kubectl -n bank-fl get pods -l app=coordinator
kubectl -n bank-fl cp <pod>:/results ./results/cluster
uv run bank-fl evaluate results/cluster/<run-id> --data data/cluster
uv run python -m experiments.recovery results/cluster/<run-id> results/kill.json
uv run bank-fl plot results/cluster/<run-id>
```

Export results before cleaning up. `kubectl delete -f k8s/deployment.yaml` removes
the workloads, namespace and result claim; the storage-class reclaim policy may
delete result storage. Keep the host dataset and exported evidence.

## Troubleshooting

- `Pending` results claim: verify the cluster's default storage class.
- Mount errors: confirm the prepared files exist inside the cluster node at
  `/mnt/bank-fl`, not only on the Windows host.
- `ImagePullBackOff`: load the locally built image into the selected cluster.
- Startup timeout: inspect all bank logs and verify the manifest's bank count.
- Nonzero deadline failures on healthy data: include cold-start costs in the
  pilot and choose a suitable deadline before the comparison study.
- Bank restart takes time: Flower heartbeat expiry and Python startup are part
  of measured recovery. Do not count pod readiness as a returned model update.

## Verified alternative: kind on Docker Desktop

The implementation was also checked on a single-node kind cluster. Install kind,
prepare `data/processed`, and save this as `results/kind.yaml` (adjust the host path):

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraMounts:
  - hostPath: C:/SIT_Projects/CSC3104-Cloud/data/processed
    containerPath: /mnt/bank-fl
    readOnly: true
```

In PowerShell, use an isolated kubeconfig for the test:

```powershell
kind create cluster --name bank-fl-check --config results/kind.yaml --kubeconfig results/kubeconfig
$env:KUBECONFIG = (Resolve-Path results/kubeconfig).Path
kind load docker-image bank-fl:0.1.0 --name bank-fl-check
kubectl apply -f k8s/deployment.yaml
kubectl -n bank-fl wait --for=condition=Ready pod --all --timeout=180s
```

Use the same port-forward, run, fault and result-retrieval steps above. After
exporting results, `kind delete cluster --name bank-fl-check` removes this test
cluster. Use a distinct name if that cluster already exists.
