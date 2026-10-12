"""Finalize auditable Phase 2B fidelity gates from raw native events."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

from kvopt.workload.phase2b_fidelity import (
    STATUS_NOT_DEMONSTRATED,
    STATUS_NOT_OBSERVABLE,
    STATUS_PASS,
    FidelityGateResult,
    PressureObservation,
    build_pressure_gate,
)


def _events(path: Path) -> tuple[dict[str, object], ...]:
    return tuple(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())


def _gate(
    name: str,
    *,
    status: str,
    reason: str,
    observed: object,
    indices: Sequence[int],
    runtime: Mapping[str, object],
    scope: str,
    clock_domain: str | None = None,
) -> FidelityGateResult:
    return FidelityGateResult(
        gate=name,
        requested=True,
        observed=observed,
        status=status,
        source_event_indices=tuple(indices),
        scope=scope,
        runtime_identity=runtime,
        reason=reason,
        clock_domain=clock_domain,
    )


def build_fidelity_audit(run_dir: Path) -> dict[str, object]:
    manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    records = _events(run_dir / "events.jsonl")
    initial = json.loads(
        (run_dir / "fidelity-result.json").read_text(encoding="utf-8")
    )
    runtime = {
        "git_sha": manifest.get("git_sha"),
        "config_sha256": manifest.get("config_sha256"),
        "trace_sha256": manifest.get("trace_sha256"),
        "contract_sha256": manifest.get("contract_sha256"),
    }
    by_type: dict[str, list[dict[str, object]]] = defaultdict(list)
    for record in records:
        by_type[str(record["event_type"])].append(record)

    materialized = [
        row
        for row in by_type["BACKEND_INPUT_MATERIALIZED"]
        if row.get("payload", {}).get("kind") == "turn"
    ]
    keys: dict[str, set[str]] = defaultdict(set)
    for row in materialized:
        payload = row["payload"]
        keys[str(payload["prefix_content_key"])].add(
            str(payload["submitted_prefix_token_ids_sha256"])
        )
    shared = any(
        sum(
            row["payload"].get("prefix_content_key") == key
            for row in materialized
        )
        >= 2
        for key in keys
    )
    prefix_input_pass = shared and len(keys) >= 2 and all(len(values) == 1 for values in keys.values())
    gates: list[FidelityGateResult] = [
        _gate(
            "G-PREFIX-INPUT",
            status=STATUS_PASS if prefix_input_pass else STATUS_NOT_DEMONSTRATED,
            reason=(
                "shared keys materialized identical prefixes and distinct keys differed"
                if prefix_input_pass
                else "shared and distinct submitted-prefix controls were incomplete"
            ),
            observed={key: sorted(values) for key, values in sorted(keys.items())},
            indices=[int(row["event_index"]) for row in materialized],
            runtime=runtime,
            scope="submitted_native_token_prefix",
        )
    ]

    native = [
        row
        for row in by_type["VLLM_NATIVE_REQUEST_OBSERVATION"]
        if not str(row.get("program_id", "")).startswith("pressure:")
    ]
    first_by_program: dict[str, dict[str, object]] = {}
    for row in native:
        first_by_program.setdefault(str(row["program_id"]), row)
    shared_a = first_by_program.get("shared-a")
    shared_b = first_by_program.get("shared-b")
    distinct = first_by_program.get("distinct-c")
    native_pass = bool(
        shared_a
        and shared_b
        and distinct
        and shared_a["payload"].get("native_apc_block_hashes")
        == shared_b["payload"].get("native_apc_block_hashes")
        and shared_a["payload"].get("native_apc_block_hashes")
        != distinct["payload"].get("native_apc_block_hashes")
        and int(shared_b["payload"].get("native_cached_prefix_tokens", 0)) > 0
    )
    gates.append(
        _gate(
            "G-PREFIX-NATIVE",
            status=STATUS_PASS if native_pass else STATUS_NOT_DEMONSTRATED,
            reason=(
                "shared native hash chain reused while distinct-key control differed"
                if native_pass
                else "native shared-prefix positive/negative control was incomplete"
            ),
            observed={
                str(row["request_id"]): {
                    "cached_prefix_tokens": row["payload"].get(
                        "native_cached_prefix_tokens"
                    ),
                    "hash_count": len(
                        row["payload"].get("native_apc_block_hashes") or []
                    ),
                }
                for row in native
            },
            indices=[int(row["event_index"]) for row in native],
            runtime=runtime,
            scope="actual_native_apc",
            clock_domain="engine_core_monotonic",
        )
    )

    for raw_gate in initial.get("gates", []):
        if raw_gate.get("gate") == "G-INFLIGHT":
            gates.append(FidelityGateResult(**raw_gate))

    queued = [
        row
        for row in native
        if row["payload"].get("native_queued_timestamp") is not None
        and row["payload"].get("native_scheduler_admission_timestamp") is not None
    ]
    queue_pass = len(queued) == len(native) and bool(native)
    gates.append(
        _gate(
            "G-NATIVE-QUEUE",
            status=STATUS_PASS if queue_pass else STATUS_NOT_OBSERVABLE,
            reason=(
                "native queued and scheduled timestamps were recorded separately"
                if queue_pass
                else "request-scoped native queue timestamps were incomplete"
            ),
            observed={"complete_requests": len(queued), "total_requests": len(native)},
            indices=[int(row["event_index"]) for row in queued],
            runtime=runtime,
            scope="native_scheduler_queue_timing",
            clock_domain="engine_core_monotonic",
        )
    )

    history = by_type["TTL_HISTORY_INPUT_OBSERVED"]
    eligible_samples = max(
        (int(row["payload"].get("queue_delay_history_sample_count", 0)) for row in history),
        default=0,
    )
    history_status = STATUS_PASS if eligible_samples else STATUS_NOT_OBSERVABLE
    gates.append(
        _gate(
            "G-TTL-HISTORY",
            status=history_status,
            reason=(
                "TTL inputs include eligible evicted-request queue history"
                if eligible_samples
                else "native queue timing was observed but no eligible EvictedRequestQueueDelayRecord existed"
            ),
            observed={
                "ttl_decision_count": len(history),
                "eligible_queue_history_sample_count": eligible_samples,
                "native_queue_used_as_ttl_history": any(
                    row["payload"].get("native_queue_duration_used_as_ttl_history") is True
                    for row in history
                ),
            },
            indices=[int(row["event_index"]) for row in history],
            runtime=runtime,
            scope="frozen_continuum_history_inputs",
        )
    )

    release = by_type["FORCED_RELEASE_DECISION"]
    evictions = by_type["VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED"]
    last_eviction = max((int(row["event_index"]) for row in evictions), default=-1)
    subsequent = [row for row in native if int(row["event_index"]) > last_eviction]
    pressure = build_pressure_gate(
        PressureObservation(
            logical_release_event_indices=tuple(int(row["event_index"]) for row in release),
            native_hashed_eviction_event_indices=tuple(
                int(row["event_index"]) for row in evictions
            ),
            subsequent_apc_event_indices=tuple(
                int(row["event_index"]) for row in subsequent
            ),
            native_cache_keys_before_eviction=tuple(
                str(row["payload"]["native_cache_key_before"]) for row in evictions
            ),
            hash_cleanup_confirmed=bool(evictions)
            and all(row["payload"].get("hash_removed_after") is True for row in evictions),
            subsequent_native_cached_prefix_tokens=(
                None
                if not subsequent
                else sum(
                    int(row["payload"]["native_cached_prefix_tokens"])
                    for row in subsequent
                )
            ),
        ),
        runtime_identity=runtime,
    )
    gates.append(pressure)

    negative_pass = bool(
        prefix_input_pass
        and native_pass
        and history
        and eligible_samples == 0
        and not any(
            row["payload"].get("native_queue_duration_used_as_ttl_history") is True
            for row in history
        )
    )
    gates.append(
        _gate(
            "G-NEGATIVE",
            status=STATUS_PASS if negative_pass else STATUS_NOT_DEMONSTRATED,
            reason=(
                "distinct content and ineligible-history controls did not false-pass"
                if negative_pass
                else "one or more required negative controls were incomplete"
            ),
            observed={"distinct_content": native_pass, "native_queue_not_ttl_history": eligible_samples == 0},
            indices=[int(row["event_index"]) for row in (*materialized, *history)],
            runtime=runtime,
            scope="phase2b_negative_controls",
        )
    )
    gates.append(
        _gate(
            "G-LEGACY",
            status=STATUS_NOT_DEMONSTRATED,
            reason="legacy regression result is bound separately after developer self-test",
            observed=None,
            indices=(),
            runtime=runtime,
            scope="legacy_regression",
        )
    )
    provenance_pass = all(runtime.values()) and manifest.get("git_dirty") is False
    gates.append(
        _gate(
            "G-PROVENANCE",
            status=STATUS_PASS if provenance_pass else STATUS_NOT_DEMONSTRATED,
            reason=(
                "clean Git SHA and config/trace/contract hashes are bound"
                if provenance_pass
                else "runtime provenance is incomplete or dirty"
            ),
            observed={**runtime, "git_dirty": manifest.get("git_dirty")},
            indices=(0,) if records else (),
            runtime=runtime,
            scope="artifact_provenance",
        )
    )
    return {
        "schema_version": "phase2b.fidelity_audit.v1",
        "run_id": manifest["run_id"],
        "execution_status": manifest["execution_status"],
        "fidelity_qualification": "NOT_DEMONSTRATED",
        "gates": [gate.to_dict() for gate in gates],
        "limitations": [
            gate.reason
            for gate in gates
            if gate.status in {STATUS_NOT_DEMONSTRATED, STATUS_NOT_OBSERVABLE}
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args(argv)
    output = arguments.output or arguments.run_dir / "fidelity-audit.json"
    report = build_fidelity_audit(arguments.run_dir)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote Phase 2B fidelity audit: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
