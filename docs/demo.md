# Demonstration guide

## Prerequisites

Run from the repository root. Install [uv](https://docs.astral.sh/uv/),
[Docker Desktop](https://docs.docker.com/desktop/),
[kubectl](https://kubernetes.io/docs/tasks/tools/), and
[kind](https://kind.sigs.k8s.io/docs/user/quick-start/). Make each command available
on PATH, and start Docker with Linux containers enabled. Setup checks for missing
tools before downloading data or changing the cluster.

```text
uv sync --frozen --extra dev --python 3.12
uv run bank-fl demo setup
```

Setup uses real ULB data by default. It verifies the downloaded CSV checksum,
removes duplicates, creates a 70/15/15 training/validation/test split, and prepares
three disjoint bank partitions. Existing matching data is reused. Older PaySim or
bank CSV files are not compatible with this model and are not used.

For a software-only rehearsal, use `demo setup --synthetic` instead. The same
cluster cannot switch datasets by rerunning setup: keep the chosen dataset for
that demo. Synthetic results must be labelled as software checks.

The demo owns the `bank-fl-demo` kind cluster and stores its kubeconfig and state
under `.demo`. It does not change your default Kubernetes context. It uses loopback
port 19093 for control; the start command manages port forwarding automatically.
Rerunning setup refreshes the image and restarts the demo workloads, so do it only
between demonstrations. Re-run `uv run bank-fl demo setup` after changing
`k8s/deployment.yaml` to apply those deployment and probe changes to the kind cluster.

## Presentation sequence

1. Run `uv run bank-fl demo status` and explain the coordinator and three banks.
2. Run `uv run bank-fl demo dashboard` in another terminal and open
   `http://127.0.0.1:8765`. In **Live monitor**, select the round count and deadline,
   then click **Start training**. The dashboard polls in the background every five
   seconds; starting a run clears the previously displayed results, and the new run
   appears automatically. The dashboard shows pod readiness/restarts,
   deployments, services, recent Kubernetes events, logs, training attempts, and
   alerts. Kubernetes event timestamps are converted to Singapore Time (SGT),
   including the date. It binds to loopback.
3. Explain a successful commit in **Live monitor**. After several commits, choose a
   bank in the dashboard's **Simulate self-healing** card and click **Delete bank
   pod**. The card tracks the deleted pod name/UID and the replacement pod name/UID
   until it becomes Ready. Alternatively, run
   `uv run bank-fl demo fail --bank bank-3` in another terminal.
4. Identify commits containing the other two banks while the failed bank recovers.
5. Identify a later commit containing the returned bank. Explain that pod readiness
   and useful training participation are distinct measurements.
6. Let training finish and open **Results**. Select the run to inspect its exported
   summary and test evaluation metrics. Results are populated from that run's saved
   `summary.json` and `evaluation.json`; while training is active, they are not
   presented as final metrics.

Use `demo start --rounds 50` if the rehearsal ends before you can trigger a fault
or see the bank rejoin. `--deadline` controls the attempt deadline in seconds and
defaults to 30. A deadline should be chosen from a healthy rehearsal on the same
machine. Do not promise a particular round or recovery time.

`demo fail` defaults to bank 3; `--bank bank-1` or `--bank bank-2` selects another
bank. Only one fault is allowed per run. Keep both commands running until they
finish. Do not interrupt the presentation just to stop the display: stopping the
local streaming process does not guarantee cancellation of server-side training.

## Results and comparisons

The start command exports only the run it submitted, evaluates its checkpoints,
and creates charts. Outputs are under `results/demo`, including the fault record
and a run directory containing `summary.json`, `evaluation.json`, `recovery.json`
(when a fault record exists), `events.jsonl`, checkpoints, and `figures`.

If export or evaluation fails, or the fault measurement finishes after training,
run `uv run bank-fl demo results` to retry. A missing recovery observation is
reported explicitly; do not describe that run as proof of successful rejoin.

The live demo proves observable behaviour, not statistical improvement. Prepare
comparison evidence separately before presenting:

```text
uv run python -m experiments.run --runtime flower --data data/ulb
```

This runs the configured repeated baseline comparisons and creates plots under
`results/study/figures`. These local-process measurements must not be pooled with
Kubernetes measurements as equivalent repeats.

## Troubleshooting

| Symptom | Action |
|---|---|
| Missing kind, kubectl, or Docker | Install the named tool, reopen the terminal, and retry setup |
| Docker connection error | Start Docker Desktop with Linux containers |
| Download rejected | Obtain creditcard.csv from Kaggle, put it in data/raw, rerun setup |
| Pods fail to become Ready | Run demo status; inspect the dedicated cluster using the command below |
| Port 19093 occupied | Stop the process you own that uses it, then retry start |
| No accepted update after replacement | Repeat with more rounds; check the event log |
| Training misses healthy deadlines | Rehearse with a larger --deadline and check Docker resources |
| Failed submission/export | Inspect .demo/session.log and .demo/forward.log; retry demo results |
| Dashboard cannot connect | Confirm setup completed; keep the dashboard on `127.0.0.1` and inspect its Kubernetes-unavailable alert |

```text
kubectl --kubeconfig .demo/kubeconfig --context kind-bank-fl-demo -n bank-fl get pods
```

## Cleanup

Wait for the demo to finish and verify that its results have been exported. Then:

```text
kind delete cluster --name bank-fl-demo
```

This removes the demo cluster and its in-cluster result storage. Exported results
and prepared datasets remain local. Run `demo setup` to recreate the cluster later.
