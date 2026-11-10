import json

from app.data import prepare
from experiments import run as study


def test_study_plan_covers_modes_baseline_and_fedprox():
    settings = {
        "seeds": [42, 43],
        "rounds": 3,
        "deadline": 5,
        "scenarios": {
            "healthy": {"scenario": "healthy"},
            "slow": {"scenario": "slow", "delay": 9, "fault_attempt": 2},
            "unavailable": {"scenario": "unavailable"},
        },
    }
    runs = list(study.plan(settings, 3, ["healthy", "slow", "unavailable"], [0.1]))
    per_seed = [(k.get("scenario"), k.get("mode"), k.get("mu")) for k, _ in runs if k["seed"] == 42]
    assert per_seed == [
        (None, None, None),  # centralised baseline
        ("healthy", "synchronous", 0.0),
        ("healthy", "resilient", 0.0),
        ("healthy", "resilient", 0.1),  # FedProx only where nothing else differs
        ("healthy", "timeout", 0.0),
        ("slow", "synchronous", 0.0),
        ("slow", "resilient", 0.0),
        ("slow", "timeout", 0.0),
        ("unavailable", "synchronous", 0.0),
        ("unavailable", "resilient", 0.0),
    ]
    assert len(runs) == 20
    # The faulty bank rotates with the seed, so no single bank drives the result.
    slow = {c.seed: c.slow_bank for k, c in runs if k.get("scenario") == "slow"}
    assert slow == {42: "bank-1", 43: "bank-2"}


def test_study_survives_a_failed_run_and_resumes_without_repeating(tmp_path, monkeypatch):
    data = tmp_path / "data"
    prepare(data, rows=6000)
    config = tmp_path / "scenarios.yaml"
    config.write_text(
        "seeds: [42]\nrounds: 2\ndeadline: 5\nscenarios:\n  healthy:\n    scenario: healthy\n",
        encoding="utf-8",
    )
    output = tmp_path / "study"
    arguments = ["--data", str(data), "--output", str(output), "--config", str(config)]
    arguments += ["--runtime", "local", "--scenarios", "healthy", "--fedprox"]
    real_run = study.run
    calls = []

    def flaky(config, *args):
        calls.append(config.mode)
        if config.mode == "synchronous" and calls.count("synchronous") == 1:
            raise RuntimeError("simulated crash")
        return real_run(config, *args)

    monkeypatch.setattr(study, "run", flaky)
    study.main(arguments)
    entries = [json.loads(line) for line in (output / "progress.jsonl").read_text().splitlines()]
    assert [("error" in e) for e in entries] == [False, True, False, False]
    assert (output / "figures" / "comparison.png").exists()

    calls.clear()
    study.main(arguments)  # resume: only the failed run is repeated
    assert calls == ["synchronous"]
