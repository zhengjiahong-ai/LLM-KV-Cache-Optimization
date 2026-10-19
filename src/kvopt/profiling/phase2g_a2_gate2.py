"""Evaluate execution-authorized Phase 2G A0/A2 Gate 2 Native evidence.

This module defines the frozen offline analysis before any formal outcomes exist.
It reuses the corrected Level-B token derivation and keeps selection, physical
eviction, and request-level recomputation as separate evidence layers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

from kvopt.workload.phase2 import load_phase2_trace

from .phase2g_a1_bounded_gate import compare_pair as compare_token_pair
from .phase2g_a1_bounded_gate import evaluate_run as evaluate_token_run
from .phase2g_a2_gate1 import _decision_identities, _event_index, _payload


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_execution_authorization(
    *, manifest_path: Path, authorization_path: Path
) -> dict[str, object]:
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if authorization.get("schema_version") != "phase2g.a2_gate2_authorization.v1":
        raise ValueError("unsupported Gate 2 execution authorization")
    if authorization.get("formal_native_execution_authorized") is not True:
        raise ValueError("formal Native Gate 2 execution is not authorized")
    if authorization.get("execution_authorized") is not True:
        raise ValueError("Gate 2 execution authorization is false")
    if authorization.get("campaign_manifest_sha256") != _sha(manifest_path):
        raise ValueError("authorization is not bound to the frozen manifest")
    if authorization.get("tested_a2_implementation_git_sha") != manifest.get(
        "tested_a2_implementation_git_sha"
    ):
        raise ValueError("authorization A2 implementation SHA mismatch")
    tooling_sha = authorization.get("experiment_tooling_git_sha")
    if not isinstance(tooling_sha, str) or len(tooling_sha) != 40:
        raise ValueError("authorization lacks a full experiment tooling SHA")
    authorized_configs = authorization.get("authorized_config_sha256")
    authorized_traces = authorization.get("authorized_trace_sha256")
    expected_configs = {
        str(row["run_id"]): str(row["config_sha256"]) for row in manifest["runs"]
    }
    expected_traces = {
        str(row["scenario_id"]): str(row["trace_sha256"])
        for row in manifest["scenarios"]
    }
    if authorized_configs != expected_configs:
        raise ValueError("authorization config hashes differ from the frozen manifest")
    if authorized_traces != expected_traces:
        raise ValueError("authorization trace hashes differ from the frozen manifest")
    return authorization


def _validate_run_binding(
    run_dir: Path,
    entry: Mapping[str, object],
    authorization: Mapping[str, object],
    *,
    frozen_root: Path | None = None,
) -> None:
    """Verify original input hashes and the Runner's canonical trace copy.

    The native runner parses the source trace and writes trace.to_dict(); its
    output is not necessarily byte-identical to the frozen input JSON.
    """
    if _sha(run_dir / "config.json") != entry["config_sha256"]:
        raise ValueError("actual run config differs from the frozen config")
    actual_manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    if actual_manifest.get("config_sha256") != entry["config_sha256"]:
        raise ValueError("run manifest config SHA differs from the frozen config")
    if actual_manifest.get("git_dirty") is not False:
        raise ValueError("run was not executed from a clean worktree")
    if actual_manifest.get("git_sha") != authorization["experiment_tooling_git_sha"]:
        raise ValueError("run tooling SHA differs from the authorization")
    if actual_manifest.get("trace_sha256") != entry["trace_sha256"]:
        raise ValueError("run source trace SHA differs from the frozen trace")
    output_trace = run_dir / "trace.json"
    if frozen_root is None:
        # Compatibility with standalone artifact-binding tests, which do not
        # supply a separate frozen campaign directory.
        if _sha(output_trace) != entry["trace_sha256"]:
            raise ValueError("actual run trace differs from the frozen trace")
        return
    source_trace = frozen_root / str(entry["trace"])
    if _sha(source_trace) != entry["trace_sha256"]:
        raise ValueError("frozen input trace does not match its manifest")
    parsed = load_phase2_trace(source_trace)
    canonical = json.dumps(
        parsed.to_dict(), indent=2, sort_keys=True, allow_nan=False
    ) + "\n"
    if output_trace.read_text(encoding="utf-8") != canonical:
        raise ValueError("actual normalized run trace differs from frozen input semantics")

def _load_events(path: Path) -> list[dict[str, object]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if not all(isinstance(row, dict) for row in rows):
        raise TypeError("events.jsonl must contain JSON objects")
    return rows


def _identity_set(
    identities: Mapping[int, tuple[str, str]], block_ids: Sequence[object]
) -> tuple[tuple[str, str], ...] | None:
    ids = tuple(int(value) for value in block_ids)
    if any(block_id not in identities for block_id in ids):
        return None
    return tuple(sorted(identities[block_id] for block_id in ids))


def _strict_physical_evidence(
    events: Sequence[Mapping[str, object]], *, require_block_decision: bool
) -> dict[str, object]:
    """Fail closed on missing identity, ordering, or selected-victim correlation.

    Native process IDs establish *within-run* provenance. The cross-run
    signature intentionally uses content keys only: separate Native runs may
    have distinct process IDs even for identical cached content.
    """
    identities: dict[int, tuple[str, str, int]] = {}
    last_forced: int | None = None
    last_decision: int | None = None
    expected_selected: dict[int, tuple[str, str]] = {}
    matched_selected: set[int] = set()
    signature: list[str] = []
    problems: list[str] = []
    eviction_count = 0

    def check_pending() -> None:
        if require_block_decision and expected_selected and (
            matched_selected != set(expected_selected)
        ):
            problems.append("selected hashed victims lack physical eviction evidence")

    for event in events:
        index = _event_index(event)
        event_type = event.get("event_type")
        if event_type == "FORCED_RELEASE_DECISION":
            check_pending()
            expected_selected.clear()
            matched_selected.clear()
            last_forced = index
            last_decision = None
        elif event_type == "COST_AWARE_BLOCK_DECISION":
            if require_block_decision:
                if last_forced is None or last_forced >= index:
                    problems.append(f"block decision {index} lacks preceding forced release")
                if last_decision is not None:
                    check_pending()
                last_decision = index
                payload = _payload(event)
                process = payload.get("native_hash_process_id")
                legal = payload.get("legal_content_hashes")
                if not isinstance(process, str) or not process or not isinstance(legal, list):
                    problems.append(f"block decision {index} lacks content/process evidence")
                    expected_selected.clear()
                else:
                    cache_keys = {
                        int(row["block_id"]): row.get("content_hash")
                        for row in legal if isinstance(row, Mapping)
                    }
                    expected_selected = {}
                    for value in payload.get("selected_victims", ()):
                        block_id = int(value)
                        key = cache_keys.get(block_id)
                        if key is not None:
                            expected_selected[block_id] = (str(key), process)
                matched_selected.clear()
        elif event_type == "VLLM_PREFIX_SNAPSHOT":
            payload = _payload(event)
            block_ids = payload.get("block_ids")
            cache_keys = payload.get("ordered_native_cache_keys")
            process = payload.get("native_hash_process_id")
            if (
                not isinstance(block_ids, list)
                or not isinstance(cache_keys, list)
                or len(block_ids) != len(cache_keys)
                or not isinstance(process, str)
                or not process
            ):
                problems.append(f"invalid identity snapshot at event {index}")
                continue
            for block_id, cache_key in zip(block_ids, cache_keys, strict=True):
                if cache_key:
                    identities[int(block_id)] = (str(cache_key), process, index)
        elif event_type == "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED":
            payload = _payload(event)
            eviction_count += 1
            block_id = int(payload["block_id"])
            identity = identities.get(block_id)
            if last_forced is None or last_forced >= index:
                problems.append(f"eviction {index} has no preceding forced-release decision")
            if require_block_decision and (
                last_decision is None or last_decision >= index
            ):
                problems.append(f"eviction {index} has no preceding A2 block decision")
            observed = (
                str(payload.get("native_cache_key_before")),
                str(payload.get("native_hash_process_id")),
            )
            if identity is None:
                problems.append(f"eviction {index} has no current content identity")
                continue
            expected = identity[:2]
            if identity[2] >= index:
                problems.append(f"eviction {index} precedes its identity snapshot")
            if observed != expected:
                problems.append(f"eviction {index} content/process identity mismatch")
            if payload.get("hash_removed_after") is not True:
                problems.append(f"eviction {index} did not remove the Native hash")
            if require_block_decision:
                selected = expected_selected.get(block_id)
                if selected != observed or block_id in matched_selected:
                    problems.append(f"eviction {index} is not a selected hashed victim")
                else:
                    matched_selected.add(block_id)
            if observed == expected and payload.get("hash_removed_after") is True:
                signature.append(expected[0])
            identities.pop(block_id, None)
    check_pending()
    observable = eviction_count > 0 and not problems and len(signature) == eviction_count
    return {
        "physical_eviction_count": eviction_count,
        "strict_physical_eviction_signature": sorted(signature),
        "unmapped_physical_eviction_count": eviction_count - len(signature),
        "physical_evidence_observable": observable,
        "physical_evidence_problems": problems,
    }

def _selection_evidence(events: Sequence[Mapping[str, object]]) -> dict[str, object]:
    forced = [row for row in events if row.get("event_type") == "FORCED_RELEASE_DECISION"]
    decisions = [row for row in events if row.get("event_type") == "COST_AWARE_BLOCK_DECISION"]
    rows: list[dict[str, object]] = []
    forced_indices = sorted(_event_index(row) for row in forced)
    decision_indices = sorted(_event_index(row) for row in decisions)
    sequence_complete = len(forced_indices) == len(decision_indices) and bool(forced_indices)
    if sequence_complete:
        sequence_complete = all(
            start < decision and (i + 1 == len(forced_indices) or decision < forced_indices[i + 1])
            for i, (start, decision) in enumerate(zip(forced_indices, decision_indices, strict=True))
        )
    for decision in decisions:
        payload = _payload(decision)
        decision_index = _event_index(decision)
        predecessors = [row for row in forced if _event_index(row) < decision_index]
        queue = _payload(predecessors[-1]).get("original_free_queue") if predecessors else None
        hash_presence: dict[int, bool] = {}
        if isinstance(queue, list):
            for item in queue:
                if isinstance(item, Mapping) and type(item.get("has_block_hash")) is bool:
                    hash_presence[int(item["block_id"])] = item["has_block_hash"]
        audit = payload.get("legal_content_hashes")
        explicit = {}
        if isinstance(audit, list):
            explicit = {
                int(row["block_id"]): row.get("content_hash")
                for row in audit if isinstance(row, Mapping)
            }
        proven = _decision_identities(events, decision)
        selected = tuple(int(value) for value in payload.get("selected_victims", ()))
        native = tuple(int(value) for value in payload.get("native_lru_victims", ()))
        legal = tuple(int(value) for value in payload.get("legal_block_ids", ()))
        required = int(payload.get("required_blocks", 0))

        def state(block_id: int) -> str:
            present = hash_presence.get(block_id)
            key = explicit.get(block_id)
            if present is False and key is None and block_id in explicit:
                return "HASHLESS_NO_CONTENT"
            if present is True and key is not None and block_id in proven:
                return "HASHED_PROVEN"
            return "HASHED_UNVERIFIED"

        states = {block_id: state(block_id) for block_id in legal}
        def complete(ids: tuple[int, ...]) -> bool:
            return all(states.get(block_id) in {"HASHED_PROVEN", "HASHLESS_NO_CONTENT"} for block_id in ids)
        identity_complete = complete(legal) and complete(selected) and complete(native)
        selected_hashed = {
            proven[bid] for bid in selected if states.get(bid) == "HASHED_PROVEN"
        }
        native_hashed = {
            proven[bid] for bid in native if states.get(bid) == "HASHED_PROVEN"
        }
        any_hashless_changed = set(selected) != set(native) and (
            any(states.get(bid) == "HASHLESS_NO_CONTENT" for bid in set(selected) ^ set(native))
        )
        selection_difference = (
            None if not identity_complete
            else True if selected_hashed != native_hashed
            else None if any_hashless_changed
            else False
        )
        fallbacks = tuple(str(value) for value in payload.get("fallbacks", ()))
        adapter_problems = tuple(str(value) for value in payload.get("adapter_problems", ()))
        contract_problems = tuple(str(value) for value in payload.get("contract_problems", ()))
        checks = {
            "selected_are_legal": set(selected).issubset(legal),
            "native_lru_are_legal": set(native).issubset(legal),
            "selected_count_matches_required": len(selected) == required,
            "native_lru_count_matches_required": len(native) == required,
            "selected_are_unique": len(selected) == len(set(selected)),
            "native_lru_are_unique": len(native) == len(set(native)),
            "legal_are_unique": len(legal) == len(set(legal)),
            "legal_identity_complete": complete(legal),
            "selected_identity_complete": complete(selected),
            "native_lru_identity_complete": complete(native),
            "adapter_problems_absent": not adapter_problems,
            "contract_problems_absent": not contract_problems,
            "fallback_is_explicit_native_lru": (
                not fallbacks or (
                    payload.get("selector") == "native_lru_fallback"
                    and set(selected) == set(native)
                )
            ),
        }
        rows.append({
            "event_index": decision_index,
            "required_blocks": required,
            "legal_block_count": len(legal),
            "selected_victim_count": len(selected),
            "native_lru_victim_count": len(native),
            "block_id_sets_differ": set(selected) != set(native),
            "identity_complete": identity_complete,
            "legal_identity_states": states,
            "selected_content_identities": tuple(sorted(selected_hashed)),
            "native_lru_content_identities": tuple(sorted(native_hashed)),
            "content_identity_sets_differ": selection_difference,
            "selector": payload.get("selector"),
            "fallbacks": fallbacks,
            "adapter_problems": adapter_problems,
            "contract_problems": contract_problems,
            "checks": checks,
            "decision_contract_valid": all(checks.values()),
        })
    contract_valid = sequence_complete and all(bool(row["decision_contract_valid"]) for row in rows)
    fallback_count = sum(bool(row["fallbacks"]) for row in rows)
    return {
        "forced_release_count": len(forced),
        "block_decision_count": len(decisions),
        "decision_rows": rows,
        "decision_sequence_complete": sequence_complete,
        "selection_contract_valid": contract_valid,
        "selection_mechanism_realized": contract_valid and fallback_count == 0,
        "selection_identity_complete": all(row["identity_complete"] for row in rows) and bool(rows),
        "selection_diverged": (
            None if not contract_valid or any(row["content_identity_sets_differ"] is None for row in rows)
            else any(bool(row["content_identity_sets_differ"]) for row in rows)
        ),
        "fallback_count": fallback_count,
    }

def evaluate_run(run_dir: Path) -> dict[str, object]:
    result = evaluate_token_run(run_dir)
    events = _load_events(run_dir / "events.jsonl")
    selection = _selection_evidence(events)
    result.update(selection)
    result.update(
        _strict_physical_evidence(
            events,
            require_block_decision=str(result.get("policy")) == "A2",
        )
    )
    return result


def compare_pair(a0: Mapping[str, object], a2: Mapping[str, object]) -> dict[str, object]:
    """Compare one runtime repeat while keeping the three evidence layers distinct."""
    token = compare_token_pair(a0, a2)
    comparable = token["status"] == "COMPARABLE"
    mechanism_realized = bool(a0.get("pressure_release_mechanism_realized")) and bool(
        a2.get("selection_mechanism_realized")
    )
    selection_observable = a2.get("selection_diverged") is not None
    selection_diverged = a2.get("selection_diverged") if selection_observable else None
    physical_observable = (
        comparable
        and a0.get("physical_evidence_observable") is True
        and a2.get("physical_evidence_observable") is True
        and int(a0.get("unmapped_physical_eviction_count", 0)) == 0
        and int(a2.get("unmapped_physical_eviction_count", 0)) == 0
    )
    physical_diverged = (
        a0.get("strict_physical_eviction_signature")
        != a2.get("strict_physical_eviction_signature")
        if physical_observable
        else None
    )
    delta = token.get("token_delta_a1_minus_a0")
    if not comparable:
        state = "INCONCLUSIVE"
    elif not mechanism_realized:
        state = "NOT_REALIZED"
    elif not selection_observable:
        state = "SELECTION_NOT_OBSERVABLE"
    elif not selection_diverged:
        state = "NO_SELECTION_DIVERGENCE"
    elif physical_diverged is None:
        state = "PHYSICAL_NOT_OBSERVABLE"
    elif not physical_diverged:
        state = "NO_PHYSICAL_DIVERGENCE"
    elif int(delta) < 0:
        state = "NATIVE_BENEFIT_OBSERVED"
    elif int(delta) > 0:
        state = "NATIVE_REGRESSION_OBSERVED"
    else:
        state = "NO_TOKEN_DIFFERENCE"
    return {
        "status": token["status"],
        "evidence_state": state,
        "checks": token["checks"],
        "selection_mechanism_realized": mechanism_realized,
        "selection_identity_complete": selection_observable,
        "selection_diverged": selection_diverged,
        "physical_diverged": physical_diverged,
        "physical_evidence_observable": physical_observable,
        "a0_aggregate_recomputed_tokens": token["a0_aggregate_recomputed_tokens"],
        "a2_aggregate_recomputed_tokens": token["a1_aggregate_recomputed_tokens"],
        "a0_aggregate_actual_prefill_tokens": token[
            "a0_aggregate_actual_prefill_tokens"
        ],
        "a2_aggregate_actual_prefill_tokens": token[
            "a1_aggregate_actual_prefill_tokens"
        ],
        "delta_recomputed_tokens_a2_minus_a0": token["token_delta_a1_minus_a0"],
        "delta_actual_prefill_tokens_a2_minus_a0": token[
            "delta_actual_prefill_a1_minus_a0"
        ],
        "delta_new_suffix_tokens_a2_minus_a0": token[
            "delta_new_suffix_a1_minus_a0"
        ],
        "request_completeness": token["request_completeness"],
        "unpaired_request_ids": token["unpaired_request_ids"],
        "metric_equivalence": token["metric_equivalence"],
        "metric_equivalence_reason": token["metric_equivalence_reason"],
    }


def _bootstrap_ci(
    values: Sequence[float], *, repetitions: int = 10_000, seed: int = 20261019
) -> list[float] | None:
    if len(values) < 2:
        return None
    generator = random.Random(seed)
    means = sorted(
        statistics.fmean(generator.choice(values) for _ in values)
        for _ in range(repetitions)
    )
    lower = int(0.025 * repetitions)
    upper = int(0.975 * repetitions) - 1
    return [means[lower], means[upper]]


def aggregate_scenarios(pairs: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for pair in pairs:
        grouped[str(pair["scenario_id"])].append(pair)
    rows: list[dict[str, object]] = []
    for scenario_id, repeats in sorted(grouped.items()):
        comparable = [row for row in repeats if row.get("status") == "COMPARABLE"]
        deltas = [
            float(row["delta_recomputed_tokens_a2_minus_a0"])
            for row in comparable
            if row.get("delta_recomputed_tokens_a2_minus_a0") is not None
        ]
        delta = statistics.fmean(deltas) if len(deltas) == 2 else None
        rows.append(
            {
                "scenario_id": scenario_id,
                "family": repeats[0]["family"],
                "repeat_count": len(repeats),
                "comparable_repeat_count": len(comparable),
                "selection_diverged": (
                    any(row.get("selection_diverged") is True for row in comparable)
                    if comparable
                    else None
                ),
                "physical_diverged": (
                    any(row.get("physical_diverged") is True for row in comparable)
                    if comparable
                    else None
                ),
                "mean_delta_recomputed_tokens_a2_minus_a0": delta,
                "direction": (
                    "BETTER"
                    if delta is not None and delta < 0
                    else "WORSE"
                    if delta is not None and delta > 0
                    else "TIED"
                    if delta == 0
                    else "INCONCLUSIVE"
                ),
                "evidence_state_counts": dict(
                    Counter(str(row["evidence_state"]) for row in repeats)
                ),
            }
        )
    return rows


def _summary(
    rows: Sequence[Mapping[str, object]], *, required_complete_scenarios: int
) -> dict[str, object]:
    values = [
        float(row["mean_delta_recomputed_tokens_a2_minus_a0"])
        for row in rows
        if row.get("mean_delta_recomputed_tokens_a2_minus_a0") is not None
    ]
    complete = len(values) == required_complete_scenarios
    descriptive_mean = statistics.fmean(values) if values else None
    descriptive_median = statistics.median(values) if values else None
    descriptive_ci = _bootstrap_ci(values)
    return {
        "scenario_count": len(rows),
        "comparable_scenario_count": len(values),
        "required_complete_scenario_count": required_complete_scenarios,
        "campaign_completeness_satisfied": complete,
        "formal_verdict": "COMPLETE" if complete else "INCONCLUSIVE",
        "selection_divergence_scenario_count": sum(
            row.get("selection_diverged") is True for row in rows
        ),
        "physical_divergence_scenario_count": sum(
            row.get("physical_diverged") is True for row in rows
        ),
        "better_worse_tied_inconclusive": dict(
            Counter(str(row["direction"]) for row in rows)
        ),
        "formal_mean_delta_recomputed_tokens_a2_minus_a0": (
            descriptive_mean if complete else None
        ),
        "formal_median_delta_recomputed_tokens_a2_minus_a0": (
            descriptive_median if complete else None
        ),
        "formal_exploratory_bootstrap_95_ci": descriptive_ci if complete else None,
        "descriptive_complete_scenarios_only": {
            "mean_delta_recomputed_tokens_a2_minus_a0": descriptive_mean,
            "median_delta_recomputed_tokens_a2_minus_a0": descriptive_median,
            "exploratory_bootstrap_95_ci": descriptive_ci,
            "scope": "predefined_parameter_grid_only_not_a_production_distribution",
        },
        "bootstrap_repetitions": 10_000 if len(values) >= 2 else 0,
        "bootstrap_seed": 20261019 if len(values) >= 2 else None,
    }


def evaluate_campaign(
    *, manifest_path: Path, authorization_path: Path, run_root: Path
) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    authorization = _validate_execution_authorization(
        manifest_path=manifest_path,
        authorization_path=authorization_path,
    )
    runs: list[dict[str, object]] = []
    for entry in manifest["runs"]:
        run_dir = run_root / str(entry["run_id"])
        if not (run_dir / "run.json").is_file():
            runs.append({**entry, "status": "MISSING"})
            continue
        try:
            _validate_run_binding(run_dir, entry, authorization, frozen_root=manifest_path.parent)
            runs.append(evaluate_run(run_dir))
        except Exception as error:  # noqa: BLE001 - preserve invalid evidence
            runs.append(
                {
                    **entry,
                    "status": "INVALID",
                    "error": f"{type(error).__name__}: {error}",
                }
            )
    indexed = {
        (str(row["scenario_id"]), int(row["repeat"]), str(row["policy"])): row
        for row in runs
    }
    pairs: list[dict[str, object]] = []
    for scenario in manifest["scenarios"]:
        scenario_id = str(scenario["scenario_id"])
        for repeat in (1, 2):
            a0 = indexed.get((scenario_id, repeat, "A0"))
            a2 = indexed.get((scenario_id, repeat, "A2"))
            comparison = (
                compare_pair(a0, a2)
                if a0 is not None and a2 is not None
                else {"status": "NOT_COMPARABLE", "evidence_state": "INCONCLUSIVE"}
            )
            pairs.append(
                {
                    "scenario_id": scenario_id,
                    "family": scenario["family"],
                    "repeat": repeat,
                    **comparison,
                }
            )
    scenarios = aggregate_scenarios(pairs)
    return {
        "schema_version": "phase2g.a2_gate2_report.v1",
        "primary_metric": "aggregate_recomputed_tokens",
        "metric_definition": {
            "recomputed_tokens": "E - C",
            "actual_prefill_tokens": "N - C",
            "new_suffix_tokens": "N - E",
        },
        "delta_definition": "A2_MINUS_A0",
        "independent_statistical_unit": "scenario_draw",
        "planned_run_count": len(manifest["runs"]),
        "run_status_counts": dict(Counter(str(row["status"]) for row in runs)),
        "pair_status_counts": dict(Counter(str(row["status"]) for row in pairs)),
        "evidence_state_counts": dict(
            Counter(str(row["evidence_state"]) for row in pairs)
        ),
        "authorization_sha256": _sha(authorization_path),
        "overall": _summary(scenarios, required_complete_scenarios=36),
        "families": {
            family: _summary(
                [row for row in scenarios if row["family"] == family],
                required_complete_scenarios=6,
            )
            for family in ("F1", "F2", "F3", "F4", "F5", "F6")
        },
        "runs": runs,
        "pairs": pairs,
        "scenarios": scenarios,
        "limitations": [
            "Runtime repeats are aggregated within scenario and are not independent samples.",
            "Block-id differences are not content-identity evidence.",
            "Physical eviction correlation is not per-block recomputation causality.",
            "A2 proxy-weighted loss is not actual expected recomputation.",
            (
                "Bootstrap statistics describe only the predefined parameter grid and "
                "are not an estimate for an arbitrary production distribution."
            ),
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = evaluate_campaign(
        manifest_path=args.manifest,
        authorization_path=args.authorization,
        run_root=args.run_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote Phase 2G A2 Gate 2 report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
