"""Prepare or run the authorized Phase 2I A3 target CUDA Native preflight."""

from __future__ import annotations

import argparse
from pathlib import Path

from kvopt.workload.phase2i_a3_cuda_preflight import (
    materialize_preflight,
    run_preflight,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--source-config", type=Path, required=True)
    prepare.add_argument("--source-trace", type=Path, required=True)
    prepare.add_argument("--profile", type=Path, required=True)
    prepare.add_argument("--output-dir", type=Path, required=True)
    prepare.add_argument("--repository", type=Path, default=Path.cwd())
    execute = subparsers.add_parser("run")
    execute.add_argument("--input-dir", type=Path, required=True)
    execute.add_argument("--output-root", type=Path, required=True)
    execute.add_argument("--repository", type=Path, default=Path.cwd())
    arguments = parser.parse_args()
    if arguments.command == "prepare":
        result = materialize_preflight(
            source_config_path=arguments.source_config,
            source_trace_path=arguments.source_trace,
            profile_path=arguments.profile,
            output_dir=arguments.output_dir,
            repository=arguments.repository,
        )
        print(f"PREPARED: {arguments.output_dir}")
        print(f"git_sha: {result['git_sha']}")
        return 0
    result = run_preflight(
        input_dir=arguments.input_dir,
        output_root=arguments.output_root,
        repository=arguments.repository,
    )
    print(f"{result['status']}: {arguments.output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
