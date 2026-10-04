"""Execute exactly one Phase 2 run for process-isolated campaign execution."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .phase2_runner import run_phase2


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    arguments = parser.parse_args(argv)

    output = run_phase2(
        arguments.config,
        output_root=arguments.output_root,
        run_id=arguments.run_id,
    )
    manifest = json.loads((output / "run.json").read_text(encoding="utf-8"))
    print(f"{manifest['status']}: {output}")
    if manifest["status"] == "failed":
        print(manifest["failure_reason"])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
