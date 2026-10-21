from dataclasses import replace

import numpy as np
import pytest

from app.protocol import Reply
from app.rounds import Round


def state():
    return Round(
        "run",
        1,
        0,
        [np.array([0, 0], dtype=np.float32)],
        {"bank-1": 1, "bank-2": 3},
        {"bank-1": "a", "bank-2": "b"},
    )


def reply(bank="bank-1", samples=1, values=(2, 4), request="a"):
    return Reply("run", 1, 0, bank, request, [np.array(values, dtype=np.float32)], samples)


def test_weighted_average_matches_hand_calculation_and_commits_once():
    current = state()
    assert current.accept(reply()) == "accepted"
    assert current.accept(reply("bank-2", 3, (6, 8), "b")) == "accepted"
    np.testing.assert_array_equal(current.aggregate(2)[0], [5, 7])
    with pytest.raises(ValueError, match="closed"):
        current.aggregate(2)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"run_id": "another-run"}, "wrong_run"),
        ({"attempt": 0}, "stale"),
        ({"version": -1}, "stale"),
        ({"request_id": "old-request"}, "wrong_request"),
        ({"bank_id": "intruder"}, "unknown_bank"),
        ({"samples": 0}, "invalid_samples"),
        ({"samples": True}, "invalid_samples"),
        ({"samples": 999}, "invalid_samples"),
        ({"error": "crashed"}, "client_error"),
        ({"weights": [np.array([np.nan, 1], dtype=np.float32)]}, "invalid_model"),
        ({"weights": [np.array([1], dtype=np.float32)]}, "invalid_model"),
        ({"weights": [np.array([1, 2], dtype=np.float64)]}, "invalid_model"),
    ],
)
def test_bad_replies_cannot_change_state(change, reason):
    current = state()
    assert current.accept(replace(reply(), **change)) == reason
    assert not current.accepted
    np.testing.assert_array_equal(current.weights[0], [0, 0])


def test_duplicate_is_not_a_second_vote_and_quorum_cannot_shrink():
    current = state()
    assert current.accept(reply()) == "accepted"
    assert current.accept(reply()) == "duplicate"
    with pytest.raises(ValueError, match="quorum"):
        current.aggregate(2)
    assert not current.closed


def test_late_reply_after_commit_is_rejected():
    current = state()
    current.accept(reply())
    current.aggregate(1)
    assert current.accept(reply("bank-2", 3, request="b")) == "closed"
