import hashlib
import io
import json
import zipfile

import pytest

from app import download


def fake_download(monkeypatch, *, corrupt=False):
    csv = b"example CSV bytes"
    monkeypatch.setattr(download, "CSV_SHA256", hashlib.sha256(csv).hexdigest())
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("creditcard.csv", b"wrong data" if corrupt else csv)
        bundle.writestr("../unexpected.txt", "must not extract this")
    monkeypatch.setattr(
        download.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(archive.getvalue())
    )
    return csv


def test_download_verifies_extracts_only_csv_and_reuses_cache(tmp_path, monkeypatch):
    csv = fake_download(monkeypatch)
    target = download.download_csv(tmp_path / "raw")
    assert target.read_bytes() == csv
    assert list((tmp_path / "raw").iterdir()) == [target]
    assert not (tmp_path / "unexpected.txt").exists()
    monkeypatch.setattr(
        download.urllib.request, "urlopen", lambda *a, **k: pytest.fail("network used")
    )
    assert download.download_csv(tmp_path / "raw") == target


def test_bad_checksum_never_publishes_csv(tmp_path, monkeypatch):
    fake_download(monkeypatch, corrupt=True)
    with pytest.raises(ValueError, match="does not match"):
        download.download_csv(tmp_path / "raw")
    assert list((tmp_path / "raw").iterdir()) == []


def test_existing_wrong_csv_is_not_overwritten(tmp_path, monkeypatch):
    fake_download(monkeypatch)
    target = tmp_path / "creditcard.csv"
    target.write_bytes(b"user data")
    with pytest.raises(ValueError, match="does not match"):
        download.download_csv(tmp_path)
    assert target.read_bytes() == b"user data"


def test_conflicting_partitions_fail_before_network(tmp_path, monkeypatch):
    output = tmp_path / "prepared"
    output.mkdir()
    (output / "manifest.json").write_text(json.dumps({"synthetic": True}))
    monkeypatch.setattr(
        download.urllib.request, "urlopen", lambda *a, **k: pytest.fail("network used")
    )
    with pytest.raises(ValueError, match="different data"):
        download.setup_data(tmp_path / "raw", output)


def test_interrupted_preparation_never_publishes_partitions(tmp_path, monkeypatch):
    fake_download(monkeypatch)

    def interrupt(output, **kwargs):
        output.mkdir()
        (output / "partial.npz").write_bytes(b"partial")
        raise RuntimeError("interrupted")

    monkeypatch.setattr(download, "prepare", interrupt)
    output = tmp_path / "prepared"
    with pytest.raises(RuntimeError, match="interrupted"):
        download.setup_data(tmp_path / "raw", output)
    assert not output.exists()
    assert not list(tmp_path.glob(".ulb-prepare-*"))
