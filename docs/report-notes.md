# Report notes (Group 18)

Working notes for the final article (IEEE/ACM, about 3,000 words), the video and
`GROUP18_INSTRUCTIONS.pdf`. Each feature lists **what** it does, **why** we built it,
and the **evidence** we measured. Every number below comes from a run we actually
performed; the run folder or date is given so it can be traced. Do not add numbers
to the report that are not recorded here or in a results folder.

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

## 2. System design (already in place before the progress presentation)

| Component | What | Why |
|---|---|---|
| Data split | ULB credit-card data (284,807 rows; 1,081 duplicates removed → 283,726). 70/15/15 train/validation/test, stratified. Training rows divided between 3 banks by transaction amount (mean 22.5 / 54.7 / 211.5). | Simulates retail / mid / high-value banks (non-IID) from one public dataset. The split is artificial, which must be stated. |
| Model | 29 → 16 → 1 neural network, SGD, fraud-weighted loss (pos_weight ≈ 599) | Small and CPU-only so many failure experiments are cheap; weighting handles 0.17% fraud. |
| Threshold | Chosen on validation data (max F1), then tested once | Avoids tuning on the test set. |
| Coordinator | Single loop owns all round state; validates run, attempt, version, request, bank identity, duplicates, sample count, tensor shape and finite values | Prevents stale, duplicate or malformed updates corrupting the model; no shared mutable state between threads. |
| Flower | Used only as the messaging layer (`push_messages` / `pull_messages`); rounds are our own logic | Flower's built-in rounds silently drop late replies; we needed version-aware handling. |
| Kubernetes | 1 coordinator + 3 bank Deployments, Service, startup/readiness/liveness gRPC probes, 1 CPU / 1 GiB limits, per-bank read-only data mounts, persistent volume for model versions, non-root containers | Self-healing, service discovery, isolation and resource control: the cloud-native part of the brief. |

## 3. Features added after the progress presentation, and why

### 3.1 FedProx (`mu` setting) — Chee Yuan, 4–5 Nov
- **What:** `--mu` (dashboard: Algorithm selector, μ = 0 / 0.01 / 0.1 / 1). μ = 0 is
  plain FedAvg. Adds (μ/2)·‖w − w_global‖² to each bank's local loss.
- **Why:** answers the lecturer's question with working code; suited to non-IID banks.

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

### 3.6 Robustness fixes found by testing
| Problem | Cause | Fix |
|---|---|---|
| Malformed bank metrics could crash a run | NaN / wrong types reached the event log | Rejected as an invalid reply (Chee Yuan) |
| Synchronous baseline looked worse than it is | A bank freed mid-attempt had to sit out | Synchronous mode re-dispatches to it (Chee Yuan) |
| Training could not start after a CronJob run | Finished job pods are never "Ready" and the start-up wait covered all pods | Wait only for the 4 workload pods; dashboard hides finished job pods |
| Killing the same bank twice could hang | A pod still terminating was mistaken for the replacement | Ignore pods with a deletion timestamp |
| "Failure simulation failed" on Windows | Windows cannot replace a file another process (the dashboard) has open | Retry the atomic replace for up to 2 s; show the real error |

### 3.7 Operations and tooling
- **Dashboard** (`uv run bank-fl demo dashboard`, Charmain and Yee): start runs, kill
  pods, watch Kubernetes state, view results. Present it as Kubernetes
  observability, not as a UI feature (the brief does not require a UI). Raw logs are
  under "Show technical details".
- **Live log lines** "bank-3 went offline / is back online" make failures visible.
- **`bank-fl predict`** scores one held-out payment for demos; the real measurement
  is the full test-set evaluation.
- **Docker image:** dependencies are installed before the code is copied, so a
  code-only rebuild takes about 3 s instead of reinstalling all packages.
- **Experiment deadline** frozen at 40 s from a healthy pilot (rounds 22.1–24.9 s
  locally) before any comparison runs (Chee Yuan).
- **Quality checks:** 97 automated tests; `ruff` lint and formatting enforced.

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
| Per-pod CPU/memory via metrics-server | Systems metrics promised in the proposal |
| 5 banks + temporary-outage experiments | Proposal scenarios ("varying number of banks", "temporary unavailability") |
| Adjustable bank difference (`--skew`) | Research question 1: performance as non-IID heterogeneity increases |
| Comparison study (resilient / synchronous / timeout / centralised, FedAvg vs FedProx, 3 seeds) | Main Evaluation graphs; several hours of compute |
| Full clean-clone test + `GROUP18_INSTRUCTIONS.pdf` | Required submission; proves it works beyond our laptops |
