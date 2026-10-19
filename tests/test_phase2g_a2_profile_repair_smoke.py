from __future__ import annotations

import json
from pathlib import Path

import pytest

from kvopt.workload.phase2g_a2_profile_repair_smoke import validate_smoke_config

REPOSITORY = Path(__file__).parents[1]
CAMPAIGN = REPOSITORY / "artifacts/phase2g-a2-native-gate2-campaign-v3"


def _config(name: str) -> Path:
    path = CAMPAIGN / name
    if not path.is_file():
        pytest.skip("generated repair campaign is not present")
    return path


def test_accepts_frozen_f4_boundary_configs() -> None:
    for policy in ("a0", "a2"):
        config = validate_smoke_config(
            _config(f"f4-draw-06-{policy}-repeat-1.config.json")
        )
        assert config["phase2g_stage"]["scenario_id"] == "f4-draw-06"


def test_rejects_unrelated_scenario_before_native_execution() -> None:
    with pytest.raises(ValueError, match="restricted to f4-draw-06"):
        validate_smoke_config(_config("f4-draw-05-a2-repeat-1.config.json"))


def test_rejects_legacy_profile_before_native_execution(tmp_path: Path) -> None:
    source = _config("f4-draw-06-a2-repeat-1.config.json")
    config = json.loads(source.read_text(encoding="utf-8"))
    config["backend_options"]["prefill_profile_path"] = str(
        REPOSITORY
        / "docs/experiments/phase1b-continuum/artifacts/"
        "prefill-reload-profile-formal-20260920T045859Z-6183d106.json"
    )
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="independently versioned extended profile"):
        validate_smoke_config(path)
