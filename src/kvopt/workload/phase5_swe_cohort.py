"""Deterministic Phase 5 SWE cohort-candidate materialization."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping
from typing import Any

from .phase5_replay import canonical_sha256, frozen_poisson_arrival_plan

GROUP_SEED = 20419074
GROUP_DOMAIN = "phase5-swe-group-v1"
POISSON_SEED = 20261201
POISSON_RATE = 0.1
SYSTEMS = (
    "NATIVE",
    "CONTINUUM_OFFICIAL",
    "CONTINUUM_ADAPTED_A0",
    "A1_ORIGINAL",
    "A3_SUFFIX",
    "DVA_ER_V1",
)
EXPECTED_GROUPS = (
    ("django__django-15572", "scikit-learn__scikit-learn-14894", "mwaskom__seaborn-3069", "django__django-11138"),
    ("pydata__xarray-4695", "django__django-11095", "pylint-dev__pylint-4551", "sympy__sympy-18199"),
    ("django__django-15741", "sympy__sympy-13974", "django__django-11880", "matplotlib__matplotlib-25311"),
    ("sympy__sympy-21596", "django__django-13212", "django__django-13513", "pytest-dev__pytest-7982"),
    ("scikit-learn__scikit-learn-25747", "django__django-12209", "django__django-14373", "sphinx-doc__sphinx-8721"),
    ("django__django-16032", "django__django-13023", "sympy__sympy-15017", "matplotlib__matplotlib-25287"),
    ("sympy__sympy-20801", "django__django-15554", "psf__requests-2931", "django__django-16662"),
    ("django__django-13569", "sympy__sympy-12419", "matplotlib__matplotlib-26466", "django__django-14011"),
    ("pydata__xarray-3305", "django__django-14493", "sympy__sympy-22714", "django__django-14170"),
    ("django__django-11790", "sympy__sympy-16886", "django__django-15569", "matplotlib__matplotlib-14623"),
    ("psf__requests-2317", "sympy__sympy-13551", "django__django-12276", "django__django-12050"),
    ("pytest-dev__pytest-8399", "django__django-13933", "django__django-16901", "pydata__xarray-3095"),
)


class SWECohortError(ValueError):
    """Raised when frozen cohort identity or construction drifts."""


def _sealed(payload: dict[str, object], field: str) -> dict[str, object]:
    return {**payload, field: canonical_sha256(payload)}


def _repo(program_id: str) -> str:
    if "__" not in program_id:
        raise SWECohortError("Program identity lacks repository delimiter")
    return program_id.split("__", 1)[0]


def _key(program_id: str) -> str:
    value = f"{GROUP_DOMAIN}|{GROUP_SEED}|{program_id}".encode()
    return hashlib.sha256(value).hexdigest()


def materialize_swe_cohort(
    *, inventory: Mapping[str, Any], lineage_bindings: Mapping[str, str]
) -> dict[str, dict[str, object]]:
    """Build all frozen candidate manifests without issuing a Workload Seal."""

    old = inventory.get("existing_qualified_programs")
    fresh = inventory.get("fresh_qualified_programs")
    if not isinstance(old, list) or not isinstance(fresh, list):
        raise SWECohortError("combined inventory rows are missing")
    rows = [({**row, "provenance_partition": "EXISTING_PHASE5"}) for row in old]
    rows += [({**row, "provenance_partition": "FRESH_REACQUISITION"}) for row in fresh]
    if len(rows) != 48:
        raise SWECohortError("cohort source must contain exactly 48 Programs")
    by_id = {str(row["program_id"]): row for row in rows}
    if len(by_id) != 48:
        raise SWECohortError("Program identities are not unique")
    ordered = sorted(by_id, key=lambda value: (_key(value), value))
    computed = tuple(tuple(ordered[i : i + 4]) for i in range(0, 48, 4))
    if computed != EXPECTED_GROUPS:
        raise SWECohortError("computed membership differs from M1 frozen membership")

    master = frozen_poisson_arrival_plan(
        ordered, rate_per_second=POISSON_RATE, seed=POISSON_SEED
    )
    group_rows = []
    arrival_rows = []
    for index, ids in enumerate(computed, start=1):
        group_id = f"SWE_G{index:02d}"
        role = "CALIBRATION" if index <= 4 else "FORMAL_CANDIDATE"
        members = []
        for ordinal, program_id in enumerate(ids, start=1):
            source = by_id[program_id]
            members.append(
                {
                    "ordinal": ordinal,
                    "program_id": program_id,
                    "session_id": source["session_id"],
                    "trace_id": source["trace_id"],
                    "repository_id": _repo(program_id),
                    "provenance_partition": source["provenance_partition"],
                    "terminal_class": source["terminal_class"],
                    "censor_reason": source.get("censor_reason"),
                    "qualification_sha256": source["qualification_sha256"],
                    "raw_artifact_sha256": source["raw_artifact_sha256"],
                    "source_trace_sha256": source["source_trace_sha256"],
                    "token_materialization_file_sha256": source[
                        "token_materialization_file_sha256"
                    ],
                }
            )
        repo_counts = Counter(row["repository_id"] for row in members)
        if len(repo_counts) < 3 or max(repo_counts.values()) > 2:
            raise SWECohortError(f"repository diversity failed for {group_id}")
        group_rows.append(
            {
                "group_id": group_id,
                "role": role,
                "members": members,
                "repository_counts": dict(sorted(repo_counts.items())),
                "group_content_sha256": canonical_sha256(members),
            }
        )
        starts = master.starts[(index - 1) * 4 : index * 4]
        base = starts[0].start_offset_seconds
        local = [
            {
                "ordinal": ordinal,
                "program_id": row.program_id,
                "start_offset_seconds": row.start_offset_seconds - base,
            }
            for ordinal, row in enumerate(starts, start=1)
        ]
        arrival_rows.append(
            {
                "group_id": group_id,
                "starts": local,
                "schedule_sha256": canonical_sha256(local),
            }
        )

    group_payload = {
        "schema_version": "phase5.swe_group_manifest.v1",
        "status": "CANDIDATE_GROUPS_MATERIALIZED_PENDING_M4_REVIEW",
        "group_seed": GROUP_SEED,
        "hash_domain": GROUP_DOMAIN,
        "sort_rule": "SHA256_KEY_ASC_THEN_PROGRAM_ID_ASC",
        "groups": group_rows,
        "calibration_groups_constructed": True,
        "formal_candidate_groups_constructed": True,
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
    }
    groups = _sealed(group_payload, "group_manifest_content_sha256")
    arrivals_payload = {
        "schema_version": "phase5.swe_frozen_poisson_arrivals.v1",
        "arrival_mode": "FROZEN_POISSON",
        "program_start_rate_per_second": POISSON_RATE,
        "master_seed": POISSON_SEED,
        "generator": "PYTHON_RANDOM_MT19937_EXPONENTIAL_V1",
        "derivation": "ONE_48_PROGRAM_STREAM_SLICE_4_AND_SUBTRACT_GROUP_FIRST",
        "master_plan_sha256": master.sha256,
        "groups": arrival_rows,
        "reuse_contract": {
            "systems": list(SYSTEMS),
            "all_repeats": True,
            "per_system_resampling_allowed": False,
            "per_repeat_resampling_allowed": False,
        },
    }
    arrivals = _sealed(arrivals_payload, "arrival_manifest_content_sha256")

    calibration = _child("CALIBRATION", group_rows[:4], groups, arrivals)
    formal = _child("FORMAL_CANDIDATE", group_rows[4:], groups, arrivals)
    cal_programs = {m["program_id"] for g in group_rows[:4] for m in g["members"]}
    formal_programs = {m["program_id"] for g in group_rows[4:] for m in g["members"]}
    cal_sessions = {m["session_id"] for g in group_rows[:4] for m in g["members"]}
    formal_sessions = {m["session_id"] for g in group_rows[4:] for m in g["members"]}
    disjoint_payload = {
        "schema_version": "phase5.swe_cohort_disjointness.v1",
        "status": "PASS",
        "program_overlap": sorted(cal_programs & formal_programs),
        "session_overlap": sorted(cal_sessions & formal_sessions),
        "group_overlap": [],
        "all_48_programs_exactly_once": len(cal_programs | formal_programs) == 48,
    }
    disjoint = _sealed(disjoint_payload, "disjointness_content_sha256")
    diversity_payload = {
        "schema_version": "phase5.swe_repository_diversity.v1",
        "status": "PASS",
        "min_distinct_repositories": 3,
        "max_programs_per_repository_per_group": 2,
        "groups": [
            {
                "group_id": g["group_id"],
                "repository_counts": g["repository_counts"],
                "status": "PASS",
            }
            for g in group_rows
        ],
    }
    diversity = _sealed(diversity_payload, "diversity_content_sha256")
    outcome_payload = {
        "schema_version": "phase5.swe_outcome_blind_audit.v1",
        "status": "PASS",
        "consumed_fields": ["program_id", "session_id", "identity/evidence hashes", "terminal classification", "provenance partition"],
        "prohibited_outcome_fields_consumed": [],
        "algorithm": "FROZEN_SHA256_SORT_AND_CONSECUTIVE_PARTITION",
    }
    outcome = _sealed(outcome_payload, "outcome_blind_content_sha256")
    terminals = Counter(row["terminal_class"] for row in rows)
    stats_payload = {
        "schema_version": "phase5.swe_group_statistics.v1",
        "group_count": 12,
        "calibration_group_count": 4,
        "formal_candidate_group_count": 8,
        "program_count": 48,
        "repository_counts": dict(sorted(Counter(_repo(x) for x in by_id).items())),
        "terminal_class_counts": dict(sorted(terminals.items())),
        "right_censoring_primary_rule": "VALID_OBSERVED_TURNS_ONLY",
        "right_censoring_sensitivity_rule": "EXCLUDE_RIGHT_CENSORED_SESSIONS",
    }
    stats = _sealed(stats_payload, "statistics_content_sha256")
    combined_payload = {
        "schema_version": "phase5.swe_combined_cohort_candidate.v1",
        "status": "READY_FOR_M4_TARGETED_REVIEW",
        "lineage_bindings": dict(sorted(lineage_bindings.items())),
        "group_manifest_content_sha256": groups["group_manifest_content_sha256"],
        "arrival_manifest_content_sha256": arrivals["arrival_manifest_content_sha256"],
        "calibration_child_content_sha256": calibration["child_content_sha256"],
        "formal_child_content_sha256": formal["child_content_sha256"],
        "disjointness_content_sha256": disjoint["disjointness_content_sha256"],
        "diversity_content_sha256": diversity["diversity_content_sha256"],
        "outcome_blind_content_sha256": outcome["outcome_blind_content_sha256"],
        "statistics_content_sha256": stats["statistics_content_sha256"],
        "formal_cohort_selected": False,
        "workload_seal_issued": False,
        "gpu_execution_authorized": False,
    }
    combined = _sealed(combined_payload, "combined_candidate_content_sha256")
    seal_payload = {
        "schema_version": "phase5.swe_workload_seal_input.v1",
        "status": "INPUT_READY_PENDING_M4_AND_M1_ACCEPTANCE",
        "combined_candidate_content_sha256": combined[
            "combined_candidate_content_sha256"
        ],
        "workload_seal_issued": False,
        "m1_acceptance_required": True,
        "gpu_execution_authorized": False,
    }
    seal_input = _sealed(seal_payload, "seal_input_content_sha256")
    outputs = {
        "swe-group-manifest.json": groups,
        "swe-calibration-child-manifest.json": calibration,
        "swe-formal-candidate-child-manifest.json": formal,
        "swe-frozen-poisson-arrival-manifest.json": arrivals,
        "swe-cohort-disjointness-validation.json": disjoint,
        "swe-repository-diversity-validation.json": diversity,
        "swe-outcome-blind-audit.json": outcome,
        "swe-group-statistics-summary.json": stats,
        "swe-combined-cohort-candidate-manifest.json": combined,
        "swe-workload-seal-input-bundle.json": seal_input,
    }
    validate_swe_cohort(outputs)
    return outputs


def _child(role: str, groups: list[dict[str, object]], parent: Mapping[str, Any], arrivals: Mapping[str, Any]) -> dict[str, object]:
    payload = {
        "schema_version": "phase5.swe_child_manifest.v1",
        "role": role,
        "groups": groups,
        "parent_group_manifest_content_sha256": parent["group_manifest_content_sha256"],
        "arrival_manifest_content_sha256": arrivals["arrival_manifest_content_sha256"],
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
    }
    return _sealed(payload, "child_content_sha256")


def validate_swe_cohort(outputs: Mapping[str, Mapping[str, Any]]) -> None:
    """Fail closed on hashes, counts, membership, or authorization drift."""
    for value in outputs.values():
        fields = [key for key in value if key.endswith("_content_sha256")]
        own = fields[-1]
        content = dict(value)
        observed = content.pop(own)
        if observed != canonical_sha256(content):
            raise SWECohortError(f"{own} mismatch")
    groups = outputs["swe-group-manifest.json"]["groups"]
    ids = [m["program_id"] for g in groups for m in g["members"]]
    if tuple(tuple(ids[i : i + 4]) for i in range(0, 48, 4)) != EXPECTED_GROUPS:
        raise SWECohortError("validated membership differs from frozen membership")
    if len(ids) != 48 or len(set(ids)) != 48:
        raise SWECohortError("Programs are not exactly-once independent members")
    if any(
        value.get("gpu_execution_authorized") is not False
        for value in outputs.values()
        if "gpu_execution_authorized" in value
    ):
        raise SWECohortError("cohort package exceeds GPU authorization")
