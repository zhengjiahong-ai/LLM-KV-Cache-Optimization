"""Run the bounded, non-formal Native smoke for the A2 profile repair."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from kvopt.continuum.prefill_profile import load_prefill_reload_provider

from .phase2d_e2_runner import _run_phase2d_stage

_SCENARIO_ID = "f4-draw-06"
_EXPECTED_PROFILE_SCHEMA = "continuum.prefill_reload.extended_profile.v1"


def validate_smoke_config(config_path: Path) -> dict[str, object]:
    """Fail closed unless the config is the frozen repair boundary case."""
    config_path = config_path.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise TypeError("profile-repair smoke config must be a JSON object")
    stage = config.get("phase2g_stage")
    options = config.get("backend_options")
    if not isinstance(stage, dict) or not isinstance(options, dict):
        raise TypeError("profile-repair smoke requires Phase 2G stage and backend options")
    if stage.get("stage") != "A2_GATE2_PREPARATION":
        raise ValueError("profile-repair smoke requires the frozen Gate 2 preparation stage")
    if stage.get("scenario_id") != _SCENARIO_ID:
        raise ValueError(f"profile-repair smoke is restricted to {_SCENARIO_ID}")
    if stage.get("policy") not in {"A0", "A2"}:
        raise ValueError("profile-repair smoke policy must be A0 or A2")
    profile_value = options.get("prefill_profile_path")
    if not isinstance(profile_value, str) or not profile_value:
        raise ValueError("profile-repair smoke requires an extended PrefillReload profile")
    profile_path = Path(profile_value)
    if not profile_path.is_absolute():
        profile_path = Path(__file__).parents[3] / profile_path
    profile_document = json.loads(profile_path.read_text(encoding="utf-8"))
    if profile_document.get("schema") != _EXPECTED_PROFILE_SCHEMA:
        raise ValueError("profile-repair smoke requires the independently versioned extended profile")
    profile = load_prefill_reload_provider(profile_path)
    profile.estimate(544)
    return config


def run_profile_repair_smoke(
    config_path: Path, *, output_root: Path, run_id: str
) -> Path:
    validate_smoke_config(config_path)
    return _run_phase2d_stage(
        config_path,
        output_root=output_root.resolve(),
        run_id=run_id,
        expected_stage="A2_GATE2_PREPARATION",
        stage_field="phase2g_stage",
        run_kind="NON_FORMAL_PROFILE_RANGE_REPAIR_SMOKE",
        schema_namespace="phase2g_profile_repair",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    arguments = parser.parse_args(argv)
    output = run_profile_repair_smoke(
        arguments.config,
        output_root=arguments.output_root,
        run_id=arguments.run_id,
    )
    manifest = json.loads((output / "run.json").read_text(encoding="utf-8"))
    print(f"{manifest['execution_status']}: {output}")
    if manifest["execution_status"] != "success":
        print(manifest["failure_reason"])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
