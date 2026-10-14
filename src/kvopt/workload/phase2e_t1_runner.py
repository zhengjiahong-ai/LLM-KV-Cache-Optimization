"""Execute one isolated Phase 2E T1 native-fidelity smoke arm."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .phase2d_e2_runner import _run_phase2d_stage


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    arguments = parser.parse_args(argv)
    output = _run_phase2d_stage(
        arguments.config,
        output_root=arguments.output_root,
        run_id=arguments.run_id,
        expected_stage="T1",
        stage_field="phase2e_stage",
        run_kind="NON_HOLDOUT_RESEARCH_DISCOVERY",
        schema_namespace="phase2e",
    )
    manifest = json.loads((output / "run.json").read_text(encoding="utf-8"))
    print(f"{manifest['execution_status']}: {output}")
    if manifest["execution_status"] != "success":
        print(manifest["failure_reason"])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
