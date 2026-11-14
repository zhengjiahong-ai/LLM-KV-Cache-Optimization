"""CLI for the read-only Phase 3 Algorithm Exposure audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from kvopt.profiling.phase3_algorithm_exposure import (
    analyze_phase3_algorithm_exposure,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--classification", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    summary = analyze_phase3_algorithm_exposure(
        arguments.archive,
        arguments.output,
        arguments.classification,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
