# Reliability roadmap: not implemented yet

This folder describes future failure-handling work. It contains no runnable recovery controller and has no setup command.

## What works today

The Flower strategy in [server_app.py](../fl/server_app.py) requires successful replies from all three selected banks. It rejects missing, failed or duplicate-node replies. The reply timeout applies after client selection; startup waits for three available banks. Completed model checkpoints are saved, but are not automatically loaded to resume training.

Kubernetes can restart a stopped process. That does not recover an interrupted training round or guarantee the update is applied only once.

## What still needs to be built

| Planned feature | Why it is needed |
| --- | --- |
| Authenticated bank identity and model/round identifiers | Know which bank sent an update and which model it trained. |
| Stale-update rejection | Prevent an old model update from changing the current round. |
| Minimum-bank quorum and deadline policy | Define when training may continue if a bank is late or unavailable. |
| Atomic aggregation state and durable checkpoints | Record completed work without applying the same update twice. |
| Recovery controller | Restore the correct state after coordinator failure. |

Tests must cover a missing bank, late replies, duplicate submissions, stale updates, concurrent arrivals and coordinator restarts. No quorum, authenticated transport, or automatic recovery guarantees are claimed until these features are implemented and tested.

Start with the [main README](../../../README.md), [current architecture](../../../docs/ARCHITECTURE.md), and [Kubernetes guide](../../../k8s/README.md). The [deployment verification record](../../../docs/DEPLOYMENT_VERIFICATION.md) distinguishes completed deployment checks from these future requirements.
