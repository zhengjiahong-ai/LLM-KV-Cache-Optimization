"""Command-line entry point for the reproducible M4 offline study.

Usage
-----

```text
python -m kvopt.costaware.cli --artifact-root <raw run dir> \
    [--output <report.json>] [--formal] [--rules RULE_ID ...] [--loss-view NAME]
```

The runner needs **no vLLM, no GPU, and no model download**: it replays
already-persisted decision artifacts. Use ``--formal`` only for the complete
canonical campaign raw run set, since the derived pipeline validates the V5
capability contract that legacy diagnostic runs do not satisfy.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .offline_eval import CANONICAL_LOSS_VIEW
from .report import build_offline_report, render_text

_DEFAULT_ARTIFACT_ROOT = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "experiments"
    / "phase2a-m6-formal"
    / "curated-evidence"
    / "exemplars"
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kvopt-m4-offline",
        description=(
            "Replay forced-release decisions and evaluate the M4 candidate "
            "rules. Offline proxy evidence only."
        ),
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=_DEFAULT_ARTIFACT_ROOT,
        help=(
            "directory of raw run directories, each containing run.json, "
            "trace.json, replay.jsonl and events.jsonl"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="write the full report as JSON to this path",
    )
    parser.add_argument(
        "--formal",
        action="store_true",
        help="assert the canonical campaign contract (V5 capability complete)",
    )
    parser.add_argument(
        "--loss-view",
        default=CANONICAL_LOSS_VIEW,
        help="candidate loss view to evaluate",
    )
    parser.add_argument(
        "--rules",
        nargs="*",
        default=None,
        help="restrict the study to these rule ids",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        report = build_offline_report(
            arguments.artifact_root,
            formal=arguments.formal,
            loss_view=arguments.loss_view,
            rule_ids=arguments.rules,
        )
    except FileNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        print(
            "hint: legacy pre-V5 runs fail the capability contract; pass "
            "--formal only for the canonical raw run set.",
            file=sys.stderr,
        )
        return 3

    print(render_text(report))
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False),
            encoding="utf-8",
        )
        print(f"\nreport written: {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
