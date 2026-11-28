from __future__ import annotations

import json
from pathlib import Path

from kvopt.workload.phase5_calibration_identity import (
    audit_calibration_execution_identity,
)


def _protocol(revision: str) -> dict[str, object]:
    return {
        "systems": [
            {
                "id": "CONTINUUM_ADAPTED",
                "model": "Qwen/test",
                "model_revision": revision,
                "tokenizer_revision": revision,
            }
        ],
        "controlled_variables": {"same_prompt_token_ids": True},
    }


def _index(tmp_path: Path, revision: str) -> dict[str, object]:
    path = tmp_path / "tokens.json"
    path.write_text(
        json.dumps(
            [
                {
                    "model_revision": revision,
                    "tokenizer_revision": revision,
                    "chat_template_sha256": "c" * 64,
                }
            ]
        )
    )
    return {
        "program_count": 16,
        "bindings": [{"token_materialization_path": str(path)}],
    }


def test_identity_audit_passes_exact_revision(tmp_path: Path) -> None:
    result = audit_calibration_execution_identity(
        protocol=_protocol("a" * 40), input_index=_index(tmp_path, "a" * 40)
    )
    assert result["status"] == "PASS"


def test_identity_audit_fails_closed_on_revision_mismatch(tmp_path: Path) -> None:
    result = audit_calibration_execution_identity(
        protocol=_protocol("a" * 40), input_index=_index(tmp_path, "b" * 40)
    )
    assert result["status"] == "FAIL_CLOSED_IDENTITY_MISMATCH"
    assert result["rematerialization_permitted"] is False
