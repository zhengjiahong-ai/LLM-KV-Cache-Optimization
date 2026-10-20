"""Review non-formal A2 Native content/chain fidelity evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _events(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _payload(event: Mapping[str, object]) -> Mapping[str, object]:
    value = event.get("payload")
    return value if isinstance(value, Mapping) else {}


def _decisions(events: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    return [
        _payload(event)
        for event in events
        if event.get("event_type") == "COST_AWARE_BLOCK_DECISION"
    ]


def _count(payload: Mapping[str, object], field: str, key: str) -> int:
    values = payload.get(field)
    if not isinstance(values, Mapping):
        return 0
    value = values.get(key, 0)
    return int(value) if isinstance(value, int) else 0


def _slot_reuse_proved(events: Sequence[Mapping[str, object]]) -> bool:
    identities: dict[int, str] = {}
    evicted: dict[int, str] = {}
    for event in events:
        payload = _payload(event)
        if event.get("event_type") == "VLLM_PREFIX_SNAPSHOT":
            block_ids = payload.get("block_ids")
            hashes = payload.get("ordered_native_cache_keys")
            if isinstance(block_ids, list) and isinstance(hashes, list):
                for block_id, content_hash in zip(block_ids, hashes, strict=True):
                    block = int(block_id)
                    current = str(content_hash)
                    if block in evicted and evicted[block] != current:
                        return True
                    identities[block] = current
        elif event.get("event_type") == "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED":
            block = int(payload["block_id"])
            content_hash = str(payload.get("native_cache_key_before"))
            if identities.get(block) == content_hash:
                evicted[block] = content_hash
                identities.pop(block, None)
    return False


def _program_completion_checks(
    decisions: Sequence[Mapping[str, object]],
) -> dict[str, bool]:
    inactive_observed = False
    active_peer_preserved = False
    stale_weight_absent = True
    for row in decisions:
        states = row.get("chain_states", [])
        if not isinstance(states, list):
            continue
        inactive = {
            str(state.get("chain_id"))
            for state in states
            if isinstance(state, Mapping)
            and state.get("reuse_weight_state") == "INACTIVE"
        }
        known = {
            str(state.get("chain_id"))
            for state in states
            if isinstance(state, Mapping)
            and state.get("reuse_weight_state") == "KNOWN"
        }
        weights = row.get("decision_reuse_weights", {})
        lengths = row.get("effective_chain_lengths", {})
        weighted_chains = set(weights) if isinstance(weights, Mapping) else set()
        effective_chains = set(lengths) if isinstance(lengths, Mapping) else set()
        inactive_observed = inactive_observed or bool(inactive)
        active_peer_preserved = active_peer_preserved or bool(inactive and known)
        stale_weight_absent = stale_weight_absent and not bool(
            inactive.intersection(weighted_chains.union(effective_chains))
        )
    return {
        "completed_chain_marked_inactive": inactive_observed,
        "active_peer_reuse_preserved": active_peer_preserved,
        "completed_chain_stale_weight_absent": stale_weight_absent,
    }


def review_run(run_dir: Path, case_kind: str) -> dict[str, object]:
    manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    events = _events(run_dir / "events.jsonl")
    decisions = _decisions(events)
    problems: list[str] = []
    if manifest.get("execution_status") != "success":
        problems.append("run did not complete successfully")
    if not decisions:
        problems.append("no A2 decision was observed")

    weighted = sum(
        _count(row, "identity_state_counts", "CONTENT_VERIFIED_CHAIN_WEIGHTED")
        for row in decisions
    )
    unknown_weight = sum(int(row.get("unknown_weight_chain_count", 0)) for row in decisions)
    broken = sum(int(row.get("broken_chain_count", 0)) for row in decisions)
    shared = max((int(row.get("shared_block_count", 0)) for row in decisions), default=0)
    fallback_reasons = Counter(
        str(reason) for row in decisions for reason in row.get("fallbacks", [])
    )
    problem_counts: Counter[str] = Counter()
    for row in decisions:
        values = row.get("evidence_problem_counts", {})
        if isinstance(values, Mapping):
            problem_counts.update({str(key): int(value) for key, value in values.items()})

    checks: dict[str, bool] = {
        "execution_success": not problems,
        "decision_observed": bool(decisions),
    }
    state = "PASS"
    if case_kind == "COMPLETE_CHAIN":
        checks["weighted_chain_evidence"] = weighted > 0
    elif case_kind == "PARTIAL_EVICTION":
        checks["native_intervention_observed"] = any(
            event.get("event_type") == "H2_NATIVE_PREFIX_INTERVENTION"
            for event in events
        )
        checks["broken_prefix_reported"] = broken > 0 and problem_counts[
            "chain_prefix_broken"
        ] > 0
        checks["remaining_prefix_boundary_observed"] = any(
            isinstance(state, Mapping)
            and 0 < int(state.get("reusable_prefix_blocks", 0))
            < int(state.get("original_length_blocks", 0))
            for row in decisions
            for state in row.get("chain_states", [])
        )
    elif case_kind == "SHARED_CONTENT":
        checks["shared_membership_observed"] = shared > 0
    elif case_kind == "PROGRAM_COMPLETION":
        checks.update(_program_completion_checks(decisions))
    elif case_kind == "SLOT_REUSE":
        checks["slot_reuse_observed"] = _slot_reuse_proved(events)
    elif case_kind == "INCOMPLETE_EVIDENCE":
        checks["incomplete_evidence_fails_closed"] = bool(fallback_reasons)
        checks["specific_problem_reported"] = bool(problem_counts)
    else:
        raise ValueError(f"unknown fidelity case kind: {case_kind}")

    if problems:
        state = "FAIL"
    elif not all(checks.values()):
        state = "NOT_DEMONSTRATED"
    return {
        "run_id": run_dir.name,
        "case_kind": case_kind,
        "state": state,
        "checks": checks,
        "problems": problems,
        "decision_count": len(decisions),
        "weighted_identity_count": weighted,
        "shared_block_count": shared,
        "broken_chain_count": broken,
        "unknown_weight_chain_count": unknown_weight,
        "fallback_reason_counts": dict(sorted(fallback_reasons.items())),
        "evidence_problem_counts": dict(sorted(problem_counts.items())),
        "events_sha256": _sha(run_dir / "events.jsonl"),
        "run_manifest_sha256": _sha(run_dir / "run.json"),
    }


def build_report(*, campaign_manifest: Path, run_root: Path) -> dict[str, object]:
    campaign = json.loads(campaign_manifest.read_text(encoding="utf-8"))
    if campaign.get("formal") is not False:
        raise ValueError("fidelity review accepts only a non-formal campaign")
    rows = [
        review_run(run_root / str(row["run_id"]), str(row["case_kind"]))
        for row in campaign["runs"]
        if (run_root / str(row["run_id"]) / "run.json").is_file()
    ]
    states = Counter(str(row["state"]) for row in rows)
    return {
        "schema_version": "phase2g.a2_native_evidence_fidelity_report.v1",
        "scope": "NON_FORMAL_NATIVE_EVIDENCE_FIDELITY_REPAIR",
        "formal_effectiveness_evidence": False,
        "planned_run_count": campaign["planned_run_count"],
        "observed_run_count": len(rows),
        "state_counts": dict(sorted(states.items())),
        "overall": (
            "PASS"
            if len(rows) == campaign["planned_run_count"] and states == {"PASS": len(rows)}
            else "FAIL"
            if states["FAIL"]
            else "NOT_DEMONSTRATED"
        ),
        "runs": rows,
        "boundaries": {
            "a2_algorithm_modified": False,
            "native_ownership_modified": False,
            "new_formal_campaign_authorized": False,
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = build_report(campaign_manifest=args.manifest, run_root=args.run_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote A2 Native fidelity report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
