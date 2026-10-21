import json
from pathlib import Path

import pytest

from kvopt.workload.phase2g_a2_value_smoke import run_smoke


def test_smoke_rejects_non_v2_config_before_native_execution(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "backend_revision": "old",
                "campaign_kind": "phase2g_a2_gate2_bounded_evaluation",
                "phase2g_stage": {"stage": "A2_GATE2_PREPARATION"},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="bounded-value v2"):
        run_smoke(config, output_root=tmp_path / "runs", run_id="smoke")
