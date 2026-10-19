"""Evaluate execution-authorized Phase 2G A0/A2 Gate 2 Native evidence.

This module defines the frozen offline analysis before any formal outcomes exist.
It reuses the corrected Level-B token derivation and keeps selection, physical
eviction, and request-level recomputation as separate evidence layers.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

from .phase2g_a1_bounded_gate import compare_pair as compare_token_pair
from .phase2g_a1_bounded_gate import evaluate_run as evaluate_token_run
from .phase2g_a2_gate1 import _decision_identities, _event_index, _payload


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


def _selection_evidence(events: Sequence[Mapping[str, object]]) -> dict[str, object]:
    forced = [row for row in events if row.get("event_type") == "FORCED_RELEASE_DECISION"]
    decisions = [row for row in events if row.get("event_type") == "COST_AWARE_BLOCK_DECISION"]
    rows: list[dict[str, object]] = []
    for decision in decisions:
        payload = _payload(decision)
        identities = _decision_identities(events, decision)
        selected = tuple(int(value) for value in payload.get("selected_victims", ()))
        native = tuple(int(value) for value in payload.get("native_lru_victims", ()))
        selected_identity = _identity_set(identities, selected)
        native_identity = _identity_set(identities, native)
        identity_complete = selected_identity is not None and native_identity is not None
        rows.append(
            {
                "event_index": _event_index(decision),
                "required_blocks": int(payload.get("required_blocks", 0)),
                "selected_victim_count": len(selected),
                "native_lru_victim_count": len(native),
                "block_id_sets_differ": set(selected) != set(native),
                "identity_complete": identity_complete,
                "selected_content_identities": selected_identity,
                "native_lru_content_identities": native_identity,
                "content_identity_sets_differ": (
                    set(selected_identity) != set(native_identity)
                    if identity_complete
                    else None
                ),
                "selector": payload.get("selector"),
                "fallbacks": payload.get("fallbacks", []),
                "adapter_problems": payload.get("adapter_problems", []),
                "contract_problems": payload.get("contract_problems", []),
            }
        )
    observable = [row for row in rows if row["identity_complete"]]
    return {
        "forced_release_count": len(forced),
        "block_decision_count": len(decisions),
        "decision_rows": rows,
        "selection_mechanism_realized": bool(forced and decisions),
        "selection_identity_complete": len(observable) == len(rows) and bool(rows),
        "selection_diverged": (
            any(bool(row["content_identity_sets_differ"]) for row in observable)
            if len(observable) == len(rows) and rows
            else None
        ),
        "fallback_count": sum(bool(row["fallbacks"]) for row in rows),
    }


def evaluate_run(run_dir: Path) -> dict[str, object]:
    result = evaluate_token_run(run_dir)
    events = _load_events(run_dir / "events.jsonl")
    selection = _selection_evidence(events)
    result.update(selection)
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
    physical_diverged = (
        a0.get("physical_eviction_signature") != a2.get("physical_eviction_signature")
        if comparable
        and a0.get("physical_eviction_count")
        and a2.get("physical_eviction_count")
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


def _summary(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    values = [
        float(row["mean_delta_recomputed_tokens_a2_minus_a0"])
        for row in rows
        if row.get("mean_delta_recomputed_tokens_a2_minus_a0") is not None
    ]
    return {
        "scenario_count": len(rows),
        "comparable_scenario_count": len(values),
        "selection_divergence_scenario_count": sum(
            row.get("selection_diverged") is True for row in rows
        ),
        "physical_divergence_scenario_count": sum(
            row.get("physical_diverged") is True for row in rows
        ),
        "better_worse_tied_inconclusive": dict(
            Counter(str(row["direction"]) for row in rows)
        ),
        "mean_delta_recomputed_tokens_a2_minus_a0": (
            statistics.fmean(values) if values else None
        ),
        "median_delta_recomputed_tokens_a2_minus_a0": (
            statistics.median(values) if values else None
        ),
        "exploratory_bootstrap_95_ci": _bootstrap_ci(values),
        "bootstrap_repetitions": 10_000 if len(values) >= 2 else 0,
        "bootstrap_seed": 20261019 if len(values) >= 2 else None,
    }


def evaluate_campaign(*, manifest_path: Path, run_root: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("execution_authorized") is not True:
        raise ValueError("refusing to evaluate an execution-locked Gate 2 manifest")
    runs: list[dict[str, object]] = []
    for entry in manifest["runs"]:
        run_dir = run_root / str(entry["run_id"])
        if not (run_dir / "run.json").is_file():
            runs.append({**entry, "status": "MISSING"})
            continue
        try:
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
        "overall": _summary(scenarios),
        "families": {
            family: _summary([row for row in scenarios if row["family"] == family])
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
    print(f"wrote Phase 2G A2 Gate 2 report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
