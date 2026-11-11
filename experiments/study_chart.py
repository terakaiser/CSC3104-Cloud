"""Draw the article chart for the comparison study.

One figure, two panels: training time and rounds completed, per scenario and
coordination mode (FedAvg runs only). Every bar is the mean over the seeds
listed in ``progress.jsonl``; nothing is typed in by hand.

    python -m experiments.study_chart results/study
"""

import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, stdev

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SCENARIOS = {
    "healthy": "Healthy",
    "slow": "Slow bank",
    "stale": "Stale update",
    "unavailable": "Missing bank",
}
# mode -> (label, colour, hatch). Hatching keeps the modes apart in greyscale print.
MODES = {
    "synchronous": ("Synchronous (wait for all)", "#2a78d6", ""),
    "timeout": ("Timeout (wait until deadline)", "#eb6834", "//"),
    "resilient": ("Resilient (quorum + grace, ours)", "#1baf7a", ".."),
}
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def load(study: Path) -> dict:
    """Return {(scenario, mode): [(training_seconds, committed_rounds), ...]}."""
    runs = defaultdict(list)
    for line in (study / "progress.jsonl").read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        key = entry["key"]
        if key.get("kind") != "federated" or key.get("mu"):
            continue
        path = Path(entry["directory"]) / "summary.json"
        summary = json.loads(path.read_text(encoding="utf-8"))
        runs[key["scenario"], key["mode"]].append(
            (summary["training_seconds"], summary["committed_rounds"])
        )
    return runs


def draw(study: Path) -> Path:
    runs = load(study)
    planned = max(rounds for values in runs.values() for _, rounds in values)
    seeds = max(len(values) for values in runs.values())
    figure, (time_axis, round_axis) = plt.subplots(1, 2, figsize=(10, 3.9), dpi=200)
    width = 0.26
    for axis, column, title, limit in (
        (time_axis, 0, "Training time (seconds)", None),
        (round_axis, 1, f"Rounds completed (of {planned})", planned * 1.18),
    ):
        for position, scenario in enumerate(SCENARIOS):
            for offset, (mode, (label, colour, hatch)) in zip(
                (-1, 0, 1), MODES.items(), strict=True
            ):
                x = position + offset * width
                values = [run[column] for run in runs.get((scenario, mode), [])]
                if not values:
                    axis.text(
                        x,
                        0,
                        "not run",
                        rotation=90,
                        ha="center",
                        va="bottom",
                        fontsize=7,
                        color=MUTED,
                    )
                    continue
                height = mean(values)
                spread = stdev(values) if len(values) > 1 else 0
                gave_up = column == 0 and not any(r[1] for r in runs[scenario, mode])
                axis.bar(
                    x,
                    height,
                    width - 0.03,
                    color="none" if gave_up else colour,
                    edgecolor=colour if gave_up else "white",
                    hatch=hatch,
                    linewidth=1.2 if gave_up else 0.8,
                    yerr=spread or None,
                    capsize=2.5,
                    error_kw={"elinewidth": 0.9, "ecolor": INK},
                    label=label if position == 0 else None,
                )
                text = f"{height:.0f}"
                if gave_up:
                    text = f"gave up\nat {height:.0f} s"
                axis.text(
                    x,
                    height + spread + (limit or 300) * 0.015,
                    text,
                    ha="center",
                    va="bottom",
                    fontsize=7.5,
                    color=INK,
                )
        axis.set_title(title, fontsize=10, color=INK, loc="left")
        axis.set_xticks(range(len(SCENARIOS)), SCENARIOS.values(), fontsize=8.5)
        axis.tick_params(axis="y", labelsize=8, colors=MUTED, length=0)
        axis.tick_params(axis="x", colors=INK, length=0)
        axis.yaxis.grid(True, color=GRID, linewidth=0.7)
        axis.set_axisbelow(True)
        for side in ("top", "right", "left"):
            axis.spines[side].set_visible(False)
        axis.spines["bottom"].set_color(MUTED)
        if limit:
            axis.set_ylim(0, limit)
        else:
            axis.set_ylim(0, axis.get_ylim()[1] * 1.08)
    handles, labels = time_axis.get_legend_handles_labels()
    figure.legend(
        handles,
        labels,
        loc="upper center",
        ncol=3,
        frameon=False,
        fontsize=8.5,
        bbox_to_anchor=(0.5, 1.0),
    )
    figure.text(
        0.5,
        0.005,
        f"Mean of {seeds} seeds; error bars show one standard deviation. "
        f"{planned} rounds planned, 3 banks, deadline 40 s.",
        ha="center",
        fontsize=7.5,
        color=MUTED,
    )
    figure.tight_layout(rect=(0, 0.03, 1, 0.93))
    output = study / "figures" / "article-time-rounds.png"
    figure.savefig(output, facecolor="white")
    figure.savefig(output.with_suffix(".pdf"), facecolor="white")
    plt.close(figure)
    return output


if __name__ == "__main__":
    print(draw(Path(sys.argv[1] if len(sys.argv) > 1 else "results/study")))
