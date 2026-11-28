from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from kvopt.workload.phase5_calibration_inputs import (
    CalibrationInputError,
    materialize_calibration_input_index,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[dict[str, object], dict[str, object], Path]:
    root = tmp_path / "evidence"
    members = []
    inventory = []
    for index in range(16):
        program = f"repo__task-{index}"
        session = f"phase5:swe:{program}:session:1"
        session_root = root / "sessions" / session
        session_root.mkdir(parents=True)
        normalized = session_root / "normalized-trace.json"
        tokens = session_root / "token-materialization.json"
        fixtures = session_root / "tool-fixtures.json"
        normalized.write_text(f"normalized-{index}")
        tokens.write_text(f"tokens-{index}")
        fixtures.write_text(f"fixtures-{index}")
        source = {
            "program_id": program,
            "session_id": session,
            "source_trace_sha256": f"{index + 1:064x}",
            "qualification_sha256": f"{index + 2:064x}",
            "normalized_trace_file_sha256": _sha(normalized),
            "token_materialization_file_sha256": _sha(tokens),
            "tool_fixtures_file_sha256": _sha(fixtures),
        }
        inventory.append(source)
        members.append({**source, "ordinal": index % 4 + 1, "terminal_class": "RIGHT_CENSORED"})
    child = {
        "schema_version": "phase5.swe_child_manifest.v1",
        "role": "CALIBRATION",
        "child_content_sha256": "a" * 64,
        "groups": [
            {"group_id": f"SWE_G{group + 1:02d}", "members": members[group * 4 : group * 4 + 4]}
            for group in range(4)
        ],
    }
    candidate = {
        "candidate_inventory_content_sha256": "b" * 64,
        "existing_qualified_programs": inventory,
        "fresh_qualified_programs": [],
    }
    return child, candidate, root


def test_materialize_calibration_input_index_binds_exact_files(tmp_path: Path) -> None:
    child, candidate, root = _fixture(tmp_path)
    result = materialize_calibration_input_index(
        calibration_child=child,
        candidate_inventory=candidate,
        evidence_roots=[root],
    )
    assert result["status"] == "PASS"
    assert result["program_count"] == 16
    assert len(result["bindings"]) == 16


def test_materialize_calibration_input_index_rejects_hash_drift(tmp_path: Path) -> None:
    child, candidate, root = _fixture(tmp_path)
    path = next(root.glob("sessions/*/token-materialization.json"))
    path.write_text("drift")
    with pytest.raises(CalibrationInputError, match="accepted hashes"):
        materialize_calibration_input_index(
            calibration_child=child,
            candidate_inventory=candidate,
            evidence_roots=[root],
        )
