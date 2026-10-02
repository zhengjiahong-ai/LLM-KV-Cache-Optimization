"""Command-line entry point for Phase 2A derived datasets."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from .ingestion import ArtifactValidationError
from .pipeline import (
    build_derived_dataset_bundle,
    discover_run_artifacts,
    write_derived_dataset_bundle,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build Phase 2A derived datasets from raw run artifacts.",
    )
    parser.add_argument(
        "artifact_root",
        type=Path,
        help="run directory or parent directory containing raw runs",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="new directory for derived JSONL tables",
    )
    parser.add_argument(
        "--formal-campaign",
        action="store_true",
        help="declare that inputs belong to the formal M6 campaign",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Validate raw runs and write all derived tables."""

    parser = _parser()
    arguments = parser.parse_args(argv)
    try:
        runs = discover_run_artifacts(arguments.artifact_root)
        bundle = build_derived_dataset_bundle(
            runs,
            formal_campaign=arguments.formal_campaign,
        )
        write_derived_dataset_bundle(bundle, arguments.output)
    except (ArtifactValidationError, FileExistsError) as error:
        parser.error(str(error))

    print(
        f"wrote {len(bundle.runs)} run(s) to "
        f"{arguments.output.resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
