"""Evaluate the non-formal A2 Native intervention positive control."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _events(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _payload(event: Mapping[str, object]) -> Mapping[str, object]:
    value = event.get("payload")
    return value if isinstance(value, Mapping) else {}


def _index(event: Mapping[str, object]) -> int:
    value = event.get("event_index")
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("event_index must be an integer")
    return value


def _content_by_block(payload: Mapping[str, object]) -> dict[int, str]:
    rows = payload.get("legal_content_hashes")
    if not isinstance(rows, list):
        return {}
    return {
        int(row["block_id"]): str(row["content_hash"])
        for row in rows
        if isinstance(row, Mapping) and row.get("content_hash")
    }


def _target_decision(
    events: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object] | None, Mapping[str, object] | None]:
    """Bind the intervention to the first decision after the declared release."""
    releases = [
        event for event in events if event.get("event_type") == "FORCED_RELEASE_DECISION"
    ]
    if len(releases) != 1:
        return None, None
    release = releases[0]
    decisions = [
        event
        for event in events
        if event.get("event_type") == "COST_AWARE_BLOCK_DECISION"
        and _index(event) > _index(release)
    ]
    return release, decisions[0] if decisions else None


def _actual_a0_victims(
    release: Mapping[str, object] | None,
) -> list[int]:
    if release is None:
        return []
    payload = _payload(release)
    required = payload.get("required_blocks")
    queue = payload.get("original_free_queue")
    if isinstance(required, bool) or not isinstance(required, int):
        return []
    if not isinstance(queue, list):
        return []
    rows = [row for row in queue if isinstance(row, Mapping)]
    if len(rows) < required:
        return []
    return [int(row["block_id"]) for row in rows[:required]]


def evaluate_positive_control(
    *,
    campaign_manifest: Path,
    run_root: Path,
    repeat: int = 1,
    case_id: str = "a2-cost-divergence",
) -> dict[str, object]:
    campaign = json.loads(campaign_manifest.read_text(encoding="utf-8"))
    if campaign.get("formal") not in (False, None):
        raise ValueError("positive control must be explicitly non-formal")
    if campaign.get("scope") not in {
        "NON_FORMAL_NATIVE_INTERVENTION_POSITIVE_CONTROL",
        "M1_RC3_MINIMAL_RERUN",
    }:
        raise ValueError("unexpected positive-control scope")

    expected = {
        str(row["policy"]): str(row["run_id"])
        for row in campaign["runs"]
        if row.get("case_id") == case_id
        and int(row.get("repeat", 0)) == repeat
    }
    if set(expected) != {"A0", "A2"}:
        raise ValueError("positive control requires one A0/A2 pair")
    run_dirs = {policy: run_root / run_id for policy, run_id in expected.items()}
    manifests = {
        policy: json.loads((path / "run.json").read_text(encoding="utf-8"))
        for policy, path in run_dirs.items()
    }
    events = {
        policy: _events(path / "events.jsonl") for policy, path in run_dirs.items()
    }
    execution_complete = all(
        manifest.get("execution_status") == "success"
        for manifest in manifests.values()
    )

    a0_release, _ = _target_decision(events["A0"])
    a2_release, decision = _target_decision(events["A2"])
    payload = _payload(decision) if decision is not None else {}
    decision_complete = bool(
        decision is not None
        and payload.get("cost_known") is True
        and not payload.get("fallbacks")
        and not payload.get("adapter_problems")
        and not payload.get("contract_problems")
    )
    gate_a = "PASS" if execution_complete and decision_complete else "FAIL"

    selected: set[int] = set()
    native: set[int] = set()
    selected_hashes: set[str] = set()
    matched_hashes: set[str] = set()
    if decision is not None:
        selected = {int(value) for value in payload.get("selected_victims", [])}
        native = {int(value) for value in payload.get("native_lru_victims", [])}
        identities = _content_by_block(payload)
        selected_hashes = {
            identities[block_id] for block_id in selected if block_id in identities
        }
        process = str(payload.get("native_hash_process_id", ""))
        seen_eviction_hashes: set[str] = set()
        for event in events["A2"]:
            if (
                event.get("event_type")
                != "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED"
                or _index(event) <= _index(decision)
            ):
                continue
            eviction = _payload(event)
            content_hash = str(eviction.get("native_cache_key_before", ""))
            if content_hash in seen_eviction_hashes:
                continue
            if (
                content_hash in selected_hashes
                and str(eviction.get("native_hash_process_id", "")) == process
                and eviction.get("hash_removed_after") is True
            ):
                matched_hashes.add(content_hash)
                seen_eviction_hashes.add(content_hash)

    diverged = bool(selected or native) and selected != native
    gate_b = "PASS" if gate_a == "PASS" and diverged else "FAIL"
    if gate_b != "PASS":
        gate_c = "NOT_OBSERVABLE"
    elif selected_hashes and selected_hashes == matched_hashes:
        gate_c = "PASS"
    else:
        gate_c = "FAIL"

    return {
        "schema_version": "phase2g.a2_native_positive_control_report.v1",
        "scope": "NON_FORMAL_NATIVE_INTERVENTION_POSITIVE_CONTROL",
        "formal_effectiveness_evidence": False,
        "repeat": repeat,
        "case_id": case_id,
        "gates": {
            "cost_evidence": gate_a,
            "selection_intervention": gate_b,
            "physical_realization": gate_c,
        },
        "decision": {
            "observed": decision is not None,
            "target_binding": "first_cost_decision_after_single_forced_release",
            "target_release_event_index": (
                _index(a2_release) if a2_release is not None else None
            ),
            "target_decision_event_index": (
                _index(decision) if decision is not None else None
            ),
            "cost_known": payload.get("cost_known"),
            "fallbacks": list(payload.get("fallbacks", [])),
            "adapter_problems": list(payload.get("adapter_problems", [])),
            "contract_problems": list(payload.get("contract_problems", [])),
            "shared_block_count": int(payload.get("shared_block_count", 0)),
            "selected_victim_count": len(selected),
            "native_reference_victim_count": len(native),
            "actual_a0_victim_block_ids": _actual_a0_victims(a0_release),
            "actual_a0_victim_provenance": (
                "A0 forced-release original native free queue; block IDs are "
                "process-local and are not compared across runs"
            ),
            "victim_set_diverged": diverged,
            "selected_hashed_identity_count": len(selected_hashes),
            "physically_matched_selected_identity_count": len(matched_hashes),
        },
        "outcome": (
            "PASS"
            if gate_a == gate_b == gate_c == "PASS"
            else "INTERVENTION_NOT_REALIZED"
            if gate_a == "PASS" and gate_b == "FAIL"
            else "FAIL"
        ),
        "claim_boundaries": [
            "non-formal mechanism positive control only",
            "cross-process block ids and native hashes are not compared",
            "physical correlation is not per-block recomputation causality",
            "no recomputation-benefit claim is made",
        ],
        "campaign_manifest_sha256": _sha(campaign_manifest),
        "runs": {
            policy: {
                "run_id": expected[policy],
                "run_manifest_sha256": _sha(run_dirs[policy] / "run.json"),
                "events_sha256": _sha(run_dirs[policy] / "events.jsonl"),
            }
            for policy in ("A0", "A2")
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--case-id", default="a2-cost-divergence")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = evaluate_positive_control(
        campaign_manifest=args.campaign,
        run_root=args.run_root,
        repeat=args.repeat,
        case_id=args.case_id,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote A2 Native positive-control report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
