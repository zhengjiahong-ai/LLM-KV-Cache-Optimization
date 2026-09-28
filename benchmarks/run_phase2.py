"""Single command-line entry point for Phase 2 raw experiment runs."""

from __future__ import annotations

import argparse
import json

from kvopt.workload.phase2_runner import run_phase2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-root", default="artifacts/phase2")
    parser.add_argument("--run-id")
    args = parser.parse_args()
    output = run_phase2(args.config, output_root=args.output_root, run_id=args.run_id)
    manifest = json.loads((output / "run.json").read_text(encoding="utf-8"))
    print(f"{manifest['status']}: {output}")
    if manifest["status"] == "failed":
        print(manifest["failure_reason"])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
