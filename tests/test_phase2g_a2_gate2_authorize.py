import hashlib
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
    original_manifest = tmp_path / "original-manifest.json"
    original_manifest.write_bytes(manifest.read_bytes())
    document = json.loads(manifest.read_text(encoding="utf-8"))
    repository = Path(__file__).parents[1]
    profile = (
        repository
        / "docs/experiments/phase2g-a2-profile-repair/"
        "prefill-reload-profile-extended-544.json"
    )
    for row in document["runs"]:
        config_path = manifest.parent / row["config"]
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["backend_options"]["prefill_profile_path"] = str(
            profile.relative_to(repository)
        )
        config_path.write_text(json.dumps(config, sort_keys=True) + "\n", encoding="utf-8")
        row["config_sha256"] = hashlib.sha256(config_path.read_bytes()).hexdigest()
    document["profile_range_repair"] = {
        "extended_profile_path": str(profile.relative_to(repository)),
        "extended_profile_sha256": hashlib.sha256(profile.read_bytes()).hexdigest(),
        "original_manifest_path": str(original_manifest),
        "original_manifest_sha256": hashlib.sha256(
            original_manifest.read_bytes()
        ).hexdigest(),
        "required_profile_max_tokens": 544,
        "legacy_points_preserved": True,
        "traces_preserved": True,
        "workload_inputs_preserved": True,
        "a2_implementation_preserved": True,
    }
    manifest.write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")
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
    assert record["authorization_review_merge_commit"] == (
        authorizer.V3_AUTHORIZATION_REVIEW_MERGE_COMMIT
    )
    assert record["extended_profile_sha256"] == json.loads(
        manifest.read_text(encoding="utf-8")
    )["profile_range_repair"]["extended_profile_sha256"]


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


def test_authorization_rejects_profile_hash_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, validation = _inputs(tmp_path)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["profile_range_repair"]["extended_profile_sha256"] = "0" * 64
    manifest.write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")
    validation_document = json.loads(validation.read_text(encoding="utf-8"))
    validation_document["manifest_sha256"] = hashlib.sha256(
        manifest.read_bytes()
    ).hexdigest()
    validation.write_text(json.dumps(validation_document), encoding="utf-8")
    monkeypatch.setattr(authorizer.subprocess, "run", _git(dirty=False))

    with pytest.raises(ValueError, match="extended profile SHA-256 mismatch"):
        authorizer.build_authorization(
            repository=Path(__file__).parents[1],
            campaign_manifest=manifest,
            validation_report=validation,
        )
