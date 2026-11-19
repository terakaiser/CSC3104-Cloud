# Resilient Bank Federation
Three simulated banks train one shared fraud-detection model **without sharing
their data**. Each bank runs in its own Kubernetes pod. If one bank fails,
training continues with the other two, and Kubernetes restarts the failed bank
so it can rejoin.

Built with Python, PyTorch, Flower (federated learning), Docker and Kubernetes.

The whole path below (install, setup, one training run with a failure) was
tested from a fresh clone on Windows 11. The times given are from
that test and a slower laptop or internet connection will take longer.

## 1. Install the tools (once)
You need Git and four tools. Install them with one command, then restart your
computer.

**Windows** (PowerShell):
```powershell
"Git.Git", "astral-sh.uv", "Docker.DockerDesktop", "Kubernetes.kubectl", "Kubernetes.kind" | ForEach-Object { winget install --exact --id $_ }
```
**Mac** (Terminal, needs homebrew):
```bash
brew install git uv kubernetes-cli kind && brew install --cask docker-desktop
```
| Tool | What it is for |
|------|----------------|
| uv | Installs the right Python (3.12) and all Python packages for this project |
| Docker Desktop | Builds and runs containers. Give it at least 4 CPUs and 6 GB memory (Settings → Resources) |
| kubectl | Talks to Kubernetes |
| kind | Runs a small Kubernetes cluster inside Docker on your laptop |

## 2. Set up the project (once)
Get the code and go into its folder. Run every later command from this folder:
```powershell
git clone https://github.com/terakaiser/CSC3104-Cloud.git
cd CSC3104-Cloud
```
Then install Python and the packages:
```powershell
uv sync --frozen --extra dev --python 3.12
```
This creates a `.venv` folder with Python 3.12 and the exact package versions
from `uv.lock`. The last lines list the installed packages, ending near
`torch==2.8.0+cpu`.

Optional check that the code works on your machine (about 30 seconds, should end
with `119 passed`):
```powershell
uv run pytest -q
```

## 3. Run it
Start Docker Desktop first and wait until it says the engine is running. Then
run setup (about 3 minutes; the first time can take several minutes longer
because Docker downloads the base images):
```powershell
uv run bank-fl demo setup
```
It is finished when the last line starts with `Ready with 3 banks`.

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
1. Click **Start Training**. The default run is 30 rounds and takes about
   7 minutes (about 13 seconds per round).
2. After a few rounds commit, pick a bank and a failure type in **Simulate
   Self-Healing**, click **Inject Failure**, then click the same button again
   within 4 seconds to confirm (it changes to **Confirm: ...**; if you wait
   longer it resets and nothing happens).
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

To change **how different the banks are**, add `--skew` to setup: `0` gives every
bank the same mix of payments, `1` is the standard split (the default), and higher
values make the banks overlap less. Runs made on a non-standard split are labelled
with their skew in the dashboard.
```powershell
uv run bank-fl demo setup --skew 0
```

After training, let the model check a payment it has never seen. `<run-folder>`
is the inner folder of a run, for example
`results\demo\20261111-162639\20261111T082649-47185598` (see section 4):
```powershell
uv run bank-fl predict <run-folder> --fraud    # a real fraud payment
uv run bank-fl predict <run-folder> --normal   # a normal payment
```

The cluster also retrains on its own every Sunday at 02:00 (Singapore time)
through a Kubernetes CronJob. To start one scheduled run now and follow it:
```powershell
kubectl --kubeconfig .demo/kubeconfig --context kind-bank-fl-demo -n bank-fl create job --from=cronjob/scheduled-training retrain-now
kubectl --kubeconfig .demo/kubeconfig --context kind-bank-fl-demo -n bank-fl logs -f job/retrain-now
```
A scheduled run is 20 rounds and takes about 5 minutes. Don't start a dashboard
or `demo start` run while a scheduled run is training.

## 4. Results
Each demo run creates a folder under `results\demo`, named after the start time,
for example `results\demo\20261111-162639`. Inside it is one folder named after
the run ID (for example `20261111T082649-47185598`) that holds the files below.
The dashboard's **Results** tab shows the same numbers.

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
- **Tests:** run `uv run pytest -q`. `uv run` always uses your latest code.
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