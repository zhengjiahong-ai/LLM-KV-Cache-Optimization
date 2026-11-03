"""Deterministically preregister the Phase 3 Primary and Reserve cohort."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

from .continuum_w1c_sampling import _allocate_quotas

PRIMARY_COUNT = 40
RESERVE_COUNT = 24
MINIMUM_REPOSITORIES = 10
DEFAULT_SEED = 20261103


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _rank(rows: Sequence[dict[str, object]], *, seed: int, label: str) -> list[dict[str, object]]:
    ordered = sorted(
        rows,
        key=lambda row: (
            int(row["problem_statement_char_count"]),
            str(row["instance_id"]),
        ),
    )
    strata: dict[int, list[dict[str, object]]] = defaultdict(list)
    for index, row in enumerate(ordered):
        strata[min(3, (index * 4) // len(ordered))].append(row)
    ranked_strata: dict[int, list[dict[str, object]]] = {}
    for stratum, values in strata.items():
        ranked_strata[stratum] = sorted(
            values,
            key=lambda row: hashlib.sha256(
                f"{seed}:{label}:Q{stratum + 1}:{row['instance_id']}".encode()
            ).hexdigest(),
        )
    result: list[dict[str, object]] = []
    position = 0
    while any(position < len(values) for values in ranked_strata.values()):
        for stratum in sorted(ranked_strata):
            values = ranked_strata[stratum]
            if position < len(values):
                result.append(values[position])
        position += 1
    return result


def _round_robin(rows_by_repo: Mapping[str, Sequence[dict[str, object]]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    position = 0
    while any(position < len(rows) for rows in rows_by_repo.values()):
        for repository in sorted(rows_by_repo):
            rows = rows_by_repo[repository]
            if position < len(rows):
                result.append(rows[position])
        position += 1
    return result


def _identity(row: Mapping[str, object]) -> dict[str, object]:
    return {
        key: row[key]
        for key in (
            "instance_id",
            "repository",
            "base_commit",
            "created_at",
            "difficulty",
            "problem_statement_char_count",
            "problem_statement_word_count",
            "problem_statement_sha256",
        )
    }


def build_candidate_plan(
    sample_freeze: Mapping[str, object],
    *,
    source_sha256: str,
    seed: int = DEFAULT_SEED,
) -> dict[str, object]:
    """Build the immutable 40 Primary + 24 Reserve acquisition plan."""

    if sample_freeze.get("schema_version") != (
        "continuum.w1c_stratified_sample_freeze.v1"
    ):
        raise ValueError("unsupported W1-C sampling freeze")
    raw_tasks = sample_freeze.get("selected_tasks")
    pilot_ids = sample_freeze.get("pilot_instance_ids")
    if not isinstance(raw_tasks, list) or not isinstance(pilot_ids, list):
        raise TypeError("W1-C freeze tasks and pilot IDs must be arrays")
    pilot_set = {str(value) for value in pilot_ids}
    candidates = [
        dict(row)
        for row in raw_tasks
        if isinstance(row, dict)
        and str(row.get("instance_id")) not in pilot_set
        and row.get("pilot_selected") is False
    ]
    identities = [str(row.get("instance_id")) for row in candidates]
    if len(candidates) != 80 or len(set(identities)) != 80:
        raise ValueError("Phase 3 requires exactly 80 unique unacquired candidates")

    by_repo: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in candidates:
        repository = str(row.get("repository", ""))
        if not repository:
            raise ValueError("candidate repository must be non-empty")
        by_repo[repository].append(row)
    if len(by_repo) < MINIMUM_REPOSITORIES:
        raise ValueError("candidate pool does not cover ten repositories")

    primary_quotas = _allocate_quotas(
        {repo: len(rows) for repo, rows in by_repo.items()}, PRIMARY_COUNT
    )
    ranked = {
        repo: _rank(rows, seed=seed, label=f"primary:{repo}")
        for repo, rows in by_repo.items()
    }
    primary_by_repo = {
        repo: rows[: primary_quotas[repo]] for repo, rows in ranked.items()
    }
    leftovers = {
        repo: rows[primary_quotas[repo] :]
        for repo, rows in ranked.items()
        if len(rows) > primary_quotas[repo]
    }
    reserve_quotas = _allocate_quotas(
        {repo: len(rows) for repo, rows in leftovers.items()}, RESERVE_COUNT
    )
    reserve_by_repo = {
        repo: rows[: reserve_quotas[repo]] for repo, rows in leftovers.items()
    }
    primary = _round_robin(primary_by_repo)
    reserve = _round_robin(reserve_by_repo)
    if len(primary) != PRIMARY_COUNT or len(reserve) != RESERVE_COUNT:
        raise RuntimeError("Phase 3 candidate plan has an invalid role count")
    if len({str(row["repository"]) for row in primary}) < MINIMUM_REPOSITORIES:
        raise RuntimeError("Primary candidates do not cover ten repositories")

    entries: list[dict[str, object]] = []
    for role, rows in (("PRIMARY", primary), ("RESERVE", reserve)):
        for rank, row in enumerate(rows, start=1):
            entries.append(
                {
                    **_identity(row),
                    "role": role,
                    "role_rank": rank,
                    "acquisition_rank": (
                        rank if role == "PRIMARY" else PRIMARY_COUNT + rank
                    ),
                    "qualification_status": "NOT_ACQUIRED",
                }
            )

    dataset = sample_freeze.get("dataset")
    if not isinstance(dataset, dict):
        raise TypeError("W1-C dataset binding must be an object")
    plan: dict[str, object] = {
        "schema_version": "phase3.cohort_candidate_plan.v1",
        "status": "PREREGISTERED_NOT_ACQUIRED",
        "dataset": dataset,
        "source_sampling_freeze_sha256": source_sha256,
        "seed": seed,
        "candidate_pool_count": len(candidates),
        "primary_count": PRIMARY_COUNT,
        "reserve_count": RESERVE_COUNT,
        "minimum_repository_count": MINIMUM_REPOSITORIES,
        "historical_pilot_ids_excluded": sorted(pilot_set),
        "sampling_rule": {
            "repository_allocation": "ONE_MINIMUM_THEN_CAPACITY_WEIGHTED",
            "within_repository_strata": "PROBLEM_STATEMENT_LENGTH_QUARTILES",
            "within_stratum_rank": "SHA256_SEEDED",
            "acquisition_order": "ROLE_THEN_REPOSITORY_ROUND_ROBIN",
            "execution_or_policy_outcomes_used": False,
        },
        "qualification_rule": {
            "required": [
                "FULL_PAYLOAD_AGENT_TRACE",
                "TOOL_OBSERVATIONS_AND_FAILURE_OR_RIGHT_CENSORING_EVIDENCE",
                "EXPLICIT_TOKEN_IDS_COMPLETE",
                "SIDECAR_COMPLETE_AND_HASH_BOUND",
                "PREFILL_PROFILE_SOURCE_VALID",
                "NATIVE_REPLAY_EXECUTABLE",
                "MODEL_TOKENIZER_CONTEXT_RUNTIME_COMPATIBLE",
            ],
            "decision_basis": "PRE_NATIVE_TRACE_AND_COMPATIBILITY_EVIDENCE_ONLY",
            "policy_outcomes_forbidden": True,
        },
        "reserve_promotion_rule": {
            "trigger": "PRIMARY_FAILS_PREREGISTERED_QUALIFICATION",
            "selection": (
                "LOWEST_ROLE_RANK_QUALIFIED_UNUSED_RESERVE_FROM_SAME_REPOSITORY;"
                " OTHERWISE_LOWEST_ROLE_RANK_QUALIFIED_UNUSED_RESERVE"
            ),
            "stop_if_qualified_tasks_below": PRIMARY_COUNT,
            "algorithm_or_native_outcomes_used": False,
        },
        "pairing_rule": {
            "group_count": 20,
            "tasks_per_group": 2,
            "different_repository_required": True,
            "input_order": "PROMOTED_COHORT_ACQUISITION_RANK",
            "algorithm": "DETERMINISTIC_GREEDY_DIFFERENT_REPOSITORY",
            "stop_on_failure": True,
        },
        "candidates": entries,
    }
    plan["candidate_assignment_sha256"] = _canonical_sha256(entries)
    return plan


def validate_candidate_plan(
    sample_freeze: Mapping[str, object],
    plan: Mapping[str, object],
    *,
    source_sha256: str,
) -> list[str]:
    problems: list[str] = []
    try:
        regenerated = build_candidate_plan(
            sample_freeze,
            source_sha256=source_sha256,
            seed=int(plan.get("seed", -1)),
        )
    except (KeyError, TypeError, ValueError) as error:
        return [str(error)]
    if regenerated != plan:
        problems.append("candidate plan does not deterministically regenerate")
    candidates = plan.get("candidates")
    if not isinstance(candidates, list):
        return [*problems, "candidate plan candidates must be an array"]
    primary = [row for row in candidates if row.get("role") == "PRIMARY"]
    reserve = [row for row in candidates if row.get("role") == "RESERVE"]
    if len(primary) != PRIMARY_COUNT or len(reserve) != RESERVE_COUNT:
        problems.append("candidate plan role counts are invalid")
    if len({str(row.get("repository")) for row in primary}) < MINIMUM_REPOSITORIES:
        problems.append("Primary role does not cover ten repositories")
    excluded = set(plan.get("historical_pilot_ids_excluded", []))
    selected = {str(row.get("instance_id")) for row in candidates}
    if excluded & selected:
        problems.append("historical Pilot task entered the Phase 3 candidate plan")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--sample-freeze", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--sample-freeze", type=Path, required=True)
    validate.add_argument("--plan", type=Path, required=True)
    arguments = parser.parse_args()
    source = json.loads(arguments.sample_freeze.read_text(encoding="utf-8"))
    source_sha = _sha256(arguments.sample_freeze)
    if arguments.command == "build":
        plan = build_candidate_plan(source, source_sha256=source_sha)
        if arguments.output.exists():
            raise FileExistsError(arguments.output)
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(
            json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(arguments.output)
        return 0
    plan = json.loads(arguments.plan.read_text(encoding="utf-8"))
    problems = validate_candidate_plan(source, plan, source_sha256=source_sha)
    print("Phase 3 candidate plan: " + ("PASS" if not problems else "FAIL"))
    for problem in problems:
        print(f"- {problem}")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
