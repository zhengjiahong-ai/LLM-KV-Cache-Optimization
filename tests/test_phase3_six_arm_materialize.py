from __future__ import annotations

import json
from pathlib import Path

import pytest

from kvopt.workload.phase3_materialize import (
    ARMS,
    CAMPAIGN_KIND,
    arm_binding,
    materialize_six_arm_cell,
)


def _base() -> dict[str, object]:
    return {
        "schema_version": "phase2.config.v1",
        "execution_authorized": False,
        "trace": "frozen.trace.json",
        "pressure": {"required_blocks": 32},
        "controlled_sparse_replay": {
            "boundaries": [{"boundary_id": "pressure:1", "logical_timestamp": 1.0}]
        },
        "backend_options": {
            "replay_token_ids_by_request": {"r": [1, 2, 3]},
            "pressure_token_ids_by_stage": {"p": [4, 5]},
        },
    }


def test_materializes_six_unauthorized_configs_with_one_shared_input(tmp_path: Path) -> None:
    manifest = materialize_six_arm_cell(
        base_config=_base(), cell_id="g01-low", output_dir=tmp_path / "cell"
    )

    assert tuple(manifest["arms"]) == ARMS
    assert manifest["execution_authorized"] is False
    assert len(manifest["runs"]) == 6
    assert {row["shared_input_sha256"] for row in manifest["runs"]} == {
        manifest["shared_input_sha256"]
    }
    configs = {
        row["arm"]: json.loads(
            (tmp_path / "cell" / row["config"]).read_text(encoding="utf-8")
        )
        for row in manifest["runs"]
    }
    assert all(config["campaign_kind"] == CAMPAIGN_KIND for config in configs.values())
    assert all(config["pressure"] == _base()["pressure"] for config in configs.values())
    assert all(
        config["controlled_sparse_replay"] == _base()["controlled_sparse_replay"]
        for config in configs.values()
    )
    assert configs["N0"]["backend_options"]["phase2g_release_policy"] == "N0"
    assert configs["E0"]["backend_options"]["phase2g_release_policy"] == "E0"
    assert configs["A2"]["backend_options"]["phase2g_block_policy"] == "A2"


def test_materializer_refuses_execution_authority(tmp_path: Path) -> None:
    base = _base()
    base["execution_authorized"] = True
    with pytest.raises(ValueError, match="cannot authorize execution"):
        materialize_six_arm_cell(
            base_config=base, cell_id="g01-low", output_dir=tmp_path / "cell"
        )


def test_arm_binding_rejects_unknown_arm() -> None:
    with pytest.raises(ValueError, match="unsupported Phase 3 arm"):
        arm_binding("AX")
