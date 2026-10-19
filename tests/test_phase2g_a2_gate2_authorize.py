import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kvopt.workload import phase2g_a2_gate2_authorize as authorizer
from kvopt.workload.phase2g_a2_gate2_materialize import materialize_gate2_campaign
from kvopt.workload.phase2g_a2_gate2_validate import validate_gate2_campaign

DISTRIBUTION = Path("configs/phase2/phase2g-a2-native-gate2-distribution-v1.json")
TOOLING_SHA = "a1" * 20


def _inputs(tmp_path: Path) -> tuple[Path, Path]:
    manifest = materialize_gate2_campaign(
        distribution_path=DISTRIBUTION,
        output_dir=tmp_path / "campaign",
    )
    validation = tmp_path / "validation.json"
    validation.write_text(
        json.dumps(validate_gate2_campaign(manifest)),
        encoding="utf-8",
    )
    return manifest, validation


def _git(*, dirty: bool):
    def run(command: list[str], **_: object) -> SimpleNamespace:
        if command[1:] == ["rev-parse", "HEAD"]:
            return SimpleNamespace(stdout=TOOLING_SHA + "\n")
        return SimpleNamespace(stdout=" M changed.py\n" if dirty else "")

    return run


def test_authorization_binds_manifest_configs_traces_and_tooling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, validation = _inputs(tmp_path)
    monkeypatch.setattr(authorizer.subprocess, "run", _git(dirty=False))

    record = authorizer.build_authorization(
        repository=Path(__file__).parents[1],
        campaign_manifest=manifest,
        validation_report=validation,
    )

    assert record["execution_authorized"] is True
    assert record["formal_native_execution_authorized"] is True
    assert record["experiment_tooling_git_sha"] == TOOLING_SHA
    assert len(record["authorized_config_sha256"]) == 144
    assert len(record["authorized_trace_sha256"]) == 36
    assert record["tested_a2_implementation_git_sha"] == authorizer.A2_IMPLEMENTATION_SHA


def test_authorization_rejects_dirty_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, validation = _inputs(tmp_path)
    monkeypatch.setattr(authorizer.subprocess, "run", _git(dirty=True))

    with pytest.raises(ValueError, match="clean working tree"):
        authorizer.build_authorization(
            repository=Path(__file__).parents[1],
            campaign_manifest=manifest,
            validation_report=validation,
        )
