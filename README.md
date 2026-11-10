# Resilient Bank Federation
Three simulated banks train one shared fraud-detection model **without sharing
their data**. Each bank runs in its own Kubernetes pod. If one bank fails,
training continues with the other two, and Kubernetes restarts the failed bank
so it can rejoin.

Built with Python, PyTorch, Flower (federated learning), Docker and Kubernetes.

## 1. Install the tools (once)
You need four tools. Install them with one command, then restart machine.

**Windows** (PowerShell):
```powershell
"astral-sh.uv", "Docker.DockerDesktop", "Kubernetes.kubectl", "Kubernetes.kind" | ForEach-Object { winget install --exact --id $_ }
```
**Mac** (Terminal, needs [Homebrew](https://brew.sh)):
```bash
brew install uv kubernetes-cli kind && brew install --cask docker-desktop
```
| Tool | What it is for |
|------|----------------|
| uv | Installs the right Python (3.12) and all Python packages for this project |
| Docker Desktop | Builds and runs containers. Give it at least 4 CPUs and 6 GB memory (Settings → Resources) |
| kubectl | Talks to Kubernetes |
| kind | Runs a small Kubernetes cluster inside Docker on your laptop |

## 2. Set up the project (once)
From the repository folder:
```powershell
uv sync --frozen --extra dev --python 3.12
```
This creates a `.venv` folder with Python 3.12 and the exact package versions
from `uv.lock`.

## 3. Run it
Start Docker Desktop first. Then run setup:
```powershell
uv run bank-fl demo setup
```
Setup downloads the public Kaggle credit-card fraud dataset into `data\raw`,
splits it into three banks under `data\ulb`, builds the Docker image and creates
the Kubernetes cluster. If the download is blocked, download `creditcard.csv`
from the [Kaggle dataset page](https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud),
put it in `data\raw`, and run setup again.

Then open the dashboard. This is the only terminal you need:
```powershell
uv run bank-fl demo dashboard
```
It opens <http://127.0.0.1:8765> in your browser. In **Live Monitor**:
1. Click **Start Training**.
2. After a few rounds commit, pick a bank and a failure type in **Simulate
   Self-Healing**, click **Inject Failure**, then click again to confirm.
   *Delete pod* kills the bank's pod (Kubernetes recreates it in seconds);
   *Offline for 20 s* is a temporary outage. You can inject more failures in the
   same run, one at a time.
3. Watch the Live Federation banner: **bank fails (red) → training continues →
   bank rejoins (green).**
4. Open **Results** after training finishes.

Keep the dashboard command running while you use it. Without the dashboard, run
`uv run bank-fl demo start` in one terminal and `uv run bank-fl demo fail` in a
second terminal.

Other demo commands:
```powershell
uv run bank-fl demo status              # show the pods
uv run bank-fl demo start --rounds 50   # longer run, more time to see the rejoin
uv run bank-fl demo results             # retry exporting results if it failed
```

To run with **five banks** (a round then needs 3 of 5), stop the dashboard, run
setup with `--banks 5`, and open the dashboard again. Run plain `demo setup` to
go back to three. Switching keeps the cluster and its saved results.
```powershell
uv run bank-fl demo setup --banks 5
```

After training, let the model check a payment it has never seen:
```powershell
uv run bank-fl predict <results-folder> --fraud    # a real fraud payment
uv run bank-fl predict <results-folder> --normal   # a normal payment
```

The cluster also retrains on its own every Sunday at 02:00 (Singapore time)
through a Kubernetes CronJob. To start one scheduled run now and follow it:
```powershell
kubectl --kubeconfig .demo/kubeconfig --context kind-bank-fl-demo -n bank-fl create job --from=cronjob/scheduled-training retrain-now
kubectl --kubeconfig .demo/kubeconfig --context kind-bank-fl-demo -n bank-fl logs -f job/retrain-now
```
Don't start a dashboard or `demo start` run while a scheduled run is training.

## 4. Results
Each demo run creates a folder under `results\demo`:

| File | What it shows |
|------|---------------|
| `figures\comparison.png` | Round times and fraud-detection quality over time |
| `figures\systems.png` | Bar charts comparing configurations (only drawn when several runs are plotted together, e.g. the comparison study) |
| `summary.json` | Rounds completed, how often each bank took part, rejected updates |
| `evaluation.json` | Precision, recall, F1, PR-AUC, ROC-AUC, false-positive rate |
| `recovery.json` | Seconds until the failed bank contributed again (demo only) |
| `figures\resources.png` | Each pod's CPU and memory during the run, with kills marked |
| `resources.json`, `resources.csv` | Mean and peak CPU/memory per pod, from Kubernetes metrics-server |
| `rounds.csv`, `events.jsonl` | Raw per-round logs |
| `model-000.npz`, `model-001.npz`, ... | The saved global model after each round |

## 5. After you change the code
- **Tests:** nothing to do. `uv run` always uses your latest code.
- **Kubernetes demo:** run `uv run bank-fl demo setup` again. It rebuilds
  the image (a few seconds when only code changed) and restarts the pods.
  Do not run it while a demo is training.
- **Added a Python package to `pyproject.toml`:** run
  `uv sync --extra dev --python 3.12` first, then `demo setup`.

## 6. Stop or clean up
You can leave the cluster in place between work sessions. Quit Docker Desktop to
free memory, and the cluster starts again with Docker.
To remove the cluster completely (your `data` and `results` folders are kept):
```powershell
kind delete cluster --name bank-fl-demo
```