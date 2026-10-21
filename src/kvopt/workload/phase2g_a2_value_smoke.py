"""Run one non-formal A2 bounded-value workload-construction smoke."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .phase2d_e2_runner import _run_phase2d_stage


def run_smoke(config_path: Path, *, output_root: Path, run_id: str) -> Path:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("backend_revision") != "phase2g-a2-bounded-value-v2":
        raise ValueError("smoke requires the bounded-value v2 construction")
    if config.get("campaign_kind") != "phase2g_a2_gate2_bounded_evaluation":
        raise ValueError("unexpected bounded-value campaign kind")
    stage = config.get("phase2g_stage", {})
    if stage.get("stage") != "A2_GATE2_PREPARATION":
        raise ValueError("smoke requires an execution-locked preparation config")
    return _run_phase2d_stage(
        config_path,
        output_root=output_root,
        run_id=run_id,
        expected_stage="A2_GATE2_PREPARATION",
        stage_field="phase2g_stage",
        run_kind="NON_FORMAL_A2_BOUNDED_VALUE_CONSTRUCTION_SMOKE",
        schema_namespace="phase2g",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    output = run_smoke(args.config, output_root=args.output_root, run_id=args.run_id)
    manifest = json.loads((output / "run.json").read_text(encoding="utf-8"))
    print(f"{manifest['execution_status']}: {output}")
    if manifest["execution_status"] != "success":
        print(manifest["failure_reason"])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
