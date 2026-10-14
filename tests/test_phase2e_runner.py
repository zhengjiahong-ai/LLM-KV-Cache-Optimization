import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from kvopt.workload.phase2e_runner import authorize_config


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_runner_rejects_incomplete_joint_freeze(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    campaign = tmp_path / "manifest.json"
    authorization = tmp_path / "authorization.json"
    config.write_text("{}\n", encoding="utf-8")
    campaign.write_text("{}\n", encoding="utf-8")
    authorization.write_text(
        json.dumps(
            {
                "schema_version": "phase2e.joint_freeze.v1",
                "joint_freeze_complete": False,
                "measured_campaign_authorized": False,
                "campaign_manifest_path": "manifest.json",
                "campaign_manifest_sha256": _sha(campaign),
                "authorized_config_sha256": [_sha(config)],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="joint freeze is incomplete"):
        authorize_config(config, authorization)


def test_runner_accepts_only_hash_bound_config(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    campaign = tmp_path / "manifest.json"
    authorization = tmp_path / "authorization.json"
    config.write_text("{}\n", encoding="utf-8")
    campaign.write_text("{}\n", encoding="utf-8")
    repository = Path(__file__).parents[1]
    git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    authorization.write_text(
        json.dumps(
            {
                "schema_version": "phase2e.joint_freeze.v1",
                "joint_freeze_complete": True,
                "measured_campaign_authorized": True,
                "campaign_manifest_path": "manifest.json",
                "campaign_manifest_sha256": _sha(campaign),
                "authorized_config_sha256": [_sha(config)],
                "git_sha": git_sha,
                "bindings": {
                    "runner": {
                        "sha256": _sha(repository / "src/kvopt/workload/phase2e_runner.py")
                    },
                    "gate_c_evaluator": {
                        "sha256": _sha(repository / "src/kvopt/profiling/phase2e_gate.py")
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    assert authorize_config(config, authorization)["joint_freeze_complete"] is True
