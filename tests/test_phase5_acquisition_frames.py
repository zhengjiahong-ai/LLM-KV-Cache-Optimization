"""Integrity tests for the Phase 5 acquisition sampling frames."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
SWE = ROOT / "configs/phase5/phase5-swe-sampling-frame-v1.json"
BFCL = ROOT / "configs/phase5/phase5-bfcl-sampling-frame-v1.json"
SCHEMA = ROOT / "configs/phase5/schema/phase5-acquisition-frames-v1.schema.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _frame_hash(document: dict) -> str:
    payload = dict(document)
    payload.pop("frame_sha256", None)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()


def test_swe_frame_integrity() -> None:
    schema = _load(SCHEMA)
    frame = _load(SWE)
    jsonschema.validate(frame, schema)
    assert frame["frame_sha256"] == _frame_hash(frame)
    assert len(frame["candidates"]) == 84
    roles = [row["candidate_role"] for row in frame["candidates"]]
    assert roles.count("PRIMARY") == 40
    assert roles.count("RESERVE") == 24
    assert roles.count("HISTORICAL_REUSE_RESERVE") == 20
    assert [row["phase5_rank"] for row in frame["candidates"]] == list(range(1, 85))
    assert frame["historical_policy"]["may_enter_formal_cohort_without_m1"] is False
    assert frame["reserve_promotion"]["algorithm_or_native_outcomes_used"] is False


def test_bfcl_frame_integrity() -> None:
    schema = _load(SCHEMA)
    frame = _load(BFCL)
    jsonschema.validate(frame, schema)
    assert frame["frame_sha256"] == _frame_hash(frame)
    assert len(frame["cases"]) == 200
    assert [row["search_mode"] for row in frame["cases"]].count("SNIPPET") == 100
    assert [row["search_mode"] for row in frame["cases"]].count("NO_SNIPPET") == 100
    assert len({row["case_id"] for row in frame["cases"]}) == 200
    assert all(len(row["content_sha256"]) == 64 for row in frame["cases"])
    assert frame["source"]["raw_file_sha256"] == (
        "6fc41d96d003dc849028966a782923560d2fc127ed2088aa967f06daaafa4268"
    )
    assert frame["configuration"]["live_search_allowed"] is False
