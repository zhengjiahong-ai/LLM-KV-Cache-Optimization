from __future__ import annotations

import json
from pathlib import Path

import pytest

from kvopt.workload.phase5e_freeze import (
    RUN_ID,
    build_phase5e_freeze_payloads,
    materialize_phase5e_freeze,
)


def _repository() -> Path:
    return Path(__file__).resolve().parents[1]


def test_phase5e_final_payload_binds_explicit_inputs_and_code() -> None:
    payloads = build_phase5e_freeze_payloads(
        repository=_repository(), git_sha="a" * 40
    )

    inputs = payloads["explicit_inputs"]
    assert inputs["run_id"] == RUN_ID
    assert len(inputs["prompt_token_ids"]) == 8
    assert all(len(row) == 1984 for row in inputs["prompt_token_ids"].values())
    assert len(inputs["pressure_token_ids"]) == 24576
    assert len(payloads["code_bindings"]) == 8
    assert payloads["gates"]["not_observable_is_pass"] is False


def test_phase5e_materialization_is_exclusive_and_not_authorized(
    tmp_path: Path,
) -> None:
    output = tmp_path / "freeze"
    result = materialize_phase5e_freeze(
        repository=_repository(), git_sha="b" * 40, output_root=output
    )

    assert result["status"] == "READY_FOR_M1_READ_ONLY_CONFIRMATION"
    assert result["execution_authorized"] is False
    manifest = json.loads((output / "execution-manifest.json").read_text())
    request = json.loads((output / "confirmation-request.json").read_text())
    assert manifest["single_execution_only"] is True
    assert manifest["automatic_retry_allowed"] is False
    assert manifest["execution_authorized"] is False
    assert request["execution_authorized"] is False
    assert len((output / "sha256-manifest.txt").read_text().splitlines()) == 6

    with pytest.raises(FileExistsError):
        materialize_phase5e_freeze(
            repository=_repository(), git_sha="b" * 40, output_root=output
        )


def test_phase5e_freeze_rejects_non_commit_identity(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="full lowercase Git commit"):
        materialize_phase5e_freeze(
            repository=_repository(), git_sha="short", output_root=tmp_path / "bad"
        )
