"""How different the banks are (non-IID strength) is set by `skew` when data is prepared."""

import numpy as np
import pytest

from app import demo, download
from app.data import prepare


def amount_means(manifest):
    return [bank["amount_mean"] for bank in manifest["partitions"]["train"].values()]


def test_skew_controls_how_different_the_banks_are(tmp_path):
    spread = {}
    for skew in (0, 1, 3):
        manifest = prepare(tmp_path / f"skew-{skew}", rows=6000, skew=skew)
        assert manifest["skew"] == skew
        means = amount_means(manifest)
        spread[skew] = max(means) / min(means)
    # Identical banks at 0, the standard small-to-large ordering at 1, wider apart above.
    assert spread[0] < 2  # only sampling noise separates identical banks
    assert spread[0] < spread[1] < spread[3]


def test_default_skew_is_the_original_split(tmp_path):
    # Earlier results were produced with the standard split; skew=1 must not change it.
    default = prepare(tmp_path / "default", rows=6000)
    explicit = prepare(tmp_path / "explicit", rows=6000, skew=1.0)
    assert default == explicit
    for file in (tmp_path / "default").rglob("*.npz"):
        with (
            np.load(file) as a,
            np.load(tmp_path / "explicit" / file.relative_to(tmp_path / "default")) as b,
        ):
            np.testing.assert_array_equal(a["ids"], b["ids"])


def test_skew_only_moves_payments_between_banks(tmp_path):
    # The same payments are in each split at every skew, so test results stay comparable.
    ids = {}
    for skew in (0, 2):
        prepare(tmp_path / f"s{skew}", rows=6000, skew=skew)
        ids[skew] = {
            split: sorted(
                np.concatenate(
                    [
                        np.load(f)["ids"]
                        for f in (tmp_path / f"s{skew}").rglob("*.npz")
                        if (split in f.name)
                    ]
                ).tolist()
            )
            for split in ("train", "validation", "test")
        }
    assert ids[0] == ids[2]


def test_every_bank_keeps_both_classes_even_at_high_skew(tmp_path):
    manifest = prepare(tmp_path / "high", rows=6000, banks=5, skew=4)
    for split in manifest["partitions"].values():
        assert all(bank["fraud"] > 0 and bank["samples"] > bank["fraud"] for bank in split.values())


@pytest.mark.parametrize("skew", [-1, float("nan"), float("inf")])
def test_invalid_skew_is_rejected_before_output(tmp_path, skew):
    with pytest.raises(ValueError, match="skew"):
        prepare(tmp_path / "bad", rows=6000, skew=skew)
    assert not (tmp_path / "bad").exists()


def test_existing_partitions_with_another_skew_are_not_reused(tmp_path, monkeypatch):
    csv = b"example CSV bytes"
    import hashlib

    monkeypatch.setattr(download, "CSV_SHA256", hashlib.sha256(csv).hexdigest())
    output = tmp_path / "prepared"
    output.mkdir()
    manifest = {"schema": 1, "synthetic": False, "banks": 3, "seed": 42}
    manifest["sha256"] = download.CSV_SHA256  # no "skew": prepared before it was configurable
    (output / "manifest.json").write_text(__import__("json").dumps(manifest))
    monkeypatch.setattr(
        download.urllib.request, "urlopen", lambda *a, **k: pytest.fail("network used")
    )
    with pytest.raises(ValueError, match="different data or settings"):
        download.setup_data(tmp_path / "raw", output, skew=2.0)


def test_each_bank_count_and_skew_has_its_own_dataset_folder():
    assert demo.dataset_name(False) == "ulb"  # the original folder is unchanged
    assert demo.dataset_name(False, 5) == "ulb-5"
    assert demo.dataset_name(False, 3, 0) == "ulb-skew0"
    assert demo.dataset_name(False, 5, 2.5) == "ulb-5-skew2.5"
    assert demo.dataset_name(True, 3, 4) == "demo-synthetic-skew4"
