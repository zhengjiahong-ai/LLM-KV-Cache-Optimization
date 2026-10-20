"""Execute one authorized non-formal A2 Native evidence fidelity fixture."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .phase2d_e2_runner import _run_phase2d_stage


def run_fidelity(config_path: Path, *, output_root: Path, run_id: str) -> Path:
    return _run_phase2d_stage(
        config_path,
        output_root=output_root,
        run_id=run_id,
        expected_stage="A2_FIDELITY",
        stage_field="phase2g_fidelity_stage",
        run_kind="NON_FORMAL_NATIVE_EVIDENCE_FIDELITY_REPAIR",
        schema_namespace="phase2g",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    output = run_fidelity(args.config, output_root=args.output_root, run_id=args.run_id)
    manifest = json.loads((output / "run.json").read_text(encoding="utf-8"))
    print(f"{manifest['execution_status']}: {output}")
    if manifest["execution_status"] != "success":
        print(manifest["failure_reason"])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
