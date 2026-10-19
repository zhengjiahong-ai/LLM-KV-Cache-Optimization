"""Audit Gate 2 PrefillReload calls and preserve an aborted execution record."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

LEGACY_PROFILE_MAX_TOKENS = 512


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def audit_profile_range(manifest_path: Path) -> dict[str, object]:
    manifest_path = manifest_path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = manifest_path.parent
    runs = manifest.get("runs")
    scenarios = manifest.get("scenarios")
    if not isinstance(runs, list) or not isinstance(scenarios, list):
        raise TypeError("Gate 2 manifest lacks scenarios/runs")

    rows_by_scenario: dict[str, list[dict[str, object]]] = {}
    for raw_row in runs:
        row = dict(raw_row)
        rows_by_scenario.setdefault(str(row["scenario_id"]), []).append(row)

    query_counts: Counter[int] = Counter()
    scenario_maxima: dict[str, int] = {}
    out_of_legacy_range: dict[str, list[int]] = {}
    for raw_scenario in scenarios:
        scenario = dict(raw_scenario)
        scenario_id = str(scenario["scenario_id"])
        rows = rows_by_scenario[scenario_id]
        if not rows:
            raise ValueError(f"scenario has no bound runs: {scenario_id}")
        config = json.loads((root / str(rows[0]["config"])).read_text(encoding="utf-8"))
        trace = json.loads((root / str(rows[0]["trace"])).read_text(encoding="utf-8"))
        segments = config["backend_options"]["prefix_segments_by_request"]
        scenario_counts: list[int] = []
        for request in trace["requests"]:
            # Terminal turns return before PrefillReload is queried by the runtime.
            if request["is_terminal"]:
                continue
            request_id = str(request["request_id"])
            request_segments = segments.get(request_id)
            if not isinstance(request_segments, list) or not request_segments:
                raise ValueError(f"missing request segments: {request_id}")
            token_count = sum(int(segment[1]) for segment in request_segments)
            scenario_counts.append(token_count)
            query_counts[token_count] += 1
        if not scenario_counts:
            raise ValueError(f"scenario has no PrefillReload query path: {scenario_id}")
        scenario_maxima[scenario_id] = max(scenario_counts)
        outside = sorted({count for count in scenario_counts if count > LEGACY_PROFILE_MAX_TOKENS})
        if outside:
            out_of_legacy_range[scenario_id] = outside

    maximum = max(query_counts)
    return {
        "schema_version": "phase2g.a2_profile_range_audit.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha(manifest_path),
        "derivation": (
            "sum(prefix_segments_by_request[request_id].token_count) for every "
            "nonterminal trace request; terminal turns do not query PrefillReload"
        ),
        "legacy_profile_max_tokens": LEGACY_PROFILE_MAX_TOKENS,
        "required_profile_max_tokens": maximum,
        "minimum_new_measured_grid": [maximum],
        "query_token_count_frequency_by_scenario_path": {
            str(count): frequency for count, frequency in sorted(query_counts.items())
        },
        "scenario_max_query_tokens": dict(sorted(scenario_maxima.items())),
        "out_of_legacy_range_scenarios": dict(sorted(out_of_legacy_range.items())),
        "scenario_count": len(scenarios),
        "planned_run_count": len(runs),
        "outcomes_inspected": False,
    }


def build_abort_record(
    *, manifest_path: Path, authorization_path: Path, run_root: Path
) -> dict[str, object]:
    manifest_path = manifest_path.resolve()
    authorization_path = authorization_path.resolve()
    run_root = run_root.resolve()
    attempts: list[dict[str, object]] = []
    statuses: Counter[str] = Counter()
    for run_manifest_path in sorted(run_root.glob("*/run.json")):
        run = json.loads(run_manifest_path.read_text(encoding="utf-8"))
        status = str(run.get("execution_status"))
        statuses[status] += 1
        attempts.append(
            {
                "run_id": run.get("run_id"),
                "execution_status": status,
                "event_count": run.get("event_count"),
                "failure_reason": run.get("failure_reason"),
                "run_manifest_path": str(run_manifest_path),
                "run_manifest_sha256": _sha(run_manifest_path),
                "events_sha256": (
                    _sha(run_manifest_path.parent / "events.jsonl")
                    if (run_manifest_path.parent / "events.jsonl").is_file()
                    else None
                ),
                "stderr_sha256": (
                    _sha(run_manifest_path.parent / "stderr.log")
                    if (run_manifest_path.parent / "stderr.log").is_file()
                    else None
                ),
            }
        )
    if statuses != Counter({"success": 92, "failed": 1}):
        raise ValueError(f"unexpected aborted campaign status counts: {dict(statuses)}")
    failed = [row for row in attempts if row["execution_status"] == "failed"]
    if (
        len(failed) != 1
        or failed[0]["run_id"] != "f4-draw-06-a2-repeat-1"
        or failed[0]["event_count"] != 299
        or failed[0]["failure_reason"]
        != "ValueError: token_count is outside the supported profile range"
    ):
        raise ValueError("aborted campaign failure identity does not match preserved evidence")
    return {
        "schema_version": "phase2g.a2_gate2_aborted_campaign.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "campaign_status": "ABORTED_PROFILE_RANGE_INCOMPATIBILITY",
        "exclusion_from_formal_statistics": True,
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha(manifest_path),
        "authorization_path": str(authorization_path),
        "authorization_sha256": _sha(authorization_path),
        "run_root": str(run_root),
        "attempt_count": len(attempts),
        "status_counts": dict(statuses),
        "attempts": attempts,
        "failure_classification": (
            "PRE_EXECUTION_SUBSTRATE_COVERAGE_REPAIR_DISCOVERED_DURING_FORMAL_EXECUTION"
        ),
        "algorithm_failure": False,
        "results_inspected_for_effect": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    _write(args.output_dir / "profile-range-audit.json", audit_profile_range(args.manifest))
    _write(
        args.output_dir / "aborted-campaign.json",
        build_abort_record(
            manifest_path=args.manifest,
            authorization_path=args.authorization,
            run_root=args.run_root,
        ),
    )
    print(f"wrote A2 profile-range repair audit: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
