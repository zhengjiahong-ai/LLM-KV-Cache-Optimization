"""Evaluate Phase 2E run completeness and cross-baseline pairing fail closed."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

from .phase2e_gate import evaluate_run


def compare_pair(
    native_lru: Mapping[str, object],
    continuum: Mapping[str, object],
) -> dict[str, object]:
    left_digests = native_lru.get("materialized_token_digests")
    right_digests = continuum.get("materialized_token_digests")
    left_rows = native_lru.get("request_evidence")
    right_rows = continuum.get("request_evidence")
    if not isinstance(left_digests, dict) or not isinstance(right_digests, dict):
        return {"status": "NOT_COMPARABLE", "reasons": ["missing token digests"]}
    left_ids = {
        str(row.get("request_id"))
        for row in left_rows
        if isinstance(row, dict)
    } if isinstance(left_rows, list) else set()
    right_ids = {
        str(row.get("request_id"))
        for row in right_rows
        if isinstance(row, dict)
    } if isinstance(right_rows, list) else set()
    checks = {
        "both_runs_valid": native_lru.get("status") == continuum.get("status") == "VALID",
        "scenario_identity_equal": native_lru.get("scenario_id") == continuum.get("scenario_id"),
        "repeat_identity_equal": native_lru.get("repeat") == continuum.get("repeat"),
        "request_identity_equal": left_ids == right_ids and bool(left_ids),
        "materialized_digest_identity_equal": left_digests == right_digests
        and bool(left_digests)
        and all(left_digests.values()),
    }
    return {
        "status": "COMPARABLE" if all(checks.values()) else "NOT_COMPARABLE",
        "checks": checks,
        "reasons": [name for name, passed in checks.items() if not passed],
    }


def evaluate_campaign(*, manifest_path: Path, run_root: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    planned = manifest.get("runs")
    if not isinstance(planned, list):
        raise TypeError("campaign manifest runs must be an array")
    results: list[dict[str, object]] = []
    for entry in planned:
        run_id = str(entry["run_id"])
        run_dir = run_root / run_id
        if not (run_dir / "run.json").is_file():
            results.append(
                {
                    "run_id": run_id,
                    "scenario_id": entry["scenario_id"],
                    "baseline": entry["baseline"],
                    "repeat": entry["repeat"],
                    "status": "MISSING",
                    "family_mechanism_status": "NOT_OBSERVABLE",
                }
            )
            continue
        try:
            results.append(evaluate_run(run_dir))
        except Exception as error:  # noqa: BLE001 - retain invalid evidence reason
            results.append(
                {
                    "run_id": run_id,
                    "scenario_id": entry["scenario_id"],
                    "baseline": entry["baseline"],
                    "repeat": entry["repeat"],
                    "status": "INVALID",
                    "family_mechanism_status": "NOT_OBSERVABLE",
                    "reasons": [f"{type(error).__name__}: {error}"],
                }
            )
    groups: dict[tuple[str, int], dict[str, dict[str, object]]] = defaultdict(dict)
    for row in results:
        groups[(str(row["scenario_id"]), int(row["repeat"]))][str(row["baseline"])] = row
    pairs: list[dict[str, object]] = []
    for (scenario_id, repeat), arms in sorted(groups.items()):
        if set(arms) != {"native-lru", "continuum-baseline"}:
            comparison = {"status": "NOT_COMPARABLE", "reasons": ["paired arm missing"]}
        else:
            comparison = compare_pair(arms["native-lru"], arms["continuum-baseline"])
        pairs.append({"scenario_id": scenario_id, "repeat": repeat, **comparison})
    return {
        "schema_version": "phase2e.campaign_gate.v1",
        "planned_run_count": len(planned),
        "run_status_counts": dict(Counter(str(row["status"]) for row in results)),
        "mechanism_status_counts": dict(
            Counter(str(row["family_mechanism_status"]) for row in results)
        ),
        "pair_status_counts": dict(Counter(str(row["status"]) for row in pairs)),
        "runs": results,
        "pairs": pairs,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = evaluate_campaign(manifest_path=args.manifest, run_root=args.run_root)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote Phase 2E campaign gate: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
