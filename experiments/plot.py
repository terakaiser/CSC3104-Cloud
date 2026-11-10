import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402


def plot_runs(directories: list[Path], output: Path):
    if not directories:
        raise ValueError("provide at least one result directory")
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    fig, axes = plt.subplots(1, 2, figsize=(12, 6), constrained_layout=True)
    colors = {}
    palette = plt.get_cmap("tab10")
    labelled = set()
    synthetic = False
    for directory in directories:
        meta = json.loads((directory / "run.json").read_text(encoding="utf-8"))
        summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
        rounds = pd.read_csv(directory / "rounds.csv")
        config = meta["config"]
        mu, skew = config.get("mu", 0.0), meta["dataset"].get("skew", 1.0)
        label = f"{meta['runtime']} / {config['mode']} / {config['scenario']} / N={config['banks']}"
        label += (f" / mu={mu:g}" if mu else "") + (f" / skew={skew:g}" if skew != 1 else "")
        if label not in colors:
            colors[label] = palette(len(colors) % 10)
        legend_label = label if label not in labelled else "_nolegend_"
        labelled.add(label)
        synthetic |= meta["dataset"]["synthetic"]
        axes[0].plot(
            rounds["attempt"],
            rounds["seconds"],
            marker=".",
            label=legend_label,
            color=colors[label],
            alpha=0.7,
        )
        row = {
            "run": directory.name,
            "runtime": meta["runtime"],
            "dataset_sha256": meta["dataset"]["sha256"],
            "partition_seed": meta["dataset"]["seed"],
            **config,
            "mu": mu,
            "skew": skew,
            **{
                k: summary[k]
                for k in (
                    "status",
                    "training_seconds",
                    "successful_round_rate",
                    "committed_rounds",
                    "tensor_bytes_sent",
                    "tensor_bytes_received",
                    "processed_examples_returned",
                )
            },
        }
        samples = []
        for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event["event"] == "reply" and event.get("metrics"):
                samples.append(event["metrics"])
        if summary.get("resources"):
            samples.append(summary["resources"])
        row["peak_reported_process_mib"] = max(
            (m.get("peak_process_rss_bytes", 0) / 1024**2 for m in samples), default=0
        )
        # Local threaded workers overlap in the same process; their CPU deltas cannot be summed.
        row["returned_worker_cpu_seconds"] = (
            sum(m.get("cpu_seconds", 0) for m in samples)
            if meta["runtime"] != "local_threads"
            else None
        )
        row["tensor_transfer_kib"] = (
            summary["tensor_bytes_sent"] + summary["tensor_bytes_received"]
        ) / 1024
        recovery = directory / "recovery.json"
        if recovery.exists():
            values = json.loads(recovery.read_text(encoding="utf-8"))
            row["fault_to_ready_seconds"] = values.get("fault_to_ready_seconds")
            row["fault_to_accepted_update_seconds"] = values.get("fault_to_accepted_update_seconds")
        evaluation = directory / "evaluation.json"
        if evaluation.exists():
            quality = json.loads(evaluation.read_text(encoding="utf-8"))
            committed = rounds[rounds["status"] == "committed"]
            times = {
                0: 0.0,
                **dict(zip(committed["version"], committed["elapsed_seconds"], strict=False)),
            }
            curve = quality["curve"]
            axes[1].plot(
                [times[p["version"]] for p in curve],
                [p["pr_auc_average_precision"] for p in curve],
                marker=".",
                color=colors[label],
                alpha=0.7,
            )
            row.update(quality["final"])
        rows.append(row)
    axes[0].set(xlabel="Attempt", ylabel="Round duration (seconds)", title="Round progress")
    axes[1].set(
        xlabel="Elapsed training time (seconds)",
        ylabel="Average precision",
        title="Fraud-detection quality",
    )
    for ax in axes:
        ax.grid(alpha=0.2)
    axes[0].legend(fontsize=7, loc="upper left", bbox_to_anchor=(0, -0.18))
    fig.suptitle(
        "SYNTHETIC DATA - software check only" if synthetic else "Federated learning study"
    )
    fig.savefig(output / "comparison.png", dpi=180)
    plt.close(fig)
    table = pd.DataFrame(rows)
    table.to_csv(output / "comparison.csv", index=False)
    group = ["runtime", "mode", "scenario", "banks", "mu", "skew"]
    group += ["dataset_sha256", "partition_seed"]
    values = [
        "training_seconds",
        "successful_round_rate",
        "tensor_transfer_kib",
        "peak_reported_process_mib",
        "returned_worker_cpu_seconds",
    ]
    if "pr_auc_average_precision" in table:
        values.append("pr_auc_average_precision")
    table.groupby(group)[values].agg(["count", "mean", "std"]).to_csv(output / "aggregate.csv")
    grouped = table.groupby(group, sort=False)
    means = grouped[values].mean()
    deviations = grouped[values].std().fillna(0)
    labels = [
        f"{key[1]}\n{key[2]}\nN={key[3]} ({key[0]})"
        + (f"\nmu={key[4]:g}" if key[4] else "")
        + (f"\nskew={key[5]:g}" if key[5] != 1 else "")
        for key in means.index
    ]
    if len(means) < 2:
        # One configuration has nothing to compare against: each chart would be a single
        # full-width bar. The same numbers are in summary.json and aggregate.csv.
        (output / "systems.png").unlink(missing_ok=True)
        return output / "comparison.png"
    systems, charts = plt.subplots(2, 2, figsize=(12, 9), constrained_layout=True)
    for chart, (column, title) in zip(
        charts.flat,
        [
            ("training_seconds", "Training time (seconds)"),
            ("successful_round_rate", "Successful rounds / attempted rounds"),
            ("tensor_transfer_kib", "Model tensor transfer (KiB; protocol overhead excluded)"),
            ("peak_reported_process_mib", "Peak sampled worker-process RSS (MiB)"),
        ],
        strict=True,
    ):
        chart.bar(
            range(len(means)),
            means[column],
            yerr=deviations[column],
            capsize=3,
            color="#287d8e",
        )
        chart.set_xticks(range(len(means)), labels, fontsize=7, rotation=25, ha="right")
        chart.set_title(title, fontsize=10)
        chart.grid(axis="y", alpha=0.2)
        chart.set_axisbelow(True)
    systems.suptitle(
        ("SYNTHETIC DATA - software check only\n" if synthetic else "")
        + "System measurements - mean and standard deviation across repeats"
    )
    systems.savefig(output / "systems.png", dpi=180)
    plt.close(systems)
    return output / "comparison.png"


