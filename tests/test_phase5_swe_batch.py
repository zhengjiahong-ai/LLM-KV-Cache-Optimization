from __future__ import annotations

import json
from pathlib import Path

import pytest

from kvopt.workload.phase5_replay import canonical_sha256
from kvopt.workload.phase5_swe_batch import validate_swe_frame, write_batch_manifest


def _frame() -> dict[str, object]:
    candidates = []
    roles = ["PRIMARY"] * 40 + ["RESERVE"] * 24 + ["HISTORICAL_REUSE_RESERVE"] * 20
    for rank, role in enumerate(roles, start=1):
        candidates.append(
            {"phase5_rank": rank, "instance_id": f"task-{rank}", "candidate_role": role}
        )
    frame = {
        "schema_version": "phase5.swe_sampling_frame.v1",
        "status": "FROZEN_ACQUISITION_FRAME_NOT_FORMAL_COHORT",
        "historical_policy": {"may_enter_formal_cohort_without_m1": False},
        "candidates": candidates,
    }
    frame["frame_sha256"] = canonical_sha256(frame)
    return frame


def test_validates_primary_order_and_excludes_historical() -> None:
    identities = validate_swe_frame(_frame())
    assert identities == tuple(f"task-{rank}" for rank in range(1, 41))


def test_rejects_tampered_frame() -> None:
    frame = _frame()
    frame["candidates"][0]["instance_id"] = "tampered"
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        validate_swe_frame(frame)


def test_batch_manifest_binds_frame_and_disables_campaign(tmp_path: Path) -> None:
    frame_path = tmp_path / "frame.json"
    config_path = tmp_path / "config.json"
    frame_path.write_text(json.dumps(_frame()), encoding="utf-8")
    config_path.write_text("{}", encoding="utf-8")
    output = tmp_path / "runs"
    path = write_batch_manifest(
        frame_path=frame_path,
        config_path=config_path,
        output_root=output,
        primary_ids=tuple(f"task-{rank}" for rank in range(1, 41)),
    )
    manifest = json.loads(path.read_text())
    assert manifest["candidate_count"] == 40
    assert manifest["historical_w1c_authorized"] is False
    assert manifest["formal_campaign_authorized"] is False
