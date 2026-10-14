from pathlib import Path

from kvopt.profiling.phase2d_e4 import evaluate_e4


def test_gate_fails_closed_without_both_arms(tmp_path: Path) -> None:
    result = evaluate_e4(tmp_path)

    assert result["status"] == "NOT_DEMONSTRATED"
    assert result["reasons"] == [
        "exactly one release-a and one release-b run are required"
    ]


def test_gate_rejects_noncomparable_free_queue(monkeypatch, tmp_path: Path) -> None:
    rows = {}
    for arm in ("release-a", "release-b"):
        run_id = f"run-{arm}"
        run_dir = tmp_path / run_id
        run_dir.mkdir()
        (run_dir / "run.json").touch()
        rows[run_id] = {
            "run_id": run_id,
            "arm": arm,
            "status": "VALID",
            "reasons": [],
            "candidate_signature": [("e4-a", 12, 4, True), ("e4-b", 12, 4, True)],
            "free_queue_signature": [(0, arm == "release-a")],
            "materialized_content_digests": {"e4-a:1": "same"},
        }
    monkeypatch.setattr(
        "kvopt.profiling.phase2d_e4._run_evidence",
        lambda path: rows[path.name],
    )

    result = evaluate_e4(tmp_path)

    assert result["status"] == "NOT_DEMONSTRATED"
    assert "paired arms differ in free_queue_signature" in result["reasons"]
