from __future__ import annotations

import pytest

from scripts.spikes.phase2_minimal_observability_metal import (
    _w1b_replay_token_ids,
    _w1b_right_censored_end_requests,
)


def test_w1b_replay_tokens_preserve_exact_sequence() -> None:
    result = _w1b_replay_token_ids(
        {
            "continuum_w1b_replay_mode": True,
            "replay_token_ids_by_request": {"session:turn:1": [11, 7, 11, 3]},
        }
    )
    assert result == {"session:turn:1": (11, 7, 11, 3)}


def test_w1b_replay_tokens_require_opt_in() -> None:
    with pytest.raises(ValueError, match="require continuum_w1b_replay_mode"):
        _w1b_replay_token_ids({"replay_token_ids_by_request": {"session:turn:1": [1]}})


def test_w1b_replay_mode_rejects_synthetic_content_mode() -> None:
    with pytest.raises(ValueError, match="exclusive"):
        _w1b_replay_token_ids(
            {
                "continuum_w1b_replay_mode": True,
                "phase2c_native_pilot_mode": True,
                "replay_token_ids_by_request": {"session:turn:1": [1]},
            }
        )


@pytest.mark.parametrize("tokens", [[], [True], [-1], ["1"]])
def test_w1b_replay_tokens_fail_closed_on_invalid_values(tokens: list[object]) -> None:
    with pytest.raises(ValueError, match="token IDs"):
        _w1b_replay_token_ids(
            {
                "continuum_w1b_replay_mode": True,
                "replay_token_ids_by_request": {"session:turn:1": tokens},
            }
        )


def test_w1b_right_censored_endpoints_require_exact_replay_identity() -> None:
    replay = {"request-1": (1, 2, 3)}
    assert _w1b_right_censored_end_requests(
        {"w1b_right_censored_end_request_ids": ["request-1"]},
        replay,
    ) == frozenset({"request-1"})
    with pytest.raises(ValueError, match="missing replay tokens"):
        _w1b_right_censored_end_requests(
            {"w1b_right_censored_end_request_ids": ["request-2"]},
            replay,
        )
