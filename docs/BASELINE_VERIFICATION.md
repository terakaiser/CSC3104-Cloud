# Baseline verification - 11 October 2026

The shared MLP baseline was implemented and verified on Windows with Python 3.12.15 and Flower 1.28.0. Exact dependency resolution is recorded in `uv.lock`.

## Checks performed

- 15 pytest tests passed (two third-party Typer/Click deprecation warnings).
- Actual Ray-backed Flower simulation completed two rounds with three workers on artificial fixtures and again on PaySim.
- All three independent banks and the pooled MLP completed their PaySim runs.
- The educational sequential FedAvg path completed on fixtures and matched Flower's final fixture validation metrics.
- Final Flower PaySim checkpoint reloaded successfully and produced finite probabilities for all 191,155 validation rows.
- Explicit final-test evaluation command verified on artificial fixtures only. PaySim test data was prepared but not evaluated.
- Flower app configuration validated; the only configuration warning was unspecified project license.

## Initial PaySim validation results

These are single-seed, short-run development results, with the threshold selected on the same validation split. They do not establish final test performance or that FL is better than local learning. All runs use fixed nine-feature transforms, the same MLP, seed 42, batch 1024, learning rate 0.001, and 100,000 sampled training rows per bank. Standalone models use two epochs; Flower uses two rounds of one local epoch.

| Model | Precision | Recall | F1 | Average precision |
| --- | ---: | ---: | ---: | ---: |
| bank-a | 0.4220 | 0.3258 | 0.3677 | 0.3547 |
| bank-b | 0.5000 | 0.3207 | 0.3908 | 0.3890 |
| bank-c | 0.5701 | 0.3215 | 0.4112 | 0.4208 |
| centralised | 0.6000 | 0.3384 | 0.4327 | 0.4638 |
| flower | 0.5099 | 0.3047 | 0.3815 | 0.3809 |

## Local run artifacts

- bank-a: `results/runs/bank-a-20261011T044722Z-aff7c6f3`
- bank-b: `results/runs/bank-b-20261011T044733Z-1d84778c`
- bank-c: `results/runs/bank-c-20261011T044743Z-b9d20bed`
- centralised: `results/runs/centralised-20261011T044803Z-613a4505`
- flower: `results/runs/flower-launch-21119dcc/flower-20261011T044618Z-0fbf047e`

These directories contain configuration/version manifests, metrics, and reloadable checkpoints. They are intentionally ignored by Git; archive them with final experimental evidence. Tracked legacy model files were preserved.

## Dataset provenance

Public Kaggle dataset: `moonknightmarvel/paysim`, downloaded version 1. Prepared split sizes: 6,082,007 training, 191,155 validation, and 89,458 test rows. Bank sizes: A 1,989,634; B 2,102,315; C 1,990,058. The downloader and preparation scripts are documented in README.

Raw CSV SHA-256: `16910f90577b0d981bf8ff289714510bb89bc71bff7d3f220f024e287e4eea6b`.

## Runtime limitation

The managed Flower CLI could not start its local SuperLink on this Windows environment. The checked-in launcher uses the public direct Simulation Runtime, which completed successfully. Flower marks that API deprecated; Flower is pinned to 1.28.0. Migrate the launch path when adopting the deployment runtime or upgrading Flower. This is still a local simulation, not a containerised distributed bank deployment.

Checkpoints capture inference state and round metadata; automatic training resume, durable coordinator protocol state, quorum resilience, stale-version recovery, Docker and Kubernetes remain subsequent milestones.
