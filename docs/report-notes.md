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
  the strength of the split is fixed (see Section 6, `--skew`).

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
  study itself is still to run (Section 6).

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
  5 Nov); the full instructions test is still to do (Section 6).

## 3. Features added after the progress presentation, and why

### 3.1 FedProx (`mu` setting) — Chee Yuan, 4–5 Nov
- **What:** `--mu` (dashboard: Algorithm selector, μ = 0 / 0.01 / 0.1 / 1). μ = 0 is
  plain FedAvg. Adds (μ/2)·‖w − w_global‖² to each bank's local loss.
- **Why:** answers the lecturer's question with working code; suited to non-IID banks.
- **Evidence:** a unit test checks that μ = 0 reproduces FedAvg exactly and that
  μ > 0 pulls local weights toward the global model (`tests/test_model.py`). Runs
  with μ = 1 (5 Nov), μ = 0.1 (6 Nov) and μ = 0.01 completed on the cluster; see
  Section 4. Whether it improves quality is for the comparison study to answer.

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

### 3.7 Robustness fixes found by testing
| Problem | Cause | Fix |
|---|---|---|
| Malformed bank metrics could crash a run | NaN / wrong types reached the event log | Rejected as an invalid reply (Chee Yuan) |
| Synchronous baseline looked worse than it is | A bank freed mid-attempt had to sit out | Synchronous mode re-dispatches to it (Chee Yuan) |
| Training could not start after a CronJob run | Finished job pods are never "Ready" and the start-up wait covered all pods | Wait only for the 4 workload pods; dashboard hides finished job pods |
| Killing the same bank twice could hang | A pod still terminating was mistaken for the replacement | Ignore pods with a deletion timestamp |
| "Failure simulation failed" on Windows | Windows cannot replace a file another process (the dashboard) has open | Retry the atomic replace for up to 2 s; show the real error |

### 3.8 Operations and tooling
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
- **Quality checks:** 101 automated tests across 16 files (coordinator and round
  rules 27, configuration 12, demo commands 12, dashboard 11, Flower transport
  10, data and download 10, resources 4, prediction 4, recovery 3, fault 2,
  scheduling 2, deployment 2, model/FedProx 1, evaluation 1); `ruff` lint and
  formatting enforced. About 4,100 lines of application code and 1,570 lines of
  tests. *Why:* the brief requires tested code; the tests are also how each
  resilience rule is shown to hold without depending on timing luck.

## 4. Results to report (Evaluation)

Single runs; repeated runs are still needed before claiming differences.

| Run (folder) | Algorithm | Rounds | Recall | Precision | F1 | AP |
|---|---|---|---|---|---|---|
| 22 Oct (`20261022T142541-d995d893`) | FedAvg | 30 | 0.775 | 0.846 | 0.809 | 0.726 |
| 26 Oct (`20261026T132412-6cf831b6`) | FedAvg | 30 | 0.775 | 0.797 | 0.786 | 0.706 |
| 5 Nov (`20261105T125505-3e6d884f`) | FedProx μ=1 | 30 | 0.746 | 0.828 | 0.785 | 0.700 |
| 6 Nov (`20261105T164748-296d386c`) | FedProx μ=0.1, grace 3 s | 20 | 0.789 | 0.789 | 0.789 | 0.707 |

- Test set: 42,559 payments, 71 frauds, so one fraud changes recall by about 1.4%.
- Most learning happens in the first ~10 rounds (26 Oct run: recall 0.75 after
  round 1, 0.79 after round 10, 0.77 after round 30).
- 22 Oct run recovery: replacement pod Ready in 5.3 s, first accepted update 61.5 s
  after the fault; participation 28 / 16 / 22 (before the grace window).

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
| 5 banks + temporary-outage experiments | Proposal scenarios ("varying number of banks", "temporary unavailability") |
| Adjustable bank difference (`--skew`) | Research question 1: performance as non-IID heterogeneity increases |
| Comparison study (resilient / synchronous / timeout / centralised, FedAvg vs FedProx, 3 seeds) | Main Evaluation graphs; several hours of compute |
| Full clean-clone test + `GROUP18_INSTRUCTIONS.pdf` | Required submission; proves it works beyond our laptops |

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
