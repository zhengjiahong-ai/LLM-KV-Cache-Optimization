#!/usr/bin/env python3
"""Materialize the M1-frozen BFCL Derived 4+8 supplementary partitions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from kvopt.workload.phase5_bfcl_derived_partitions import (
    build_bfcl_derived_supplement_partitions,
)
from kvopt.workload.phase5_dataset_processing import file_sha256


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-group-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    parent = args.parent_group_root.resolve()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite BFCL partition package: {output}")

    parent_manifest = _load(parent / "sha256-manifest.json")
    for name, expected_sha256 in parent_manifest.items():
        path = parent / name
        if not path.is_file() or file_sha256(path) != expected_sha256:
            raise ValueError(f"Parent Group package hash mismatch: {name}")
    calibration, evaluation, paired, audit, seal = (
        build_bfcl_derived_supplement_partitions(
            parent_group_manifest=_load(
                parent / "bfcl-derived-candidate-group-manifest.json"
            ),
            parent_group_seal=_load(parent / "bfcl-derived-group-preparation-seal.json"),
            parent_paired_ledger=_load(parent / "bfcl-derived-paired-mode-ledger.json"),
            parent_sha256_manifest=parent_manifest,
        )
    )
    output.mkdir(parents=True)
    files = {
        "bfcl-derived-calibration-child-manifest.json": calibration,
        "bfcl-derived-evaluation-child-manifest.json": evaluation,
        "bfcl-derived-child-paired-mode-ledger.json": paired,
        "bfcl-derived-child-partition-audit.json": audit,
        "bfcl-derived-supplement-seal.json": seal,
    }
    for name, value in files.items():
        _write(output / name, value)
    manifest = {
        path.name: file_sha256(path)
        for path in sorted(output.iterdir())
        if path.is_file() and path.name != "sha256-manifest.json"
    }
    _write(output / "sha256-manifest.json", manifest)
    print(json.dumps(audit, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
