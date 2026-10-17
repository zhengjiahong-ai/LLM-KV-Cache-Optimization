import hashlib
import json
from pathlib import Path

import pytest

from kvopt.workload.phase2g_a1_bounded_runner import authorize_config


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_runner_rejects_locked_campaign(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    manifest = tmp_path / "manifest.json"
    authorization = tmp_path / "authorization.json"
    config.write_text("{}\n", encoding="utf-8")
    manifest.write_text("{}\n", encoding="utf-8")
    authorization.write_text(
        json.dumps(
            {
                "schema_version": "phase2g.a1_bounded_authorization.v1",
                "gate1_status": "PASS",
                "bounded_campaign_authorized": False,
                "campaign_manifest_path": "manifest.json",
                "campaign_manifest_sha256": _sha(manifest),
                "authorized_config_sha256": [_sha(config)],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="campaign is not authorized"):
        authorize_config(config, authorization)


def test_runner_rejects_unbound_config(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    manifest = tmp_path / "manifest.json"
    authorization = tmp_path / "authorization.json"
    config.write_text("{}\n", encoding="utf-8")
    manifest.write_text("{}\n", encoding="utf-8")
    authorization.write_text(
        json.dumps(
            {
                "schema_version": "phase2g.a1_bounded_authorization.v1",
                "gate1_status": "PASS",
                "bounded_campaign_authorized": True,
                "campaign_manifest_path": "manifest.json",
                "campaign_manifest_sha256": _sha(manifest),
                "authorized_config_sha256": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="config is not bound"):
        authorize_config(config, authorization)
