# Current architecture and planned work

```text
bank-a data -> bank-a trainer --\
bank-b data -> bank-b trainer ----> coordinator -> versioned model checkpoint
bank-c data -> bank-c trainer --/       |
                                    metrics / monitoring
```

The coordinator starts a shared model, sends it to three banks, combines their locally trained model updates, and evaluates the combined model on validation data. It saves a checkpoint and results after each round. Training requires successful replies from all three selected banks.

There are three ways to run the same training handlers:

| Route | Where the work runs | Instructions |
| --- | --- | --- |
| Local simulation | Three Ray-backed workers on one computer | [Main README](../README.md) |
| Docker Compose | One coordinator container and three bank containers | [Docker guide](../docker/README.md) |
| Local Kubernetes | One coordinator pod and three bank pods | [Kubernetes guide](../k8s/README.md) |

The container routes use Flower's networked Deployment Runtime. Each bank mounts only its own training CSV. The coordinator mounts validation data and persistent results/state storage. Model arrays and training metrics travel through Flower; raw bank rows are not bundled or sent by the training handler. Model updates can still leak information, and cluster administrators control the storage.

Read [deployment verification](DEPLOYMENT_VERIFICATION.md) for completed smoke checks. Stored checkpoints include round metadata and survive pod replacement, but restarting a pod does not resume interrupted training.

Still planned: minimum-bank quorum, stale-model rejection, authenticated bank identities, TLS, and recovery without double aggregation. See the [reliability roadmap](../src/crossbank/reliability/README.md). An inference API and optional Rust demonstration frontend are also future work, not required to run current training.
