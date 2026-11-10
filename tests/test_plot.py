import json

from app.data import write_json
from experiments.plot import plot_runs


def run(root, name, mode):
    directory = root / name
    directory.mkdir()
    config = {"mode": mode, "scenario": "healthy", "banks": 3}
    dataset = {"synthetic": True, "sha256": "x", "seed": 42}
    write_json(directory / "run.json", {"runtime": "flower", "config": config, "dataset": dataset})
    write_json(
        directory / "summary.json",
        {
            "status": "completed",
            "training_seconds": 10.0,
            "successful_round_rate": 1.0,
            "committed_rounds": 1,
            "tensor_bytes_sent": 2048,
            "tensor_bytes_received": 2048,
            "processed_examples_returned": 30,
        },
    )
    (directory / "rounds.csv").write_text(
        "attempt,version,status,seconds,elapsed_seconds\n1,1,committed,10,10\n", encoding="utf-8"
    )
    (directory / "events.jsonl").write_text(
        json.dumps({"event": "reply", "metrics": {"peak_process_rss_bytes": 1048576}}) + "\n",
        encoding="utf-8",
    )
    return directory


def test_systems_chart_is_drawn_only_when_there_is_something_to_compare(tmp_path):
    one = run(tmp_path, "a", "resilient")
    single = tmp_path / "single"
    plot_runs([one], single)
    assert (single / "comparison.png").exists()
    assert not (single / "systems.png").exists()

    study = tmp_path / "study"
    plot_runs([one, run(tmp_path, "b", "synchronous")], study)
    assert (study / "systems.png").exists()
