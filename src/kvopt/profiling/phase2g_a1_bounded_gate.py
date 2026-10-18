"""Evaluate paired Phase 2G A0/A1 native bounded evidence."""

from __future__ import annotations

import argparse
import json
import random
import statistics
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

from .ingestion import load_run_artifacts
from .phase2e_fidelity import _materialized_digests
from .phase2g_a1_metric import RequestTokenFacts, request_token_facts

EVIDENCE_STATES = frozenset(
    {
        "NO_SELECTION_DIVERGENCE",
        "NO_PHYSICAL_DIVERGENCE",
        "NOT_REALIZED",
        "NATIVE_BENEFIT_OBSERVED",
        "NATIVE_REGRESSION_OBSERVED",
        "NO_TOKEN_DIFFERENCE",
        "INCONCLUSIVE",
    }
)


def _event_rows(run: object, event_type: str) -> list[dict[str, object]]:
    return [
        row
        for row in run.events  # type: ignore[attr-defined]
        if row.get("event_type") == event_type
    ]


def _turn_index(request_id: str) -> int | None:
    try:
        return int(request_id.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return None


def evaluate_run(run_dir: Path) -> dict[str, object]:
    run = load_run_artifacts(run_dir)
    config = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    stage = config["phase2g_stage"]
    forced = _event_rows(run, "FORCED_RELEASE_DECISION")
    native = _event_rows(run, "VLLM_NATIVE_REQUEST_OBSERVATION")
    evictions = _event_rows(run, "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED")
    selections = [
        [
            str(release["program_id"])
            for release in row.get("payload", {}).get("selected_releases", [])
        ]
        for row in forced
    ]
    observations: dict[str, dict[str, object]] = {}
    hash_identity: dict[str, tuple[str, int]] = {}
    for row in native:
        request_id = str(row.get("request_id"))
        payload = row.get("payload", {})
        for position, block_hash in enumerate(payload.get("native_apc_block_hashes", [])):
            hash_identity[str(block_hash)] = (str(row.get("program_id")), position)

    # Token facts come from the frozen Level-B derivation, never from a local
    # re-derivation: N - C is actual prefill, while the frozen recomputation
    # metric is E - C. See phase2g_a1_metric for why that distinction matters.
    facts: dict[str, RequestTokenFacts] = request_token_facts([run])
    for request_id, fact in facts.items():
        observations[request_id] = {
            "program_id": fact.program_id,
            "prompt_tokens": fact.prompt_tokens,
            "eligible_prefix_tokens": fact.eligible_prefix_tokens,
            "cached_prefix_tokens": fact.cached_prefix_tokens,
            "actual_prefill_tokens": fact.actual_prefill_tokens,
            "recomputed_tokens": fact.recomputed_tokens,
            "new_suffix_tokens": fact.new_suffix_tokens,
        }
    physical_signature: list[tuple[str, int]] = []
    unmapped_evictions = 0
    for row in evictions:
        key = str(row.get("payload", {}).get("native_cache_key_before", ""))
        matches = [
            identity for block_hash, identity in hash_identity.items() if key.startswith(block_hash)
        ]
        if len(matches) == 1:
            physical_signature.append(matches[0])
        else:
            unmapped_evictions += 1
    eligible = {
        request_id: row
        for request_id, row in observations.items()
        if not request_id.startswith("pressure:") and (_turn_index(request_id) or 0) > 1
    }
    checks = {
        "execution_success": run.manifest.get("execution_status") == "success",
        "clean_git": run.manifest.get("git_dirty") is False,
        "native_request_evidence_present": bool(native),
        "all_native_counts_nonnegative": all(
            int(row["recomputed_tokens"]) >= 0 for row in observations.values()
        ),
    }
    return {
        "run_id": run.run_id,
        "scenario_id": stage["scenario_id"],
        "family": stage["family"],
        "policy": stage["policy"],
        "repeat": int(stage["repeat"]),
        "status": "VALID" if all(checks.values()) else "INVALID",
        "checks": checks,
        "git_sha": run.manifest.get("git_sha"),
        "trace_sha256": run.manifest.get("trace_sha256"),
        "request_ids": sorted(str(row.get("request_id")) for row in run.replay),
        "materialized_token_digests": _materialized_digests(run),
        "pairing_config": {
            "model": config.get("model"),
            "tokenizer": config.get("tokenizer"),
            "generation": config.get("generation"),
            "batching": config.get("batching"),
            "cache": config.get("cache"),
            "seed": config.get("seed"),
            "trace": config.get("trace"),
            "backend_revision": config.get("backend_revision"),
        },
        "selection_sequence": selections,
        "pressure_release_mechanism_realized": bool(forced),
        "physical_eviction_count": len(evictions),
        "physical_eviction_signature": sorted(physical_signature),
        "unmapped_physical_eviction_count": unmapped_evictions,
        "eligible_request_count": len(eligible),
        "aggregate_recomputed_tokens": sum(
            int(row["recomputed_tokens"]) for row in eligible.values()
        ),
        "aggregate_actual_prefill_tokens": sum(
            int(row["actual_prefill_tokens"]) for row in eligible.values()
        ),
        "aggregate_new_suffix_tokens": sum(
            int(row["new_suffix_tokens"]) for row in eligible.values()
        ),
        "metric_definition": {
            "actual_prefill_tokens": "N - C",
            "recomputed_tokens": "E - C",
            "new_suffix_tokens": "N - E",
            "derived_by": "runtime_evidence.derive_level_b_token_semantics",
        },
        "request_outcomes": eligible,
    }


def _delta(a0: Mapping[str, object], a1: Mapping[str, object], key: str) -> int | None:
    """Difference of one aggregate, or ``None`` when either side lacks the key."""
    left, right = a0.get(key), a1.get(key)
    if left is None or right is None:
        return None
    return int(right) - int(left)


def compare_pair(
    a0: Mapping[str, object],
    a1: Mapping[str, object],
) -> dict[str, object]:
    checks = {
        "both_valid": a0.get("status") == a1.get("status") == "VALID",
        "same_scenario_repeat": (a0.get("scenario_id"), a0.get("repeat"))
        == (a1.get("scenario_id"), a1.get("repeat")),
        "same_git_sha": bool(a0.get("git_sha")) and a0.get("git_sha") == a1.get("git_sha"),
        "same_trace": bool(a0.get("trace_sha256"))
        and a0.get("trace_sha256") == a1.get("trace_sha256"),
        "same_requests": bool(a0.get("request_ids"))
        and a0.get("request_ids") == a1.get("request_ids"),
        "same_materialized_tokens": bool(a0.get("materialized_token_digests"))
        and a0.get("materialized_token_digests") == a1.get("materialized_token_digests"),
        "same_runtime_config": a0.get("pairing_config") == a1.get("pairing_config"),
    }
    if not all(checks.values()):
        state = "INCONCLUSIVE"
    elif not a0.get("pressure_release_mechanism_realized") or not a1.get(
        "pressure_release_mechanism_realized"
    ):
        state = "NOT_REALIZED"
    elif a0.get("selection_sequence") == a1.get("selection_sequence"):
        state = "NO_SELECTION_DIVERGENCE"
    elif not a0.get("physical_eviction_count") or not a1.get("physical_eviction_count"):
        state = "NOT_REALIZED"
    elif a0.get("physical_eviction_signature") == a1.get("physical_eviction_signature"):
        state = "NO_PHYSICAL_DIVERGENCE"
    else:
        delta = int(a1["aggregate_recomputed_tokens"]) - int(a0["aggregate_recomputed_tokens"])
        if delta < 0:
            state = "NATIVE_BENEFIT_OBSERVED"
        elif delta > 0:
            state = "NATIVE_REGRESSION_OBSERVED"
        else:
            state = "NO_TOKEN_DIFFERENCE"
    return {
        "status": "COMPARABLE" if all(checks.values()) else "NOT_COMPARABLE",
        "evidence_state": state,
        "checks": checks,
        "selection_diverged": a0.get("selection_sequence") != a1.get("selection_sequence"),
        "physical_diverged": a0.get("physical_eviction_signature")
        != a1.get("physical_eviction_signature"),
        "a0_aggregate_recomputed_tokens": a0.get("aggregate_recomputed_tokens"),
        "a1_aggregate_recomputed_tokens": a1.get("aggregate_recomputed_tokens"),
        "a0_aggregate_actual_prefill_tokens": a0.get("aggregate_actual_prefill_tokens"),
        "a1_aggregate_actual_prefill_tokens": a1.get("aggregate_actual_prefill_tokens"),
        "token_delta_a1_minus_a0": (
            _delta(a0, a1, "aggregate_recomputed_tokens") if all(checks.values()) else None
        ),
        "delta_actual_prefill_a1_minus_a0": (
            _delta(a0, a1, "aggregate_actual_prefill_tokens")
            if all(checks.values())
            else None
        ),
        "delta_new_suffix_a1_minus_a0": (
            _delta(a0, a1, "aggregate_new_suffix_tokens") if all(checks.values()) else None
        ),
        **_metric_equivalence(a0, a1, checks),
    }


def _metric_equivalence(
    a0: Mapping[str, object],
    a1: Mapping[str, object],
    checks: Mapping[str, object],
) -> dict[str, object]:
    """State whether the actual-prefill delta equals the frozen recomputation delta.

    The two coincide when every paired request has identical ``(N, E)``, because
    ``N - C = (E - C) + (N - E)`` and only the last term can then differ. Rather
    than assume that, this measures it per request and records the verdict next to
    the numbers it describes.
    """
    a0_rows = a0.get("request_outcomes") or {}
    a1_rows = a1.get("request_outcomes") or {}
    if not a0_rows and not a1_rows:
        return {
            "request_completeness": "NO_ELIGIBLE_REQUESTS",
            "unpaired_request_ids": [],
            "new_suffix_identical_across_arms": None,
            "metric_equivalence": "NOT_COMPUTABLE",
            "metric_equivalence_reason": (
                "no eligible follow-up requests were observed in either arm"
            ),
        }
    paired = sorted(set(a0_rows) & set(a1_rows))
    unpaired = sorted(set(a0_rows) ^ set(a1_rows))

    if unpaired:
        return {
            "request_completeness": "UNPAIRED",
            "unpaired_request_ids": unpaired,
            "new_suffix_identical_across_arms": None,
            "metric_equivalence": "NOT_COMPUTABLE",
            "metric_equivalence_reason": (
                "eligible request populations differ between arms; a delta across "
                "different populations is not a paired comparison"
            ),
        }

    differing = [
        request_id
        for request_id in paired
        if int(a0_rows[request_id]["new_suffix_tokens"])
        != int(a1_rows[request_id]["new_suffix_tokens"])
    ]
    identical = not differing
    delta_r = _delta(a0, a1, "aggregate_recomputed_tokens") if all(checks.values()) else None
    delta_w = (
        _delta(a0, a1, "aggregate_actual_prefill_tokens") if all(checks.values()) else None
    )
    return {
        "request_completeness": "COMPLETE",
        "unpaired_request_ids": [],
        "paired_eligible_request_count": len(paired),
        "new_suffix_identical_across_arms": identical,
        "new_suffix_differing_request_ids": differing,
        "metric_equivalence": "EXACT" if identical else "NOT_EQUIVALENT",
        "metric_equivalence_reason": (
            "identical (N, E) for every paired request, so delta(new_suffix) = 0 "
            "and delta(actual_prefill) = delta(recomputed) exactly"
            if identical
            else "new-suffix tokens differ for some requests, so the two metrics "
            "give different deltas and both must be reported"
        ),
        "delta_difference_actual_prefill_minus_recomputed": (
            None if delta_r is None or delta_w is None else delta_w - delta_r
        ),
    }


def _bootstrap_ci(values: Sequence[float]) -> list[float] | None:
    if len(values) < 2:
        return None
    generator = random.Random(20261107)
    means = sorted(
        statistics.fmean(generator.choice(values) for _ in values) for _ in range(10_000)
    )
    return [means[249], means[9749]]


def _aggregate_scenarios(pairs: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for pair in pairs:
        grouped[str(pair["scenario_id"])].append(pair)
    rows: list[dict[str, object]] = []
    for scenario_id, repeats in sorted(grouped.items()):
        comparable = [row for row in repeats if row["status"] == "COMPARABLE"]
        deltas = [float(row["token_delta_a1_minus_a0"]) for row in comparable]
        delta = statistics.fmean(deltas) if len(comparable) == 2 else None
        state_counts = Counter(str(row["evidence_state"]) for row in repeats)
        rows.append(
            {
                "scenario_id": scenario_id,
                "family": repeats[0]["family"],
                "repeat_count": len(repeats),
                "comparable_repeat_count": len(comparable),
                "evidence_state_counts": dict(state_counts),
                "selection_diverged": any(bool(row["selection_diverged"]) for row in comparable),
                "physical_diverged": any(bool(row["physical_diverged"]) for row in comparable),
                "mean_token_delta_a1_minus_a0": delta,
                "mean_actual_prefill_delta_a1_minus_a0": (
                    statistics.fmean(
                        float(row["delta_actual_prefill_a1_minus_a0"])
                        for row in comparable
                        if row.get("delta_actual_prefill_a1_minus_a0") is not None
                    )
                    if len(comparable) == 2
                    and all(
                        row.get("delta_actual_prefill_a1_minus_a0") is not None
                        for row in comparable
                    )
                    else None
                ),
                "metric_equivalence": sorted(
                    {str(row.get("metric_equivalence")) for row in comparable}
                ),
                "direction": (
                    "BETTER"
                    if delta is not None and delta < 0
                    else "WORSE"
                    if delta is not None and delta > 0
                    else "TIED"
                    if delta == 0
                    else "INCONCLUSIVE"
                ),
            }
        )
    return rows


def _summary(rows: Sequence[dict[str, object]]) -> dict[str, object]:
    valid = [row for row in rows if row["mean_token_delta_a1_minus_a0"] is not None]
    values = [float(row["mean_token_delta_a1_minus_a0"]) for row in valid]
    return {
        "scenario_count": len(rows),
        "comparable_scenario_count": len(valid),
        "selection_divergence_scenario_count": sum(
            bool(row["selection_diverged"]) for row in valid
        ),
        "physical_divergence_scenario_count": sum(bool(row["physical_diverged"]) for row in valid),
        "better_worse_tied_inconclusive": dict(Counter(str(row["direction"]) for row in rows)),
        "mean_token_delta_a1_minus_a0": statistics.fmean(values) if values else None,
        "median_token_delta_a1_minus_a0": statistics.median(values) if values else None,
        "exploratory_bootstrap_95_ci": _bootstrap_ci(values),
        "bootstrap_replicates": 10_000 if len(values) >= 2 else 0,
        "bootstrap_seed": 20261107 if len(values) >= 2 else None,
    }


def evaluate_campaign(*, manifest_path: Path, run_root: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    runs: list[dict[str, object]] = []
    for entry in manifest["runs"]:
        run_dir = run_root / str(entry["run_id"])
        if not (run_dir / "run.json").is_file():
            runs.append({**entry, "status": "MISSING"})
            continue
        try:
            runs.append(evaluate_run(run_dir))
        except Exception as error:  # noqa: BLE001 - retain invalid evidence
            runs.append({**entry, "status": "INVALID", "error": f"{type(error).__name__}: {error}"})
    indexed = {
        (str(row["scenario_id"]), int(row["repeat"]), str(row["policy"])): row for row in runs
    }
    pairs: list[dict[str, object]] = []
    for scenario in manifest["scenarios"]:
        scenario_id = str(scenario["scenario_id"])
        for repeat in (1, 2):
            a0 = indexed.get((scenario_id, repeat, "A0"))
            a1 = indexed.get((scenario_id, repeat, "A1"))
            comparison = (
                compare_pair(a0, a1)
                if a0 is not None and a1 is not None
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
    scenarios = _aggregate_scenarios(pairs)
    by_family = {
        family: _summary([row for row in scenarios if row["family"] == family])
        for family in ("F1", "F2", "F3", "F4", "F5", "F6")
    }
    return {
        "schema_version": "phase2g.a1_bounded_gate.v1",
        "primary_metric": "aggregate_recomputed_tokens",
        "metric_definition": {
            "actual_prefill_tokens": "N - C",
            "recomputed_tokens": "E - C",
            "new_suffix_tokens": "N - E",
            "note": (
                "Gate 2 previously reported N - C under both metric names; this "
                "report computes the frozen recomputation metric E - C and records "
                "per-pair whether the two deltas coincide"
            ),
        },
        "delta_definition": "A1_MINUS_A0",
        "independent_statistical_unit": "scenario_draw",
        "planned_run_count": len(manifest["runs"]),
        "run_status_counts": dict(Counter(str(row["status"]) for row in runs)),
        "pair_status_counts": dict(Counter(str(row["status"]) for row in pairs)),
        "evidence_state_counts": dict(Counter(str(row["evidence_state"]) for row in pairs)),
        "metric_equivalence_counts": dict(
            Counter(str(row.get("metric_equivalence")) for row in pairs)
        ),
        "request_completeness_counts": dict(
            Counter(str(row.get("request_completeness")) for row in pairs)
        ),
        "overall": _summary(scenarios),
        "families": by_family,
        "runs": runs,
        "pairs": pairs,
        "scenarios": scenarios,
        "limitations": [
            "Runtime repeats are aggregated within scenario and are not independent samples.",
            "Logical release, physical eviction, and recomputation are separate evidence layers.",
            "Mapped block identity is observational and does not modify native ownership.",
            (
                "metric_equivalence is measured per pair; NOT_EQUIVALENT means the two "
                "candidate metrics disagree and both deltas are reported."
            ),
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = evaluate_campaign(manifest_path=args.manifest, run_root=args.run_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote Phase 2G A1 bounded gate: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
