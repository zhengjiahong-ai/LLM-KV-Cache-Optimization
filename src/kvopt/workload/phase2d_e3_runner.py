"""Execute one isolated Phase 2D E3 paired diagnostic arm."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .phase2d_e2_runner import _run_phase2d_stage


def run_e3(config_path: Path, *, output_root: Path, run_id: str) -> Path:
    return _run_phase2d_stage(
        config_path,
        output_root=output_root,
        run_id=run_id,
        expected_stage="E3",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    arguments = parser.parse_args(argv)
    output = run_e3(arguments.config, output_root=arguments.output_root, run_id=arguments.run_id)
    manifest = json.loads((output / "run.json").read_text(encoding="utf-8"))
    print(f"{manifest['execution_status']}: {output}")
    if manifest["execution_status"] != "success":
        print(manifest["failure_reason"])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
