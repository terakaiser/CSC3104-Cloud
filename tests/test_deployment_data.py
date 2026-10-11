from pathlib import Path
import runpy

import pytest

from crossbank.data.smoke import create_smoke_data

prepare = runpy.run_path(str(Path(__file__).resolve().parents[1] /
                            "scripts/prepare_deployment_data.py"))["prepare"]


def test_deployment_separates_data_and_keeps_smoke_label(tmp_path):
    source, output = tmp_path / "source", tmp_path / "deployment"
    create_smoke_data(source, rows=20)
    prepare(source, output)
    for role, filename in [("coordinator", "validation.csv"), ("bank-a", "bank_a.csv"),
                            ("bank-b", "bank_b.csv"), ("bank-c", "bank_c.csv")]:
        assert {p.name for p in (output / role).iterdir()} == {filename, "SYNTHETIC_SMOKE_ONLY.txt"}
        assert (output / role / filename).read_bytes() == (source / filename).read_bytes()
    with pytest.raises(FileExistsError):
        prepare(source, output)


def test_missing_source_does_not_create_partial_deployment(tmp_path):
    source, output = tmp_path / "source", tmp_path / "deployment"
    create_smoke_data(source, rows=20)
    (source / "bank_c.csv").unlink()
    with pytest.raises(FileNotFoundError):
        prepare(source, output)
    assert not output.exists()
