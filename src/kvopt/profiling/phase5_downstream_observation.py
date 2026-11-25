"""Observation-only linkage from physical victims to later Native requests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from kvopt.workload.phase5_replay import canonical_sha256


def join_downstream_observations(
    *,
    physical_evidence: Mapping[str, object],
    observations: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Link content identities to later N/E/C without asserting causality."""

    if physical_evidence.get("status") != "PASS":
        raise ValueError("physical evidence is not PASS")
    decision_id = physical_evidence.get("decision_id")
    content_rows = physical_evidence.get("block_content_identities")
    if not isinstance(decision_id, str):
        raise TypeError("physical evidence identity is incomplete")
    if not isinstance(content_rows, Mapping):
        raise TypeError("physical evidence content identity is incomplete")
    victim_content = {
        value for value in content_rows.values() if isinstance(value, str) and value != "HASHLESS"
    }
    rows: list[dict[str, object]] = []
    seen_requests: set[str] = set()
    for raw in observations:
        if not isinstance(raw, Mapping):
            raise TypeError("downstream observation must be an object")
        request_id = raw.get("request_id")
        if not isinstance(request_id, str) or not request_id or request_id in seen_requests:
            raise ValueError("downstream request identity is missing or duplicated")
        seen_requests.add(request_id)
        identities = raw.get("prefix_content_identities")
        if not isinstance(identities, list) or any(
            not isinstance(value, str) for value in identities
        ):
            raise ValueError("downstream prefix content identity is incomplete")
        n = raw.get("native_prompt_tokens")
        e = raw.get("reusable_prefix_tokens")
        c = raw.get("native_cached_tokens")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in (n, e, c)
        ):
            raise ValueError("downstream N/E/C evidence is incomplete")
        if not 0 <= c <= e <= n:
            raise ValueError("downstream N/E/C invariant failed")
        rows.append(
            {
                "request_id": request_id,
                "program_id": raw.get("program_id"),
                "session_id": raw.get("session_id"),
                "revisited_victim_content_identities": sorted(
                    victim_content.intersection(identities)
                ),
                "native_prompt_tokens": n,
                "reusable_prefix_tokens": e,
                "native_cached_tokens": c,
                "observed_recomputed_tokens": e - c,
                "prefix_cache_observation": "HIT" if c > 0 else "MISS",
                "eviction_causal_attribution": "NOT_ESTABLISHED",
            }
        )
    payload = {
        "schema_version": "phase5.downstream_observation.v1",
        "status": "PASS",
        "decision_id": decision_id,
        "observation_count": len(rows),
        "observations": rows,
        "downstream_recompute_attribution": "NOT_ESTABLISHED",
        "missing_native_fields": [],
    }
    return {**payload, "evidence_sha256": canonical_sha256(payload)}
