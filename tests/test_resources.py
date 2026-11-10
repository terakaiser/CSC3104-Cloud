import csv
import json
import time

import pytest

from app import resources


def metrics(*pods):
    return json.dumps(
        {
            "items": [
                {
                    "metadata": {"name": name, "labels": {"app": role}},
                    "timestamp": timestamp,
                    "containers": [{"usage": {"cpu": cpu, "memory": memory}}],
                }
                for name, role, timestamp, cpu, memory in pods
            ]
        }
    )


def test_kubernetes_quantities_convert_to_millicores_and_mib():
    assert resources.parse_cpu("250000000n") == pytest.approx(250)
    assert resources.parse_cpu("1500u") == pytest.approx(1.5)
    assert resources.parse_cpu("3m") == 3
    assert resources.parse_cpu("2") == 2000
    assert resources.parse_memory("215040Ki") == pytest.approx(210)
    assert resources.parse_memory("64Mi") == 64
    assert resources.parse_memory("1Gi") == 1024
    assert resources.parse_memory("1048576") == 1


def test_pod_usage_reads_the_metrics_api_and_keeps_the_bank_role():
    calls = []

    def kubectl(*args):
        calls.append(args)
        return metrics(("bank-1-abc", "bank-1", "2026-11-10T08:00:00Z", "120m", "200Mi"))

    (row,) = resources.pod_usage(kubectl)
    assert calls == [("get", "--raw", resources.METRICS_PATH)]
    assert row["role"] == "bank-1" and row["pod"] == "bank-1-abc"
    assert row["cpu_millicores"] == 120 and row["memory_mib"] == 200
    assert row["unix_time"] == 1794297600


def test_sampler_skips_repeats_and_survives_metrics_failures(tmp_path):
    replies = iter(
        [
            metrics(("bank-1-abc", "bank-1", "2026-11-10T08:00:00Z", "100m", "200Mi")),
            RuntimeError("metrics-server not ready"),
            metrics(("bank-1-abc", "bank-1", "2026-11-10T08:00:00Z", "100m", "200Mi")),
            metrics(("bank-1-xyz", "bank-1", "2026-11-10T08:00:15Z", "300m", "260Mi")),
        ]
    )

    def kubectl(*args):
        reply = next(replies, None)
        if isinstance(reply, Exception):
            raise reply
        return reply or metrics()

    path = tmp_path / "resources.csv"
    with resources.Sampler(kubectl, path, interval=0.01):
        time.sleep(0.3)
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [row["pod"] for row in rows] == ["bank-1-abc", "bank-1-xyz"]  # the repeat is dropped
    usage = resources.summarize(path)
    # The replacement pod counts towards the same bank.
    assert usage["bank-1"]["samples"] == 2
    assert usage["bank-1"]["cpu_millicores_mean"] == 200
    assert usage["bank-1"]["cpu_millicores_peak"] == 300
    assert usage["bank-1"]["memory_mib_peak"] == 260


def test_summary_of_a_run_without_metrics_is_empty(tmp_path):
    path = tmp_path / "resources.csv"
    with resources.Sampler(lambda *args: metrics(), path, interval=0.01):
        pass
    assert resources.summarize(path) == {}
