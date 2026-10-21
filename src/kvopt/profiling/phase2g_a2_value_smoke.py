"""Validate the bounded Native workload-construction smoke evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

EXPECTED_RUN_IDS = (
    "f4-draw-06-a0-repeat-1",
    "f4-draw-06-a2-repeat-1",
    "f6-draw-02-a0-repeat-1",
    "f6-draw-02-a2-repeat-1",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _events(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def build_smoke_report(*, manifest_path: Path, run_root: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    runs = {str(row["run_id"]): row for row in manifest["runs"]}
    scenarios = {str(row["scenario_id"]): row for row in manifest["scenarios"]}
    rows: list[dict[str, object]] = []
    git_shas: set[str] = set()
    for run_id in EXPECTED_RUN_IDS:
        expected = runs[run_id]
        directory = run_root / run_id
        run = json.loads((directory / "run.json").read_text(encoding="utf-8"))
        config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
        events = _events(directory / "events.jsonl")
        event_counts = Counter(str(event["event_type"]) for event in events)
        checks = {
            "execution_success": run.get("execution_status") == "success",
            "config_hash_bound": _sha(directory / "config.json")
            == expected["config_sha256"],
            "trace_hash_bound": run.get("trace_sha256") == expected["trace_sha256"],
            "extended_profile_bound": config["backend_options"][
                "prefill_profile_path"
            ]
            == manifest["prefill_profile_binding"]["path"],
            "all_submissions_completed": run.get("submission_count")
            == run.get("completion_count"),
        }
        if run_id.startswith("f4-"):
            checks.update(
                {
                    "three_pressure_attempts": run.get("pressure_attempts") == 3,
                    "multi_turn_prefix_snapshots": event_counts[
                        "VLLM_PREFIX_SNAPSHOT"
                    ]
                    >= 20,
                    "forced_release_observed": event_counts[
                        "FORCED_RELEASE_DECISION"
                    ]
                    > 0,
                }
            )
        else:
            omitted = str(
                scenarios[str(expected["scenario_id"])]["family_parameters"][
                    "omitted_program_id"
                ]
            )
            omitted_types = [
                str(event["event_type"])
                for event in events
                if event.get("program_id") == omitted
            ]
            checks.update(
                {
                    "omitted_program_waits_for_followup": "FOLLOWUP_WAITING"
                    in omitted_types,
                    "omitted_program_not_completed": "PROGRAM_COMPLETED"
                    not in omitted_types,
                    "forced_release_observed": event_counts[
                        "FORCED_RELEASE_DECISION"
                    ]
                    > 0,
                }
            )
        git_shas.add(str(run.get("git_sha")))
        rows.append(
            {
                "run_id": run_id,
                "checks": checks,
                "status": "PASS" if all(checks.values()) else "FAIL",
                "event_counts": dict(sorted(event_counts.items())),
                "run_manifest_sha256": _sha(directory / "run.json"),
                "events_sha256": _sha(directory / "events.jsonl"),
            }
        )
    overall = all(row["status"] == "PASS" for row in rows) and len(git_shas) == 1
    return {
        "schema_version": "phase2g.a2_bounded_value_smoke_report.v1",
        "scope": "NON_FORMAL_WORKLOAD_CONSTRUCTION_SMOKE",
        "status": "PASS" if overall else "FAIL",
        "manifest_sha256": _sha(manifest_path),
        "observed_git_sha": next(iter(git_shas)) if len(git_shas) == 1 else None,
        "run_count": len(rows),
        "runs": rows,
        "formal_outcomes_materialized": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = build_smoke_report(manifest_path=args.manifest, run_root=args.run_root)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote A2 bounded-value smoke report: {args.output}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
