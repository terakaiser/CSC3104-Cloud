import threading

import numpy as np
import pytest

from app.data import pooled, prepare, replace_file, synthetic_frame


def test_replace_waits_while_another_process_reads_the_target(tmp_path):
    # On Windows a reader's open handle blocks the swap, as the dashboard's polling did.
    target, temporary = tmp_path / "fault-2.json", tmp_path / "fault-2.json.tmp"
    target.write_text("old", encoding="utf-8")
    temporary.write_text("new", encoding="utf-8")
    reader = target.open(encoding="utf-8")
    threading.Timer(0.3, reader.close).start()
    replace_file(temporary, target)
    assert target.read_text(encoding="utf-8") == "new"
    assert not temporary.exists()


def test_replace_still_raises_if_the_target_stays_locked(tmp_path):
    class Locked:
        def replace(self, target):
            raise PermissionError("locked")

    with pytest.raises(PermissionError):
        replace_file(Locked(), tmp_path / "x", attempts=3, wait=0)


def test_partitions_are_disjoint_reproducible_and_class_complete(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    one = prepare(first, rows=6000)
    two = prepare(second, rows=6000)
    assert one == two
    assert one["synthetic"] is True
    identities = []
    for file in first.rglob("*.npz"):
        relative = file.relative_to(first)
        with np.load(file) as data, np.load(second / relative) as again:
            assert set(data["y"]) == {0, 1}
            assert data["x"].shape[1] == 29
            np.testing.assert_array_equal(data["x"], again["x"])
            identities.extend(data["ids"].tolist())
    assert len(identities) == len(set(identities)) == 6000
    x, y = pooled(first, "train", 3)
    assert len(x) == len(y) == 4200
    assert (
        one["partitions"]["train"]["bank-1"]["amount_mean"]
        < (one["partitions"]["train"]["bank-3"]["amount_mean"])
    )
    with pytest.raises(ValueError, match="not empty"):
        prepare(first)


def test_duplicates_removed_before_split(tmp_path):
    import pandas as pd

    frame = synthetic_frame(6000, 42)
    path = tmp_path / "input.csv"
    pd.concat([frame, frame.iloc[:10]]).to_csv(path, index=False)
    manifest = prepare(tmp_path / "prepared", csv=path)
    assert manifest["removed_duplicates"] == 10


def test_invalid_data_is_rejected_before_output(tmp_path):
    frame = synthetic_frame(1000, 42)
    frame.loc[0, "Amount"] = -1
    path = tmp_path / "bad.csv"
    frame.to_csv(path, index=False)
    with pytest.raises(ValueError, match="non-negative"):
        prepare(tmp_path / "prepared", csv=path)
    assert not (tmp_path / "prepared").exists()
