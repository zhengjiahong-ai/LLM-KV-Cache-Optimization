"""Evaluate Phase 2I A3 integration gates from JSONL mock/static evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from kvopt.workload.phase2i_a3_preflight import evaluate_a3_native_preflight


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    events = tuple(
        json.loads(line)
        for line in arguments.events.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    report = evaluate_a3_native_preflight(events)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"{report['status']}: {arguments.output}")
    return 0 if report["status"] == "PASS_STATIC_PREFLIGHT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
