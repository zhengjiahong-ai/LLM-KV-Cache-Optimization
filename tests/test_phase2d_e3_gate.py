from pathlib import Path

from kvopt.profiling.phase2d_e3 import evaluate_e3


def test_gate_fails_closed_when_pairs_are_missing(tmp_path: Path) -> None:
    result = evaluate_e3(tmp_path)

    assert result["status"] == "COMPARABILITY_FAILED"
    assert result["valid_pair_count"] == 0
    assert all(row["status"] == "INVALID" for row in result["pairs"])


def test_gate_uses_only_valid_comparable_pairs(monkeypatch, tmp_path: Path) -> None:
    runs = []
    for case_id, target in (
        ("e3-target-a-headroom", "e3-a"),
        ("e3-target-b-control", "e3-b"),
    ):
        for repeat in (1, 2):
            for arm, recomputed in (("release-a", 65), ("release-b", 1)):
                runs.append(
                    {
                        "run_id": f"{case_id}-{arm}-repeat-{repeat}",
                        "case_id": case_id,
                        "arm": arm,
                        "repeat": repeat,
                        "evaluation_program": target,
                        "expected_first_logical_release": arm,
                        "observed_release_sequence": [arm],
                        "candidate_marginal_relief_blocks": {"e3-a": 4, "e3-b": 4},
                        "decision_signature": {"same": True},
                        "materialized_content_digests": {"same": "digest"},
                        "target_request_id": f"{target}:2",
                        "native_cached_prefix_tokens": 128,
                        "native_prompt_tokens": 193,
                        "observed_recomputed_tokens": recomputed,
                        "native_physical_victim_forced": False,
                        "reasons": [],
                    }
                )
    iterator = iter(runs)
    for row in runs:
        (tmp_path / str(row["run_id"])).mkdir()
        (tmp_path / str(row["run_id"]) / "run.json").touch()
    monkeypatch.setattr("kvopt.profiling.phase2d_e3._extract_run", lambda _path: next(iterator))

    result = evaluate_e3(tmp_path)

    assert result["status"] == "HEADROOM_OBSERVED"
    assert result["valid_pair_count"] == 4
    assert {row["delta_recomputed_tokens_release_a_minus_release_b"] for row in result["pairs"]} == {64}
