# Report notes (Group 18)

Working notes for the final article (IEEE/ACM, about 3,000 words), the video and
`GROUP18_INSTRUCTIONS.pdf`. Each feature lists **what** it does, **why** we built it,
and the **evidence** we measured. Every number below comes from a run we actually
performed; the run folder or date is given so it can be traced. Do not add numbers
to the report that are not recorded here or in a results folder.

**Keep the evidence.** Each run's core data (events, summary, model versions) is
on the cluster's results volume (`/results` in the coordinator pod; 17 completed
runs from 25 Oct to 10 Nov at the time of writing) and is lost if the kind cluster
is deleted. The laptop-side files (`fault-N.json`, `recovery.json`, `resources.*`,
`evaluation.json`, figures) exist only under `results\demo`. The local folders
for runs before 10 Nov 17:41 were removed, so for those runs the fault, recovery
and resource numbers below are the surviving record. Do not delete `results\demo`
or the cluster again before the report is written; copy both somewhere safe.

**Update 11 Nov:** the cluster was deleted and recreated for the clean-clone
test (Section 3.11). Before that, all 26 runs on its results volume were copied
to the laptop: 18 in `results\cluster-backup-20261110` and the 8 runs from the
evening of 10 Nov in `results\cluster-backup-20261111` (file counts checked
against the cluster). `/results/...` paths in this file now refer to those two
folders. Neither folder is in git.

---

## 1. Positioning (Introduction / Related Work)

- **Contribution:** integration and evaluation, not a new FL algorithm. Non-IID
  fraud learning + quorum- and version-aware round management + Kubernetes client
  recovery, measured under deliberate failures.
- **Why quorums (lecturer question, 27 Oct):** production FL does not wait for every
  client. Google's FL system selects more devices than it needs and closes a round
  once enough report (Bonawitz et al., *Towards Federated Learning at Scale: System
  Design*, SysML 2019). Flower and NVIDIA FLARE expose a "minimum clients" setting
  for the same reason. Quorums are also a standard distributed-systems technique
  for availability (majority quorums in Raft/etcd, Cassandra). Our additions: a
  model-version check so late updates cannot overwrite a newer model, and a grace
  window (Section 3.2) so a quorum does not discard slightly late banks.
- **Honest trade-off:** with only three banks, many systems simply wait for all of
  them. A quorum keeps training going during failures, but slower banks can
  contribute less often, so participation per bank is always reported.
- **FedProx (lecturer question):** FedAvg plus a proximal penalty that keeps each
  bank's local model close to the global model ("FedAvg with a leash"). It targets
  non-IID clients like our banks and tolerates partial local work (Li et al.,
  *Federated Optimization in Heterogeneous Networks*, MLSys 2020).

## 2. Core system (built 11–27 Oct, before the progress presentation)