def plot_resources(directory: Path, faults=()):
    """Per-pod CPU and memory over a run, from the Kubernetes metrics in resources.csv."""
    samples = pd.read_csv(directory / "resources.csv")
    started = (samples["unix_time"] - samples["elapsed_seconds"]).iloc[0]
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True, constrained_layout=True)
    for role, rows in samples.groupby("role"):
        # A killed bank's old and replacement pods share one role, so they form one line.
        rows = rows.sort_values("elapsed_seconds")
        axes[0].plot(rows["elapsed_seconds"], rows["cpu_millicores"], marker=".", label=role)
        axes[1].plot(rows["elapsed_seconds"], rows["memory_mib"], marker=".", label=role)
    for fault in faults:
        for ax in axes:
            ax.axvline(fault["unix_time"] - started, color="red", linestyle="--", alpha=0.6)
        axes[0].annotate(
            f"{fault['bank']} killed",
            (fault["unix_time"] - started, axes[0].get_ylim()[1]),
            fontsize=7,
            color="red",
            rotation=90,
            va="top",
            ha="right",
        )
    axes[0].set(ylabel="CPU (millicores)", title="Pod resource use (Kubernetes metrics-server)")
    axes[1].set(xlabel="Seconds since training was submitted", ylabel="Memory (MiB)")
    for ax in axes:
        ax.grid(alpha=0.2)
    axes[0].legend(fontsize=8, loc="center right")
    (directory / "figures").mkdir(exist_ok=True)
    fig.savefig(directory / "figures" / "resources.png", dpi=180)
    plt.close(fig)
    return directory / "figures" / "resources.png"
