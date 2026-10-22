"""Fail-closed W1-A CLI over the immutable W0 trajectory converter."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path

from .continuum_source_audit import convert_mini_swe_trajectory, validate_conversion


def _source_instance_id(trajectory: Mapping[str, object]) -> str | None:
    top_level_value = trajectory.get("instance_id")
    top_level_id = str(top_level_value) if top_level_value else None
    info = trajectory.get("info")
    if info is None:
        return top_level_id
    if not isinstance(info, Mapping):
        raise TypeError("trajectory info must be an object")
    value = info.get("instance_id")
    info_id = str(value) if value else None
    if top_level_id and info_id and top_level_id != info_id:
        raise ValueError("trajectory top-level and info instance_id conflict")
    return top_level_id or info_id


def resolve_instance_id(
    trajectory: Mapping[str, object], external_instance_id: str | None
) -> tuple[str, str]:
    """Source identity wins; an external identity may only fill a missing ID."""
    source_id = _source_instance_id(trajectory)
    if source_id and external_instance_id and source_id != external_instance_id:
        raise ValueError("external instance_id conflicts with source trajectory identity")
    resolved = source_id or external_instance_id
    if not resolved:
        raise ValueError("instance_id is required")
    provenance = "SOURCE_TRAJECTORY" if source_id else "EXTERNAL_FILL_FOR_MISSING_SOURCE_ID"
    return resolved, provenance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trajectory", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--instance-id")
    args = parser.parse_args()
    trajectory = json.loads(args.trajectory.read_text(encoding="utf-8"))
    if not isinstance(trajectory, dict):
        raise TypeError("trajectory must be an object")
    instance_id, identity_provenance = resolve_instance_id(trajectory, args.instance_id)
    trace, report = convert_mini_swe_trajectory(trajectory, instance_id=instance_id)
    validation = validate_conversion(trajectory, trace, report)
    validation["instance_id_provenance"] = identity_provenance
    args.output_root.mkdir(parents=True, exist_ok=True)
    outputs = {
        "trace.json": trace.to_dict(),
        "conversion-report.json": report,
        "validation-report.json": validation,
    }
    for name, payload in outputs.items():
        (args.output_root / name).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(f"wrote W1-A workload conversion: {args.output_root}")
    return 2 if validation["verdict"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
