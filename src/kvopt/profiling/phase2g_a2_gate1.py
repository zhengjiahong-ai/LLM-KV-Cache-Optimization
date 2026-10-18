"""Fail-closed review of the Phase 2G A2 Native Gate 1 campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _load_events(path: Path) -> list[dict[str, object]]:
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if not all(isinstance(event, dict) for event in events):
        raise TypeError(f"{path} must contain JSON objects")
    return events


def _payload(event: Mapping[str, object]) -> Mapping[str, object]:
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        raise TypeError("event payload must be an object")
    return payload


def _event_index(event: Mapping[str, object]) -> int:
    value = event.get("event_index")
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("event_index must be an integer")
    return value


def _review_a2_run(run_dir: Path, expected_relation: str) -> dict[str, object]:
    manifest = _load_json(run_dir / "run.json")
    events = _load_events(run_dir / "events.jsonl")
    forced = [event for event in events if event.get("event_type") == "FORCED_RELEASE_DECISION"]
    if len(forced) != 1:
        return {
            "run_id": run_dir.name,
            "valid": False,
            "problems": [f"expected one forced-release decision, observed {len(forced)}"],
        }
    forced_event = forced[0]
    forced_index = _event_index(forced_event)
    decisions = [
        event
        for event in events
        if event.get("event_type") == "COST_AWARE_BLOCK_DECISION"
        and _event_index(event) > forced_index
    ]
    if not decisions:
        return {
            "run_id": run_dir.name,
            "valid": False,
            "problems": ["no A2 decision follows the forced-release decision"],
        }
    decision = decisions[0]
    decision_payload = _payload(decision)
    forced_payload = _payload(forced_event)
    queue = forced_payload.get("original_free_queue")
    if not isinstance(queue, list):
        raise TypeError("forced-release queue must be a list")
    hashed_ids = {
        int(row["block_id"])
        for row in queue
        if isinstance(row, Mapping) and row.get("has_block_hash") is True
    }
    selected = tuple(int(value) for value in decision_payload["selected_victims"])
    native = tuple(int(value) for value in decision_payload["native_lru_victims"])
    selected_hashed = set(selected).intersection(hashed_ids)
    physical = {
        int(_payload(event)["block_id"])
        for event in events
        if event.get("event_type") == "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED"
        and _event_index(event) > _event_index(decision)
    }
    fallbacks = tuple(str(value) for value in decision_payload.get("fallbacks", ()))
    adapter_problems = tuple(
        str(value) for value in decision_payload.get("adapter_problems", ())
    )
    contract_problems = tuple(
        str(value) for value in decision_payload.get("contract_problems", ())
    )
    relation = "DIFFERENT" if selected != native else "SAME"
    expects_fallback = expected_relation == "FALLBACK_SAME"
    fallback_ok = (
        bool(fallbacks)
        and decision_payload.get("selector") == "native_lru_fallback"
        and relation == "SAME"
        if expects_fallback
        else not fallbacks
    )
    problems: list[str] = []
    if manifest.get("execution_status") != "success":
        problems.append("run did not complete successfully")
    if adapter_problems or contract_problems:
        problems.append("adapter or frozen-contract validation failed")
    if not fallback_ok:
        problems.append("fallback behavior differs from the case contract")
    if selected_hashed and not selected_hashed.issubset(physical):
        problems.append("selected hashed victims lack subsequent physical eviction evidence")
    if expected_relation == "SAME" and relation != "SAME":
        problems.append("negative control diverged from Native LRU")
    return {
        "run_id": run_dir.name,
        "valid": not problems,
        "problems": problems,
        "expected_relation": expected_relation,
        "observed_relation": relation,
        "required_blocks": decision_payload["required_blocks"],
        "legal_block_count": len(decision_payload["legal_block_ids"]),
        "selected_victims": selected,
        "native_lru_victims": native,
        "selector": decision_payload["selector"],
        "cost_known": decision_payload["cost_known"],
        "fallbacks": fallbacks,
        "chain_count": decision_payload.get("chain_count", 0),
        "shared_block_count": decision_payload.get("shared_block_count", 0),
        "identified_hashed_block_count": decision_payload.get(
            "identified_hashed_block_count", 0
        ),
        "selected_hashed_victim_count": len(selected_hashed),
        "physically_correlated_hashed_victim_count": len(
            selected_hashed.intersection(physical)
        ),
        "physical_evidence_complete": selected_hashed.issubset(physical),
        "events_sha256": _sha256(run_dir / "events.jsonl"),
        "run_manifest_sha256": _sha256(run_dir / "run.json"),
    }


def build_gate1_report(*, campaign_manifest: Path, run_root: Path) -> dict[str, object]:
    campaign = _load_json(campaign_manifest)
    rows = campaign.get("runs")
    if not isinstance(rows, list):
        raise TypeError("campaign runs must be a list")
    expected = {
        str(row["run_id"]): str(row["expected_relation"])
        for row in rows
        if isinstance(row, Mapping) and row.get("policy") == "A2"
    }
    reviews = [
        _review_a2_run(run_root / run_id, relation)
        for run_id, relation in sorted(expected.items())
    ]
    statuses = Counter(
        "INVALID"
        if not row["valid"]
        else "DIVERGED"
        if row.get("observed_relation") == "DIFFERENT"
        else "FALLBACK"
        if row.get("fallbacks")
        else "AGREED"
        for row in reviews
    )
    shared_realized = any(int(row.get("shared_block_count", 0)) > 0 for row in reviews)
    divergence_realized = statuses["DIVERGED"] > 0
    physical_complete = all(
        bool(row.get("physical_evidence_complete"))
        for row in reviews
        if row.get("valid") and not row.get("fallbacks")
    )
    outcome = (
        "INVALID"
        if statuses["INVALID"]
        else "MECHANISM_INTEGRATION_DEMONSTRATED_WITH_LIMITATIONS"
    )
    return {
        "schema_version": "phase2g.a2_native_gate1_report.v1",
        "outcome": outcome,
        "gate2_execution_authorized": False,
        "planned_run_count": campaign.get("planned_run_count"),
        "observed_run_count": len(list(run_root.glob("*/run.json"))),
        "reviewed_a2_run_count": len(reviews),
        "status_counts": dict(sorted(statuses.items())),
        "native_selection_divergence": (
            "DEMONSTRATED" if divergence_realized else "NOT_REALIZED"
        ),
        "shared_multichain_mechanism": (
            "DEMONSTRATED" if shared_realized else "NOT_REALIZED"
        ),
        "physical_eviction_correlation": (
            "DEMONSTRATED" if physical_complete else "INCOMPLETE"
        ),
        "claim_boundaries": [
            "proxy-weighted selection is not expected recomputed-token evidence",
            "physical eviction correlation is not per-block causal attribution",
            "no Native selection divergence was observed when status is NOT_REALIZED",
            "A2 Gate 2 remains pending M1 review",
        ],
        "campaign_manifest_sha256": _sha256(campaign_manifest),
        "runs": reviews,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = build_gate1_report(
        campaign_manifest=args.campaign.resolve(),
        run_root=args.run_root.resolve(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote Phase 2G A2 Gate 1 report: {args.output}")
    return 0 if report["outcome"] != "INVALID" else 1


if __name__ == "__main__":
    raise SystemExit(main())
