from __future__ import annotations

import json
from pathlib import Path

import pytest

from kvopt.workload.phase5_replay import canonical_sha256
from kvopt.workload.phase5_swe_batch import (
    validate_historical_authorization,
    validate_swe_frame,
    write_batch_manifest,
    write_historical_batch_manifest,
)


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


def _historical_authorization(frame: dict[str, object]) -> dict[str, object]:
    payload = {
        "schema_version": "phase5.swe_historical_reacquisition_authorization.v1",
        "status": "M1_AUTHORIZED_2026_11_24",
        "sampling_frame_canonical_sha256": frame["frame_sha256"],
        "candidate_ranks": list(range(65, 85)),
        "candidate_count": 20,
        "ordered_instance_ids": [f"task-{rank}" for rank in range(65, 85)],
        "old_w1c_evidence_may_be_reused": False,
        "execution_authorized": True,
        "gpu_execution_authorized": False,
    }
    return {**payload, "authorization_sha256": canonical_sha256(payload)}


def test_historical_authorization_binds_exact_ranks_and_fresh_evidence(
    tmp_path: Path,
) -> None:
    frame = _frame()
    authorization = _historical_authorization(frame)
    ids = validate_historical_authorization(authorization, frame)
    assert ids == tuple(f"task-{rank}" for rank in range(65, 85))
    frame_path = tmp_path / "frame.json"
    config_path = tmp_path / "config.json"
    authorization_path = tmp_path / "authorization.json"
    frame_path.write_text(json.dumps(frame), encoding="utf-8")
    config_path.write_text("{}", encoding="utf-8")
    authorization_path.write_text(json.dumps(authorization), encoding="utf-8")
    manifest_path = write_historical_batch_manifest(
        frame_path=frame_path,
        config_path=config_path,
        authorization_path=authorization_path,
        output_root=tmp_path / "fresh-runs",
        ordered_ids=ids,
    )
    manifest = json.loads(manifest_path.read_text())
    assert manifest["candidate_count"] == 20
    assert manifest["candidate_ranks"] == list(range(65, 85))
    assert manifest["old_w1c_evidence_reused"] is False
    assert manifest["formal_campaign_authorized"] is False


def test_historical_authorization_rejects_reorder_and_old_evidence() -> None:
    frame = _frame()
    authorization = _historical_authorization(frame)
    authorization["ordered_instance_ids"][0:2] = reversed(
        authorization["ordered_instance_ids"][0:2]
    )
    payload = dict(authorization)
    payload.pop("authorization_sha256")
    authorization["authorization_sha256"] = canonical_sha256(payload)
    with pytest.raises(ValueError, match="identity order"):
        validate_historical_authorization(authorization, frame)

    authorization = _historical_authorization(frame)
    authorization["old_w1c_evidence_may_be_reused"] = True
    payload = dict(authorization)
    payload.pop("authorization_sha256")
    authorization["authorization_sha256"] = canonical_sha256(payload)
    with pytest.raises(ValueError, match="reuse must remain forbidden"):
        validate_historical_authorization(authorization, frame)