### 2.0 Design evolution: from Flower's built-in strategy to our own coordinator
- **What:** the first prototype (11 Oct, Chee Yuan) trained three banks with
  Flower's built-in `FedAvg` strategy (a `SynchronousFedAvg` subclass), ran on
  Docker Compose and Kubernetes, and compared logistic-regression and XGBoost
  baselines. On 20–21 Oct the repository was restarted ("Clear repository for a
  fresh start") and rebuilt around our own round coordinator on Flower's
  low-level Message API.
- **Why:** a built-in strategy runs the round for you: it waits for the selected
  clients and silently drops anything late. Our proposal needs the opposite:
  decide per reply whether it is valid, late or stale, close a round on a quorum,
  and let a failed bank rejoin. That logic has to own the round, so Flower was
  reduced to the transport. (Team: confirm this was the reason before quoting it.)
- **Evidence:** `git log` (commits `c1de741` → `54a7a84` → `0c69162`); the current
  code has no strategy class (`app/flower_transport.py`: "No legacy
  NumPyClient/server API is mixed in").

### 2.1 Data pipeline and non-IID bank partitions (`app/download.py`, `app/data.py`)
- **What:** downloads the public ULB credit-card dataset (284,807 payments, 492
  frauds = 0.173%), verifies a pinned SHA-256 checksum, removes 1,081 duplicate
  rows (→ 283,726), applies `log1p` to Amount, and makes a stratified 70/15/15
  train/validation/test split. Each split is divided between the banks by
  transaction-amount rank with overlap, so banks differ but are not disjoint in
  behaviour. Every bank must hold both classes or preparation fails. A
  `manifest.json` records counts, checksum, seed and the class weight.
- **Why:** (i) the checksum and fixed seed mean every teammate and the marker
  train on byte-identical partitions, so results are comparable; (ii) duplicates
  are removed *before* splitting so the same payment cannot be in both train and
  test (leakage); (iii) amount-based allocation simulates retail / mid /
  high-value banks from one public dataset: the only honest way to get non-IID
  "banks" without real bank data; (iv) preparation writes to a temporary folder
  and renames it, so an interrupted run never leaves half-written data; only the
  expected file is extracted from the downloaded archive.
- **Evidence:**

  | | bank-1 | bank-2 | bank-3 |
  |---|---|---|---|
  | Training payments | 53,444 | 91,585 | 53,579 |
  | Training frauds | 93 | 146 | 92 |
  | Mean amount | 22.5 | 54.7 | 211.5 |
  | Test payments / frauds | 11,580 / 21 | 19,460 / 28 | 11,519 / 22 |

  (`data/ulb/manifest.json`.) 10 tests cover reproducibility, disjointness,
  duplicate removal, bad input, checksum mismatch and interrupted preparation
  (`tests/test_data.py`, `tests/test_download.py`).
- **Caveat:** the personas are artificial splits of anonymised PCA features, and
  the strength of the split is set by `skew` (Section 3.8).

### 2.2 Model and local training (`app/model.py`, `app/worker.py`)
- **What:** a 29 → 16 → 1 neural network (497 parameters) trained with SGD
  (learning rate 0.01, batch 256, one local epoch per round) and a fraud-weighted
  binary cross-entropy loss (`pos_weight` ≈ 599). Each bank trains only on its own
  mounted `train.npz` and returns weights, its sample count and metrics.
- **Why:** fraud is 1 in 580, so an unweighted model learns "never fraud"; the
  weight makes one missed fraud cost about as much as 599 false alarms. The model
  is deliberately small: CPU-only, fast enough to repeat many failure
  experiments, and a model update is only 1,988 bytes of tensors (497 float32
  values), so communication cost is negligible and FedAvg averaging is well
  behaved. Local training has a cooperative time budget so a stuck bank cannot
  run forever.
- **Evidence:** saved checkpoints are 2,978 bytes each; quality in Section 4.

### 2.3 Our round coordinator: quorum, deadline and version checks (`app/coordinator.py`, `app/rounds.py`)
- **What:** one loop owns all round state. Each attempt: send the current global
  model (with run ID, attempt, model version and a unique request ID) to the
  available banks; validate every reply; commit when the mode's rule is met;
  save a new model version. Reply validation rejects, with a recorded reason:
  wrong run, **stale** attempt/version, unknown bank, wrong request, duplicate,
  client error, wrong sample count, wrong tensor shape/dtype and non-finite
  values. A missed deadline leaves the model unchanged and retries; three
  consecutive failures stop the run cleanly (`insufficient_quorum`). Startup
  needs only the quorum, so a missing bank cannot block training.
- **Why:** these are the three contributions promised in the proposal.
  *Quorum* keeps training alive when a bank fails; *deadline* stops a straggler
  blocking everyone; *version checking* stops an update trained on an old model
  corrupting a newer one. A single owner of state means no locks and no race
  between two updates. Recording the rejection reason makes the mechanism
  observable rather than a silent drop.
- **Concurrency rules:** a bank never gets a second request while one is
  outstanding (in-flight tracking across attempts); quorum modes dispatch once per
  attempt so a returning bank waits for the next round instead of chasing a
  nearly finished one; messages carry a TTL so abandoned work expires.
- **Evidence:** 27 tests on these rules (`tests/test_rounds.py`,
  `tests/test_coordinator.py`), including a hand-calculated weighted average and a
  simulated clock so timing tests do not depend on machine speed. In real runs
  before the grace window, 14–15 late replies per 30-round run were rejected
  (26 Oct, 5 Nov). Deadline retry seen live on 6 Nov ("Attempt 5 missed its
  deadline - 1/2 required replies; model unchanged", then 15/15 rounds).

### 2.4 Three coordination modes and a centralised baseline
- **What:** `resilient` (ours: quorum + grace), `synchronous` (every bank must
  reply), `timeout` (wait for all or the deadline, need at least the quorum), all
  through the same coordinator; plus `experiments/centralized.py`, which trains
  the same model on the pooled data.
- **Why:** the proposal promises comparison against standard synchronous FL and
  centralised learning. Running every mode through one code path means the only
  difference measured is the waiting rule, not the implementation.
- **Evidence:** mode behaviour is unit-tested; the comparison itself is still to
  run (Section 6).

### 2.5 Flower as transport, and bank identity (`app/flower_transport.py`, `app/server.py`, `app/client.py`)
- **What:** the coordinator runs inside a Flower ServerApp and talks to one
  ClientApp per bank with `push_messages` / `pull_messages`, polling replies
  incrementally. An `identify` query binds each configured bank ID to its current
  Flower node; training replies must come from that node and match the original
  request. When a pod is replaced, the dead node disappears and the replacement
  is identified and bound automatically.
- **Why:** incremental polling is what makes quorum closing and late-reply
  handling possible. The identity binding is what lets a *replacement* pod count
  as the same bank, which is the basis of rejoin after Kubernetes recovery.
- **Design point:** the coordinator depends only on a small `Transport`
  interface, so the same round logic runs on three transports: in-process
  threads (fast tests), local Flower processes, and Flower on Kubernetes.
- **Evidence:** 10 transport tests (`tests/test_flower.py`); rejoin after pod
  replacement measured in Sections 3.5, 3.6 and 4.
- **Caveat:** identity is not cryptographic enrolment; the cluster is trusted.

### 2.6 Containerisation (`Dockerfile`)
- **What:** one image (Python 3.12 slim) runs both roles. Dependencies come from
  a lock file (`uv.lock`) with CPU-only PyTorch; the container runs as non-root
  user 10001. Dependencies are installed before the code is copied.
- **Why:** pinned versions make the marker's image identical to ours; CPU-only
  PyTorch avoids a multi-GB GPU download; non-root is required by the pod
  security settings; the layer order makes rebuilds fast during development.
- **Evidence (25 Oct):** full build 61 s; rebuild after a code change 3 s (the
  dependency layer is cached). Inside the image: Flower 1.22.0, torch 2.8.0+cpu,
  uid 10001.

### 2.7 Kubernetes deployment (`k8s/render.py` → `k8s/deployment.yaml`)
- **What:** a namespace with one coordinator and N bank **Deployments**, a
  **Service** for the coordinator, a **PersistentVolumeClaim** for model versions
  and results, **startup/readiness/liveness gRPC probes**, requests of 250m /
  256 MiB and **limits of 1 CPU / 1 GiB**, per-bank **read-only data mounts**, and
  hardened pods (non-root, no privilege escalation, all capabilities dropped, no
  service-account token). The manifest is generated, for 3 or 5 banks.
- **Why:** each object does one job in the resilience story. Deployments give
  self-healing (a killed bank pod is recreated); the Service gives banks a stable
  name for the coordinator across restarts; probes let Kubernetes tell "started"
  from "ready" from "alive"; limits stop one bank starving the others; separate
  mounts enforce that a bank can only read its own data; the volume keeps model
  versions when the coordinator pod restarts. Generating the manifest keeps the
  3-bank and 5-bank deployments identical apart from the bank count.
- **Evidence:** replacement pod Ready in 3.0–5.3 s in every recorded kill
  (Sections 3.5, 3.6, 4); deployment structure is unit-tested
  (`tests/test_deployment.py`).

### 2.8 Failure injection and recovery measurement (`experiments/fault.py`, `experiments/recovery.py`)
- **What:** two Kubernetes faults: **kill** (delete the bank's pod) and
  **absence** (scale the Deployment to 0 for a set time, then back). Three
  software scenarios built into the run configuration for repeatable tests:
  **slow** (delay one attempt), **stale** (reply with an old version) and
  **unavailable** (the bank never starts). Recovery is measured two ways:
  *fault → replacement pod Ready*, and *fault → first accepted update from work
  dispatched after the pod was Ready*. Unobserved recoveries are marked censored,
  not guessed.
- **Why:** these are the proposal's scenarios (slowed clients, terminated pods,
  temporary unavailability). The second recovery measure exists because a Ready
  pod is not yet a useful bank; counting only work dispatched after readiness
  stops a buffered reply from the *old* pod being mistaken for recovery.
- **Evidence:** 22 Oct: Ready 5.3 s vs useful 61.5 s. 6–10 Nov: Ready 3.0–3.6 s
  vs useful 33–42 s (Sections 3.5, 3.6). 5 tests (`tests/test_fault.py`,
  `tests/test_recovery.py`).

### 2.9 Evaluation and telemetry (`experiments/evaluate.py`, `app/telemetry.py`, `experiments/plot.py`)
- **What:** every run writes `events.jsonl` (every dispatch, reply and decision),
  `rounds.csv`, `summary.json` (status, attempts, successful-round rate,
  participation per bank, rejections by reason, tensor bytes sent/received,
  examples processed) and `run.json` (configuration, dataset manifest, library
  versions, platform). Every committed round is a versioned checkpoint
  (`model-000.npz` …), written atomically and without pickle. Offline evaluation
  scores **every** checkpoint: threshold chosen on validation data (maximum F1),
  then precision, recall, F1, PR-AUC (average precision), ROC-AUC and
  false-positive rate on the test set, overall and per bank.
- **Why:** accuracy is meaningless at 0.17% fraud, so precision/recall/PR-AUC
  are reported. Choosing the threshold on validation data keeps the test set
  untouched. Scoring every version gives the quality-over-time curve and
  implements the "model versions v0, v1, v2…" in the proposal. Logging every
  decision means any number in the report can be recomputed from the run folder.
- **Evidence:** Section 4; per-bank results for the 26 Oct run: bank-1 caught
  16/21 frauds, bank-2 19/28, bank-3 20/22.

### 2.10 Experiment runner and reproducibility (`experiments/run.py`, `experiments/scenarios.yaml`)
- **What:** runs the comparison matrix: 3 seeds × scenarios (healthy, slow,
  unavailable) × modes, plus the centralised baseline, rotating which bank is
  faulty, then draws comparison and systems charts with mean and standard
  deviation. Runs serially to avoid experiments competing for CPU.
- **Why:** one run proves nothing; repeated, seeded runs with a rotated faulty
  bank are what make a comparison defensible. The deadline is frozen from a
  pilot before the study so it cannot be tuned to favour a mode.
- **Evidence:** pilot rounds 22.1–24.9 s → deadline 40 s (Chee Yuan, 5 Nov). The
  full study ran on 10–11 Nov (Section 4.1). The runner now records each
  finished run in `progress.jsonl`, resumes an interrupted study and survives
  a failed run, so hours of earlier runs are never lost; it also runs the
  stale scenario and FedProx.

### 2.11 One-command demo environment (`app/demo.py`)
- **What:** `demo setup` checks tools, prepares data, builds the image, creates a
  dedicated kind cluster (`bank-fl-demo`) with its own kubeconfig, loads the
  image and applies the manifests. `demo start` port-forwards to the coordinator,
  submits the run, streams progress, then exports results, evaluates and plots.
- **Why:** the brief says "it worked at home" is not accepted; one command that
  builds everything from a clean clone is how the marker reproduces our results.
  A dedicated cluster and kubeconfig mean the demo never touches the user's own
  Kubernetes setup.
- **Evidence:** clean-clone setup worked on a second machine (Faizal's desktop,
  5 Nov); full timed clean-clone test on 11 Nov (Section 3.11).

## 3. Features added after the progress presentation, and why

### 3.1 FedProx (`mu` setting) — Chee Yuan, 4–5 Nov
- **What:** `--mu` (dashboard: Algorithm selector, μ = 0 / 0.01 / 0.1 / 1). μ = 0 is
  plain FedAvg. Adds (μ/2)·‖w − w_global‖² to each bank's local loss.
- **Why:** answers the lecturer's question with working code; suited to non-IID banks.
- **Evidence:** a unit test checks that μ = 0 reproduces FedAvg exactly and that
  μ > 0 pulls local weights toward the global model (`tests/test_model.py`). Runs
  with μ = 1 (5 Nov), μ = 0.1 (6 Nov) and μ = 0.01 completed on the cluster; see
  Section 4. The comparison study found no measurable difference from FedAvg (Section 4.1).

### 3.2 Grace window for late banks (`grace`, default 3 s)
- **What:** once 2 of 3 banks reply, the round stays open up to 3 s for the third,
  then closes. It never waits for a bank that was not sent work (e.g. dead).
- **Why:** the third bank was usually only **< 1 s** late, yet its whole update was
  thrown away as stale. Measured before the change: 15 late replies in the 26 Oct
  run (median 0.8 s, max 2.2 s after commit) and 14 in the 5 Nov run (median 0.8 s,
  max 1.4 s).
- **Evidence (20-round runs on the kind cluster, 5 Nov):**

  | | Before (grace 0) | After (grace 3 s) |
  |---|---|---|
  | Rounds with all 3 banks | 7 / 20 | **20 / 20** |
  | Rejected updates | 13 | **0** |
  | Participation (bank-1/2/3) | uneven | **20 / 20 / 20** |
  | Wait after quorum | 0 s | median **0.91 s**, max 2.08 s |
  | Training time | 284.2 s | 296.8 s (+4.5%) |

  Runs: `/results/20261105T161230-770e5e8c` (before) and
  `/results/20261105T161951-b6ede905` (after), on the coordinator's volume.
- **Framing:** "quorum for resilience, grace window for fairness".

### 3.3 Round 1 waits for all banks to connect
- **What:** before round 1, wait up to `grace` for every bank to connect.
- **Why:** pods connect a moment apart; in the 6 Nov dashboard run bank-3 connected
  1.5 s after the others and missed round 1. In a later run bank-2 connected 3 s
  before the others and round 1 still included all three.

### 3.4 Weekly scheduled retraining (Kubernetes CronJob)
- **What:** a CronJob starts a 20-round run every Sunday 02:00 SGT
  (`app/scheduled.py`). `concurrencyPolicy: Forbid` (never two runs at once),
  `backoffLimit: 0` (failures are reported, not hidden), 1-hour time limit.
- **Why (lecturer question: "how often do banks train?"):** fraud labels arrive late
  (chargebacks and investigations take days to weeks), so daily retraining adds
  little newly confirmed fraud; monthly may be too slow as fraud tactics change.
  Weekly is our design choice, with that reasoning, not an industry fact.
- **Evidence:** a manually triggered job completed 20 rounds in about 5 minutes and
  Kubernetes marked it Complete (1/1).
- **Limitation:** bank data is fixed in the prototype; a real deployment would load
  each bank's latest labelled transactions.

### 3.5 Repeated failure injection (chaos testing)
- **What:** any number of bank-pod kills per run, one at a time (the next kill is
  allowed once the previous replacement is Ready). Each kill has its own record
  (`fault-1.json`, …) and its own recovery time in `recovery.json`.
- **Why:** more recovery measurements per run (averages for the report), and two
  banks down close together exercises the deadline/retry safety net. Same idea as
  chaos engineering in industry.
- **Evidence (15-round runs, 6 Nov):**

  | Run | Kill | Pod Ready | Bank contributing again |
  |---|---|---|---|
  | A | bank-3 | 3.6 s | not observed (killed again first) |
  | A | bank-3 | 3.6 s | 42.2 s |
  | A | bank-1 | 3.0 s | 38.2 s |
  | B | bank-1 | 3.3 s | not observed (killed again first) |
  | B | bank-1 | 3.4 s | 40.1 s |
  | B | bank-2 | 3.2 s | 34.3 s |

  Run A: `results/demo/20261106-011319`. Run B: `results/demo/20261106-012912`
  (run B also read the fault files 9,260 times during the kills to stress-test the
  Windows fix). Across all six kills the replacement pod was Ready in 3.0–3.6 s.

  In both runs, two banks down at once caused one attempt to miss its deadline
  ("1/2 required replies; model unchanged"); training retried and completed 15/15.
- **Key insight for the report:** *pod Ready* and *bank useful again* are different
  measurements. In the 6 Nov run the pod was Ready after 4.8 s, but Flower only
  reconnected the bank after 17.7 s, and the first useful update came later still.

### 3.6 Per-pod CPU and memory from Kubernetes (metrics-server)
- **What:** `demo setup` installs metrics-server from a pinned manifest
  (`k8s/metrics-server.yaml`, v0.9.1). Every demo run records each pod's CPU and
  memory to `resources.csv`, with mean/peak per pod in `resources.json` and a
  chart in `figures/resources.png` (kills marked). The dashboard Pods table shows
  live CPU and memory.
- **Why:** the proposal promised CPU/memory utilisation. Before this we only had
  per-process samples reported by the banks themselves; these are the cluster's
  own measurements of whole pods, which is what resource limits are enforced on.
  The manifest is pinned in the repo so setup does not depend on a download URL.
- **Evidence (12-round run with one kill of bank-2, 10 Nov,
  `results/demo/20261110-172302/20261110T092311-873663cd`):**

  | Pod | CPU mean | CPU peak | Memory mean | Memory peak | Limit |
  |---|---|---|---|---|---|
  | bank-1 | 629m | 839m | 235 MiB | 408 MiB | 1000m / 1024 MiB |
  | bank-2 (killed once) | 600m | 841m | 235 MiB | 397 MiB | 1000m / 1024 MiB |
  | bank-3 | 626m | 820m | 247 MiB | 399 MiB | 1000m / 1024 MiB |
  | coordinator | 111m | 349m | 431 MiB | 488 MiB | 1000m / 1024 MiB |

  Idle pods use about 20m CPU and 100–130 MiB. While training, each bank runs at
  about 800m of its 1000m limit; the coordinator's CPU peaks during startup and is
  about 75m between rounds. bank-2's replacement pod was Ready in 3.3 s and the
  bank contributed again 33.2 s after the kill.
- **Caveats:** metrics-server refreshes about every 15 s, so short spikes are
  averaged out and a 3-minute run gives only 11–13 samples per pod. One run on one
  laptop; means include the idle seconds before round 1. CronJob runs are not
  sampled.

### 3.7 Five banks and temporary outages (scaling and a second failure type)
- **What:** `demo setup --banks 5` deploys five bank pods with a majority quorum
  of 3 (three banks: 2). It prepares a separate 5-bank dataset (`data/ulb-5`),
  generates the manifests for that count, removes or adds the extra bank
  Deployments, and tells Start Training and the weekly CronJob the bank count.
  The dashboard draws however many banks are deployed. A second failure type,
  **temporary outage** (`absence`), scales a bank's Deployment to 0 for 20 s and
  back, next to the existing pod **kill**. Both are in the dashboard's "Simulate
  Self-Healing" card and in `demo fail --kind`.
- **Why:** the proposal's evaluation promises "different numbers of participating
  banks" and "temporary client unavailability". Five banks shows the round logic
  is not hard-wired to three and lets a quorum survive *two* missing banks. An
  outage is a harder test than a kill: Kubernetes replaces a killed pod in about
  3 s, so the bank misses little; an offline bank misses whole rounds and has to
  rejoin with a model several versions newer than the one it last saw.
- **Design choice:** kind fixes a node's data mount when the cluster is created.
  To switch bank counts without recreating the cluster (and losing the saved runs
  on its results volume), the other dataset is copied into the node and the
  manifests point at that path. Switching 3 → 5 → 3 keeps the cluster.
- **Evidence (10 Nov, FedAvg, grace 3 s, deadline 30 s):**

  | | 5 banks, one 20 s outage | 3 banks, one pod kill |
  |---|---|---|
  | Run folder (`results/demo/`) | `20261110-180818` | `20261110-181339` |
  | Rounds committed / attempts | 14 / 14 | 8 / 8 |
  | Quorum | 3 of 5 | 2 of 3 |
  | Training time | 206.7 s (about 14 s between commits) | 121.6 s (about 13 s between commits) |
  | Fault → pod Ready | 23.3 s (20 s offline + 3.3 s) | 3.2 s |
  | Fault → bank contributing again | 60.2 s | 30.0 s |
  | Rounds the failed bank missed | 4 (rounds 4–7) | 2 (rounds 3–4) |
  | Participation | 14 / 14 / 14 / 14 / 10 | 6 / 8 / 8 |

  In the 5-bank run every round outside the outage used all five banks; during
  the outage rounds kept committing with four. No attempt missed its deadline.
  Round time with five banks was about the same as with three, because banks
  train in parallel in separate pods (the laptop has 28 CPUs).
- **5-bank partitions (training):** 29,895 / 44,804 / 49,277 / 44,545 / 30,087
  payments with 51 / 82 / 74 / 79 / 45 frauds and mean amounts 22.8 / 26.6 / 57.8
  / 134.0 / 227.6.
- **5-bank quality (one 14-round run, same test set of 71 frauds):** recall 0.746,
  precision 0.815, F1 0.779, AP 0.688; frauds caught per bank 11/12, 7/13, 10/14,
  15/18, 10/14. Fewer training frauds per bank than with three banks; whether
  quality really differs needs the repeated comparison runs.
- **Per-pod CPU in the 5-bank run:** bank means 540–669m, peaks 836–915m (limit
  1000m); coordinator mean 139m. bank-5's mean is lowest because it was offline
  for part of the run.
- **Caveats:** one run each; bank counts are limited to 3 and 5; the 5-bank
  dataset copy inside the node is lost if the kind cluster is recreated (setup
  copies it again).

### 3.8 Adjustable bank heterogeneity (`skew`) and research question 1
- **What:** a `--skew` setting on data preparation (`setup-data`, `prepare`,
  `demo setup --skew`). Each payment goes to a bank with probability proportional
  to its amount-rank preference raised to the power `skew`: 0 gives identical
  banks (IID), 1 is the original split (reproduced byte for byte), higher values
  make banks overlap less. Each skew is prepared into its own folder and can be
  deployed to the same cluster; runs are labelled with their skew.
- **Why:** research question 1 asks how performance changes *as non-IID
  heterogeneity increases*. Before this the heterogeneity was a constant in the
  code, so the question could not be tested. All skew levels share the same
  train/validation/test membership, so they share one test set and one
  centralised baseline, which makes the comparison fair.
- **Design note:** the first version narrowed each bank's Gaussian preference.
  Measuring it showed banks became *less* different at high skew (amount-mean
  ratio 5.3 at skew 3 vs 7.5 at skew 1), because the split's fixed overlap floor
  dominates between bank centres. An exponent on the whole preference is
  monotonic (ratios 1.5, 7.5, 27.5, 42.4 at skew 0, 1, 2, 4 on the test data).
- **Evidence (10 Nov, kind cluster, 3 banks, FedAvg unless stated, 20 rounds,
  seed 42, grace 3 s; one run each):**

  | Skew | Mean amount per bank | Recall | Precision | F1 | AP | AP after round 2 | Run (`results/demo/`) |
  |---|---|---|---|---|---|---|---|
  | 0 (identical) | 88.5 / 88.8 / 87.7 | 0.775 | 0.846 | 0.809 | 0.708 | 0.677 | `20261110-184635` |
  | 1 (standard) | 22.5 / 54.7 / 211.5 | 0.775 | 0.833 | 0.803 | 0.703 | 0.654 | `20261110-190804` |
  | 2 | 5.4 / 37.3 / 270.3 | 0.747 | 0.841 | 0.791 | 0.712 | 0.650 | `20261110-185212` |
  | 4 | 2.5 / 30.1 / 290.2 | 0.747 | 0.855 | 0.797 | 0.700 | 0.642 | `20261110-185834` |
  | 4, FedProx μ=0.1 | 2.5 / 30.1 / 290.2 | 0.747 | 0.855 | 0.797 | 0.702 | 0.648 | `20261110-190249` |
  | Centralised (pooled data, 20 epochs) | n/a | 0.775 | 0.833 | 0.803 | 0.725 | 0.688 | `results/centralized/centralized-b9b389dce7` |

  Every federated run committed 20/20 rounds with all three banks in every round
  (participation 20 / 20 / 20, no rejected updates), in 232–253 s.
- **What the numbers say (answer to RQ1 so far):**
  - Final quality is **essentially flat** as banks go from identical to having
    mean amounts 116 times apart (2.5 vs 290.2). Recall moves from 0.775 to 0.747,
    which is 55 vs 53 of 71 frauds: two frauds, within what one run can resolve.
  - Federated training at the standard split matches the centralised model on
    recall, precision and F1 (identical confusion counts: 55 caught, 11 false
    alarms) and is slightly behind on AP (0.703 vs 0.725).
  - The one consistent trend is **early convergence**: AP after two rounds falls
    steadily with skew (0.677 → 0.654 → 0.650 → 0.642), so more different banks
    learn a little more slowly at first, then catch up by about round 10.
  - FedProx (μ = 0.1) at the highest skew gave the same final confusion counts
    as FedAvg, so it had nothing to fix here.
- **Why the effect is small (interpretation, to state as such):** this skew acts
  on one of 29 input features and leaves each bank's fraud rate unchanged; banks
  do one local epoch per round with a small model, so local models drift little
  before averaging. Skew in the *label* distribution (banks with very different
  fraud rates) is the harder case in the literature and is not tested here.
- **Caveats:** one seed per setting; 71 test frauds; per-bank test results are
  not comparable across skew levels because the test payments are also
  re-allocated between banks. The repeated comparison study should confirm the
  early-convergence trend before the report claims it.

### 3.9 Robustness fixes found by testing
| Problem | Cause | Fix |
|---|---|---|
| Malformed bank metrics could crash a run | NaN / wrong types reached the event log | Rejected as an invalid reply (Chee Yuan) |
| Synchronous baseline looked worse than it is | A bank freed mid-attempt had to sit out | Synchronous mode re-dispatches to it (Chee Yuan) |
| Training could not start after a CronJob run | Finished job pods are never "Ready" and the start-up wait covered all pods | Wait only for the 4 workload pods; dashboard hides finished job pods |
| Killing the same bank twice could hang | A pod still terminating was mistaken for the replacement | Ignore pods with a deletion timestamp |
| "Failure simulation failed" on Windows | Windows cannot replace a file another process (the dashboard) has open | Retry the atomic replace for up to 2 s; show the real error |
| Dashboard Training card said "0 committed" for a whole run (found in the 11 Nov clean-clone test) | The card read the run summary, which is only written when the run ends | Count the committed events while the run is active (checked live: "2 committed · attempt 3") |

### 3.10 Operations and tooling
- **Dashboard** (`uv run bank-fl demo dashboard`, Charmain and Yee, 26–27 Oct):
  - *What:* a local web page served by the CLI. Live Federation view (bank states,
    which banks each round used, global model version), Start Training (rounds,
    deadline, FedAvg/FedProx), Delete Bank Pod (two clicks to confirm), pods with
    live CPU/memory, deployments, the latest Kubernetes events in Singapore time,
    alerts (pods not ready, restarts, missed deadlines, rejected replies, uneven
    participation), training progress, and a Results tab with test metrics per
    run and per bank. Services, the raw event stream and pod logs sit under
    "Show technical details" (closed by default, 5 Nov).
  - *Why:* one screen shows Kubernetes self-healing and the FL round logic side
    by side, which is the story of the project. Present it as Kubernetes
    observability and operations, not as a UI feature (the brief does not require
    a UI). The collapsed section keeps the demo readable while leaving the
    diagnostics one click away.
  - *Safety:* it listens on 127.0.0.1 only; actions must come from the same local
    page (Origin check), accept only small JSON bodies and validated values, and
    it reuses the tested `demo start` / `demo fail` commands instead of duplicating
    their logic.
  - *Evidence:* 11 dashboard tests (`tests/test_dashboard.py`); checked in a
    browser after each change (5, 6 and 10 Nov).
- **Live log lines** (26 Oct): the coordinator logs "bank-3 went offline - training
  continues without it" and "bank-3 is back online". *Why:* with a quorum of 2,
  rounds often had only two banks even when healthy, so a kill did not stand out.
  *Evidence:* 12-round cluster run on 26 Oct: offline at 65.9 s, back at 77.3 s,
  contributing again 62.8 s after the kill.
- **`bank-fl predict`** (25 Oct) scores one held-out test payment with the final
  model and shows the real answer. *Why:* a concrete moment for demos; the real
  measurement stays the full test-set evaluation. *Evidence:* 4 tests; 4 of 4
  spot checks correct on the 25 Oct run (not a statistic).
- **README** rewritten as six numbered steps with one-line installs for Windows
  and macOS (25 Oct). *Why:* a marker or new teammate should be able to run the
  system without reading the design documents.
- **Docker image:** dependencies are installed before the code is copied, so a
  code-only rebuild takes about 3 s instead of reinstalling all packages.
- **Experiment deadline** frozen at 40 s from a healthy pilot (rounds 22.1–24.9 s
  locally) before any comparison runs (Chee Yuan).
- **Quality checks:** 119 automated tests across 19 files (coordinator and round
  rules 27, configuration 12, demo commands 13, dashboard 12, bank heterogeneity 9, study runner 2, Flower transport
  10, data and download 10, resources 4, prediction 4, recovery 3, fault 2,
  scheduling 2, deployment 2, model/FedProx 1, evaluation 1); `ruff` lint and
  formatting enforced. About 4,100 lines of application code and 1,570 lines of
  tests. *Why:* the brief requires tested code; the tests are also how each
  resilience rule is shown to hold without depending on timing luck.

### 3.11 Clean-clone test and testing instructions (11 Nov)
- **What:** the repository was cloned from GitHub into a new empty folder
  (`Desktop\G18-clean-test`, commit `0831c3a`), the existing kind cluster was
  deleted, and only the README was followed: install packages, `demo setup`,
  dashboard, Start Training, inject a failure, read the results, plus the
  tests, `demo status`, `predict` and the manual CronJob run. The result is
  written up for the marker as `docs/GROUP18_INSTRUCTIONS.pdf` (4 pages:
  requirements, 11 steps with expected output and time, optional tests, common
  problems, what each step demonstrates).
- **Why:** the brief requires testing instructions and says "it worked at home"
  is not accepted. A fresh folder and a fresh cluster is the closest we can get
  to the marker's machine.
- **Evidence (Windows 11, 28 CPU threads, 32 GB; Docker engine 29.8.2, kind
  0.33.0, kubectl 1.36.1, uv 0.13.5). Every step worked first time.**

  | Step | Time | Result |
  |---|---|---|
  | `git clone` | 2 s | — |
  | `uv sync --frozen --extra dev --python 3.12` (empty package cache) | 70 s | 61 packages; torch alone is a 591 MiB download |
  | `uv run pytest -q` | 30 s | 119 passed |
  | `uv run bank-fl demo setup` (new cluster) | 152 s | data ready at 19 s, image built at 23 s, cluster up at 57 s, image loaded at 92 s, pods rolled out at 126 s, metrics-server at 152 s |
  | Same, from the real repo afterwards | 134 s | — |
  | Dashboard run, 30 rounds, one kill of bank-3 | 407.0 s training | 30/30 rounds; participation 30 / 30 / 28; 1 rejected reply (`client_error`, the killed pod's request) |
  | Kill → replacement pod Ready | 3.8 s | — |
  | Kill → bank contributing again | 28.2 s | — |
  | Final model on the test set | — | recall 0.789, precision 0.836, F1 0.812, AP 0.717 (56 of 71 frauds, 11 false alarms) |
  | Manual CronJob run (`retrain-now`) | 279 s | 20 rounds, job Complete 1/1 |
  | `predict --fraud` / `--normal` | seconds | both correct (2 spot checks, not a statistic) |

  Run folder (copied into the real repo): `results/demo/20261111-162639`.
- **Limits of the test:** the tools were already installed, so Step 1 (winget)
  was not timed, only checked that the package IDs exist. Docker's build cache
  and the kind node image were already on the laptop, so the 152 s does not
  include a first image build (61 s measured on 25 Oct) or the image
  downloads. Windows only; the Mac commands are untested by us.
- **Problems found and fixed:**

  | Problem | Fix |
  |---|---|
  | **The GitHub repository is private**: an anonymous `git ls-remote` is refused, so the marker cannot clone it | **Open: the owner (terakaiser) must make it public or give the lecturer access before submission** |
  | README never said how to get the code, and Git was not in the install line | Added `git clone` + `cd`, and Git to both install commands |
  | "Click again to confirm" did not say the confirm click must come within 4 s; a slow second click silently does nothing | README and instructions now say so |
  | No time estimates anywhere | Added measured times for sync, setup, a run and a scheduled run |
  | `predict <results-folder>` fails with a confusing "run evaluate first" if given the outer start-time folder | README now explains the inner run-ID folder, with an example |
  | README said "Tests: nothing to do" and never gave the test command | Added `uv run pytest -q` and the expected `119 passed` |
  | Setup's last line said to run `demo start`, while the README says to open the dashboard | Message now says `demo dashboard` |
  | Dashboard showed "0 committed" during a run | Fixed (Section 3.9) |

### 3.12 Final article draft (12 Nov)
- **What:** first full draft of the article, written into the group's Google Doc
  ("Groupd_18 Final Report") in IEEE conference layout: Letter page, two
  columns, Times New Roman 10 pt, abstract of 193 words, about 3,400 words of
  text, 16 references, two tables and three figures. Sections: Introduction,
  System Design, Implementation, Evaluation, Related Work, Conclusion.
- **Figures** (in `docs/figures/`, drawn from the results folders, no typed
  numbers): `fig1-architecture.png` (system diagram), `fig2-time-rounds.png`
  (the Section 4.1 study, one-column version of the article chart) and
  `fig3-skew-ap.png` (average precision per round for skew 0, 1, 2, 4, from the
  four runs in Section 3.8, with the centralised result as a reference line).
- **Why these choices:** the brief gives most weight to the originality argument
  and the quantitative evaluation, so the article states the contribution as
  integration plus measurement, compares against six groups of related work, and
  reports every claim with a number and its spread.
- **Numbers derived for the article (from runs already recorded above):**
  pod Ready after a deletion, 9 kills on the cluster (six on 6 Nov, two on
  10 Nov, one on 11 Nov): 3.0–3.8 s, mean 3.4 s. Bank contributing again, 7
  observed (two censored): 28.2–42.2 s, mean 35.2 s.
- **To check before submission:**
  - The 16 references were written from memory. Check authors, venue, year and
    pages of each one against Google Scholar. The proposal's fourth reference
    (loss-aware weighted aggregation, 2026) is not cited because its details
    are unknown.
  - Section II-C says Flower's built-in strategies drop late results without
    recording a reason, and Section V says Micro-FL's evaluation assumes working
    clients (as in our proposal). The team should confirm both against the
    sources.
  - The author line and affiliation are taken from the proposal; adjust to what
    the lecturer expects.
  - The three figure images must be inserted by hand at the yellow placeholder
    lines (the Docs connector cannot upload local images). Final length must
    stay within 6 pages after that.

## 4. Results to report (Evaluation)

The table below lists single cluster runs. The repeated comparison is in Section 4.1.

| Run (folder) | Algorithm | Rounds | Recall | Precision | F1 | AP |
|---|---|---|---|---|---|---|
| 22 Oct (`20261022T142541-d995d893`) | FedAvg | 30 | 0.775 | 0.846 | 0.809 | 0.726 |
| 26 Oct (`20261026T132412-6cf831b6`) | FedAvg | 30 | 0.775 | 0.797 | 0.786 | 0.706 |
| 5 Nov (`20261105T125505-3e6d884f`) | FedProx μ=1 | 30 | 0.746 | 0.828 | 0.785 | 0.700 |
| 6 Nov (`20261105T164748-296d386c`) | FedProx μ=0.1, grace 3 s | 20 | 0.789 | 0.789 | 0.789 | 0.707 |
| 10 Nov (`20261110-190804`) | FedAvg, grace 3 s | 20 | 0.775 | 0.833 | 0.803 | 0.703 |
| 10 Nov (`centralized-b9b389dce7`) | Centralised baseline (pooled data) | 20 epochs | 0.775 | 0.833 | 0.803 | 0.725 |

- Test set: 42,559 payments, 71 frauds, so one fraud changes recall by about 1.4%.
- Most learning happens in the first ~10 rounds (26 Oct run: recall 0.75 after
  round 1, 0.79 after round 10, 0.77 after round 30).
- 22 Oct run recovery: replacement pod Ready in 5.3 s, first accepted update 61.5 s
  after the fault; participation 28 / 16 / 22 (before the grace window).

### 4.1 Comparison study (research question 2) — 10–11 Nov

- **What was run:** `python -m experiments.run --runtime flower --data data/ulb
  --output results/study --scenarios healthy slow unavailable stale`. 36 runs:
  3 seeds (42, 43, 44) × 12 configurations, 20 rounds each, deadline 40 s, grace
  3 s, 3 banks at the standard split (skew 1). The faulty bank rotates with the
  seed (bank-1, bank-2, bank-3). Real Flower processes on one laptop (one
  SuperLink, three SuperNodes), **not** the Kubernetes cluster.
- **Scenarios:** *healthy* (no fault); *slow* (one bank delays its round-2 reply
  by 45 s, longer than the deadline); *unavailable* (one bank never connects);
  *stale* (one bank's round-2 reply arrives after the model has moved on).
- **Why:** research question 2 asks whether the resilient coordinator keeps
  training through faults at no cost to model quality, compared with waiting
  for everyone (synchronous) and with waiting for the deadline (timeout).
- **Results (mean ± standard deviation over 3 seeds):**

  | Scenario | Mode | Rounds done | Lost attempts | Training time (s) | Faulty bank's rounds | Recall | Precision | F1 | AP |
  |---|---|---|---|---|---|---|---|---|---|
  | — | Centralised (pooled data) | 20 epochs | — | 9.6 ± 0.5 | — | 0.770 ± 0.008 | 0.828 ± 0.009 | 0.798 ± 0.008 | 0.706 ± 0.016 |
  | Healthy | Synchronous | 20 | 0 | 218.6 ± 9.2 | 20 | 0.779 ± 0.008 | 0.806 ± 0.024 | 0.792 ± 0.009 | 0.703 ± 0.007 |
  | Healthy | Resilient (FedAvg) | 20 | 0 | 221.1 ± 9.7 | 20 | 0.779 ± 0.008 | 0.806 ± 0.024 | 0.792 ± 0.009 | 0.703 ± 0.007 |
  | Healthy | Resilient (FedProx μ=0.1) | 20 | 0 | 210.7 ± 20.4 | 20 | 0.784 ± 0.008 | 0.792 ± 0.027 | 0.788 ± 0.016 | 0.703 ± 0.012 |
  | Healthy | Timeout | 20 | 0 | 210.1 ± 19.9 | 20 | 0.779 ± 0.008 | 0.806 ± 0.024 | 0.792 ± 0.009 | 0.703 ± 0.007 |
  | Slow | Synchronous | 20 | 1 | 256.0 ± 16.2 | 20 | 0.789 ± 0.000 | 0.801 ± 0.031 | 0.795 ± 0.015 | 0.707 ± 0.003 |
  | Slow | Resilient | 20 | 0 | 204.6 ± 15.5 | 13.7 ± 0.6 | 0.779 ± 0.008 | 0.784 ± 0.028 | 0.781 ± 0.015 | 0.699 ± 0.013 |
  | Slow | Timeout | 20 | 0 | 286.3 ± 29.5 | 18 | 0.784 ± 0.008 | 0.792 ± 0.016 | 0.788 ± 0.004 | 0.704 ± 0.006 |
  | Unavailable | Synchronous | **0** (never starts) | — | gives up after 90 s | 0 | no model | no model | no model | no model |
  | Unavailable | Resilient | 20 | 0 | 184.8 ± 13.5 | 0 | 0.775 ± 0.014 | 0.798 ± 0.027 | 0.786 ± 0.007 | 0.694 ± 0.012 |
  | Stale | Synchronous | 20 | 1 | 240.3 ± 21.3 | 20 | 0.789 ± 0.000 | 0.801 ± 0.031 | 0.795 ± 0.015 | 0.707 ± 0.003 |
  | Stale | Resilient | 20 | 0 | 208.8 ± 17.7 | 19 | 0.779 ± 0.008 | 0.806 ± 0.024 | 0.792 ± 0.012 | 0.701 ± 0.010 |

  Figures: `results/study/figures/comparison.png` and `systems.png` (the axis
  labels are crowded with 12 configurations). **Article figure:**
  `results/study/figures/article-time-rounds.png` (and `.pdf`), drawn on 11 Nov
  by `python -m experiments.study_chart results/study`. Two panels, training
  time and rounds completed, grouped by scenario with one bar per mode
  (synchronous, timeout, resilient). It reads each run's `summary.json` through
  `progress.jsonl`, so no number is typed by hand; the bars match the table
  above (219 / 210 / 221, 256 / 286 / 205, 240 / 209, 90 "gave up" / 185).
  FedProx and the centralised baseline are left out to keep it readable, and
  the two combinations the study did not run (timeout with a stale update or a
  missing bank) are marked "not run". Raw list of runs:
  `results/study/progress.jsonl`.
- **What the numbers say (answer to RQ2):**
  - **A missing bank stops synchronous training completely.** In all 3 seeds it
    never started (0 rounds, gave up after the 90 s startup limit). Resilient
    finished 20/20 rounds with the other two banks in every seed, and its
    quality (F1 0.786 ± 0.007, AP 0.694 ± 0.012) is within one standard
    deviation of the healthy runs. This is the strongest result in the project.
  - **A slow bank costs resilient mode nothing in time.** Round 2 took
    11.0–13.0 s in resilient mode, against a full 40 s lost attempt in
    synchronous mode and two 40 s rounds in timeout mode. Total time: resilient
    204.6 s, synchronous 256.0 s (+25%), timeout 286.3 s (+40%).
  - **The cost of resilience is participation, not accuracy.** One 45 s delay
    kept the slow bank out of 6–7 of 20 rounds in resilient mode (13, 14, 14
    rounds), because its late reply is rejected as stale and it rejoins at the
    next round. Timeout mode lost it for 2 rounds; synchronous for none. Final
    quality did not measurably suffer (F1 0.781 ± 0.015 vs 0.795 ± 0.015; the
    ranges overlap). Report this trade-off openly: it is the fairness
    limitation already noted in `docs/design.md`.
  - **When nothing fails, the mode does not matter.** Healthy synchronous,
    resilient and timeout runs gave identical fraud results for each seed (same
    caught frauds and false alarms: 55/11, 55/14, 56/15), because with the grace
    window all three banks are in every round. Times differ by less than the
    spread between seeds.
  - **Stale updates are rejected safely.** Exactly one stale reply was rejected
    in every stale and slow run, and no run aggregated one. Synchronous pays one
    lost 40 s attempt for it; resilient pays nothing.
  - **Federated matches centralised.** Healthy federated F1 0.792 ± 0.009 and
    AP 0.703 ± 0.007 against centralised 0.798 ± 0.008 and 0.706 ± 0.016. The
    difference is smaller than the spread between seeds. Centralised is far
    faster (about 10 s) but needs all banks' data in one place, which is the
    thing federated learning avoids.
  - **FedProx (μ = 0.1) made no measurable difference** to FedAvg at the
    standard split: AP 0.703 ± 0.012 vs 0.703 ± 0.007, F1 0.788 vs 0.792. It
    remains a setting, not a claimed improvement (consistent with Section 3.8).
- **A disturbance, reported for honesty:** in the first pass, four consecutive
  seed-44 runs between 00:50 and 01:10 on 11 Nov stalled: in two no bank
  connected within 90 s, and in two all three banks went silent together from
  round 8, including a *healthy* run. Every run before and after was normal,
  so this was the laptop, not the algorithm; the cause was not identified (no
  sleep event in the Windows log). Those four runs were repeated and completed
  normally; the table uses the repeats. The originals are kept and listed in
  `results/study/disturbed.jsonl`, and the untouched first-pass list is
  `results/study/progress-first-pass.jsonl`. Useful side note: in the stalled
  runs the coordinator stopped cleanly with `insufficient_quorum` after three
  failed attempts instead of hanging.
- **Caveats:** 3 seeds; 71 test frauds, so one fraud is 1.4% of recall; local
  processes with no CPU limits, so rounds are about 10 s here against about
  12 s on the cluster and absolute times are not comparable with the cluster
  runs; one fault per run at a fixed round; the faults are injected by the
  harness (a delay, an absent process), while pod deletion and outages are
  measured separately on Kubernetes (Sections 3.5 and 3.7).

## 5. Limitations (state these explicitly)

- Simulated banks from one public dataset; bank "personas" are amount-based splits.
- One coordinator, no failover; local trusted kind cluster; insecure gRPC inside it.
- Keeping data local is not a formal privacy guarantee (no secure aggregation or
  differential privacy); model updates can leak some information.
- Scheduled runs and manual demo runs do not coordinate; do not overlap them.
- Recovery timings depend on synchronized clocks and on laptop load.

## 6. Still to do before 15 Nov

| Item | Purpose |
|---|---|
| Make the GitHub repository public (or give the lecturer access) | The marker cannot clone a private repository (Section 3.11) |
| Progress deck slide 11 still mentions an AWS EKS run | The lecturer said local hosting is fine; do not repeat the EKS claim in the video |
| Article (about 3,000 words, max 6 pages, IEEE/ACM) and 10–15 minute video | Required submissions, due 23:59 Sun 15 Nov |

Done: clean-clone test and `docs/GROUP18_INSTRUCTIONS.pdf` (11 Nov, Section 3.11).

## 7. Who built what (from the git history; map usernames to real names)

| Period | Git author | Work |
|---|---|---|
| 11 Oct | CheeYuan | First prototype: data loading, models, Flower FedAvg, Docker, Kubernetes |
| 20–22 Oct | terakaiser | Redesign: coordinator and round rules, Flower transport, experiments, evaluation, fault tracking, CLI, Docker/Kubernetes deployment, documentation |
| 22–24 Oct | CheeYuan | Clean-up, README, shared functions |
| 25 Oct – 10 Nov | Faiz0909 | Docker layer caching, README, `predict`, offline/online logging, dashboard clean-up, CronJob, grace window, startup fixes, repeated kills, Windows file fix, per-pod metrics, report notes |
| 26–27 Oct | TanJiaYiCharmain, TheYeeboii | Dashboard (first version, self-healing simulation, redesign) |
| 26–27 Oct | Yew Wei Song | Reviewed and merged the dashboard pull requests |
| 4–5 Nov | Chin Chee Yuan | Malformed-metrics fix, synchronous re-dispatch, FedProx (code, config, dashboard), frozen experiment deadline |

Use each person's real contribution in the report, video and peer evaluation.
