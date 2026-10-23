"""Freeze the cross-repository W1-C sample and paired S50/S100 pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

DATASET_NAME = "princeton-nlp/SWE-bench_Verified"
DATASET_CONFIG = "default"
DATASET_SPLIT = "test"
DATASET_REVISION = "c104f840cc67f8b6eec6f759ebc8b2693d585d4a"
DEFAULT_SEED = 20261023


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _row_feature(row: Mapping[str, object]) -> dict[str, object]:
    instance_id = str(row["instance_id"])
    repo = str(row["repo"])
    statement = str(row.get("problem_statement", ""))
    if not instance_id or not repo or not statement:
        raise ValueError("candidate rows require instance_id, repo, and problem_statement")
    return {
        "instance_id": instance_id,
        "repository": repo,
        "base_commit": str(row.get("base_commit", "")),
        "created_at": str(row.get("created_at", "")),
        "difficulty": str(row.get("difficulty", "")),
        "problem_statement_char_count": len(statement),
        "problem_statement_word_count": len(statement.split()),
        "problem_statement_sha256": hashlib.sha256(statement.encode()).hexdigest(),
    }


def build_candidate_snapshot(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    features = [_row_feature(row) for row in rows]
    identities = [str(row["instance_id"]) for row in features]
    if len(features) != 500 or len(set(identities)) != 500:
        raise ValueError("W1-C requires the unique 500-row SWE-bench Verified test split")
    return {
        "schema_version": "continuum.w1c_candidate_snapshot.v1",
        "dataset": {
            "name": DATASET_NAME,
            "config": DATASET_CONFIG,
            "split": DATASET_SPLIT,
            "revision": DATASET_REVISION,
            "row_count": len(features),
        },
        "feature_boundary": {
            "execution_outcomes_used": False,
            "policy_results_used": False,
            "solution_patch_features_used": False,
            "features": [
                "repository",
                "problem_statement_char_count",
                "problem_statement_word_count",
                "created_at",
            ],
        },
        "repository_counts": dict(
            sorted(Counter(str(row["repository"]) for row in features).items())
        ),
        "candidates": sorted(features, key=lambda row: str(row["instance_id"])),
    }


def _allocate_quotas(capacities: Mapping[str, int], total: int) -> dict[str, int]:
    if total < len(capacities) or total > sum(capacities.values()):
        raise ValueError("quota total cannot cover every stratum within capacity")
    quotas = {key: 1 for key in capacities}
    remaining = total - len(quotas)
    while remaining:
        eligible = [key for key in sorted(capacities) if quotas[key] < capacities[key]]
        denominator = sum(capacities[key] for key in eligible)
        ideals = {key: capacities[key] * remaining / denominator for key in eligible}
        base = {
            key: min(capacities[key] - quotas[key], int(ideals[key])) for key in eligible
        }
        allocated = sum(base.values())
        if allocated:
            for key, count in base.items():
                quotas[key] += count
            remaining -= allocated
            continue
        ranked = sorted(
            eligible,
            key=lambda key: (
                -(ideals[key] - int(ideals[key])),
                -(capacities[key] - quotas[key]),
                key,
            ),
        )
        progressed = False
        for key in ranked:
            if remaining == 0:
                break
            quotas[key] += 1
            remaining -= 1
            progressed = True
        if not progressed:
            raise RuntimeError("quota allocation made no progress")
    return quotas


def _length_strata(rows: Sequence[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    ordered = sorted(
        rows,
        key=lambda row: (
            int(row["problem_statement_char_count"]),
            str(row["instance_id"]),
        ),
    )
    strata: dict[str, list[dict[str, object]]] = defaultdict(list)
    for index, row in enumerate(ordered):
        quartile = min(3, (index * 4) // len(ordered))
        strata[f"Q{quartile + 1}"].append(row)
    return dict(strata)


def _sample_repository(
    rows: Sequence[dict[str, object]], *, count: int, seed: int, label: str
) -> list[dict[str, object]]:
    strata = _length_strata(rows)
    quotas = _allocate_quotas(
        {key: len(value) for key, value in strata.items()},
        count,
    ) if count >= len(strata) else {
        key: 1 if index < count else 0
        for index, key in enumerate(sorted(strata))
    }
    chosen: list[dict[str, object]] = []
    for stratum, stratum_rows in sorted(strata.items()):
        shuffled = list(stratum_rows)
        random.Random(f"{seed}:{label}:{stratum}").shuffle(shuffled)
        chosen.extend(shuffled[: quotas[stratum]])
    return sorted(chosen, key=lambda row: str(row["instance_id"]))


def freeze_sampling(
    snapshot: Mapping[str, object],
    *,
    snapshot_sha256: str,
    w1a_instance_ids: Sequence[str],
    sample_count: int = 100,
    pilot_count: int = 20,
    seed: int = DEFAULT_SEED,
) -> dict[str, object]:
    if snapshot.get("schema_version") != "continuum.w1c_candidate_snapshot.v1":
        raise ValueError("unsupported W1-C candidate snapshot")
    dataset = snapshot.get("dataset")
    if not isinstance(dataset, Mapping) or dataset.get("revision") != DATASET_REVISION:
        raise ValueError("W1-C dataset revision mismatch")
    historical = set(w1a_instance_ids)
    candidates = [
        dict(row)
        for row in snapshot["candidates"]  # type: ignore[index]
        if str(row["instance_id"]) not in historical
    ]
    by_repo: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in candidates:
        by_repo[str(row["repository"])].append(row)
    sample_quotas = _allocate_quotas(
        {repo: len(rows) for repo, rows in by_repo.items()}, sample_count
    )
    selected: list[dict[str, object]] = []
    for repo, rows in sorted(by_repo.items()):
        selected.extend(
            _sample_repository(rows, count=sample_quotas[repo], seed=seed, label=f"sample:{repo}")
        )
    selected_by_repo: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in selected:
        selected_by_repo[str(row["repository"])].append(row)
    pilot_quotas = _allocate_quotas(
        {repo: len(rows) for repo, rows in selected_by_repo.items()}, pilot_count
    )
    pilot: list[dict[str, object]] = []
    for repo, rows in sorted(selected_by_repo.items()):
        pilot.extend(
            _sample_repository(
                rows,
                count=pilot_quotas[repo],
                seed=seed + 1,
                label=f"pilot:{repo}",
            )
        )
    pilot_ids = {str(row["instance_id"]) for row in pilot}
    selected_rows = [
        {**row, "pilot_selected": str(row["instance_id"]) in pilot_ids}
        for row in sorted(selected, key=lambda row: str(row["instance_id"]))
    ]
    return {
        "schema_version": "continuum.w1c_stratified_sample_freeze.v1",
        "scope": "W1C_SAMPLING_DESIGN_AND_BOUNDED_S50_S100_PILOT_ONLY",
        "dataset": dict(dataset),
        "candidate_snapshot_sha256": snapshot_sha256,
        "seed": seed,
        "sampling_method": {
            "primary_stratum": "repository",
            "repository_allocation": "ONE_MINIMUM_THEN_CAPACITY_WEIGHTED",
            "within_repository_stratum": "PROBLEM_STATEMENT_LENGTH_QUARTILE",
            "within_stratum_selection": "SEEDED_WITHOUT_REPLACEMENT",
            "execution_or_policy_outcomes_used": False,
        },
        "w1a_historical_instances": sorted(historical),
        "w1a_handling": "PRESERVED_AS_HISTORY_EXCLUDED_FROM_NEW_W1C_SAMPLE_AND_PILOT",
        "sample_count": len(selected_rows),
        "sample_repository_quotas": dict(sorted(sample_quotas.items())),
        "pilot_count": len(pilot),
        "pilot_repository_quotas": dict(sorted(pilot_quotas.items())),
        "selected_tasks": selected_rows,
        "pilot_instance_ids": sorted(pilot_ids),
        "pilot_conditions": {
            "S50": {"step_limit": 50},
            "S100": {"step_limit": 100},
            "paired_same_task_ids": True,
            "planned_execution_count": len(pilot_ids) * 2,
        },
        "full_100_task_acquisition_authorized": False,
        "formal_native_policy_campaign_authorized": False,
    }


def validate_freeze(
    snapshot: Mapping[str, object], freeze: Mapping[str, object], *, snapshot_sha256: str
) -> list[str]:
    problems: list[str] = []
    if freeze.get("candidate_snapshot_sha256") != snapshot_sha256:
        problems.append("candidate snapshot SHA-256 mismatch")
    regenerated = freeze_sampling(
        snapshot,
        snapshot_sha256=snapshot_sha256,
        w1a_instance_ids=freeze.get("w1a_historical_instances", []),  # type: ignore[arg-type]
        sample_count=int(freeze.get("sample_count", 0)),
        pilot_count=int(freeze.get("pilot_count", 0)),
        seed=int(freeze.get("seed", -1)),
    )
    if regenerated != freeze:
        problems.append("freeze does not deterministically regenerate from the candidate snapshot")
    repositories = {str(row["repository"]) for row in freeze.get("selected_tasks", [])}  # type: ignore[union-attr]
    if len(repositories) != 12:
        problems.append("sample does not cover all 12 repositories")
    pilot_ids = freeze.get("pilot_instance_ids", [])
    if len(pilot_ids) != 20 or len(set(pilot_ids)) != 20:  # type: ignore[arg-type]
        problems.append("pilot must contain exactly 20 unique task IDs")
    if freeze.get("full_100_task_acquisition_authorized") is not False:
        problems.append("full acquisition authorization must remain false")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    snapshot_parser = sub.add_parser("snapshot")
    snapshot_parser.add_argument("--output", type=Path, required=True)
    freeze_parser = sub.add_parser("freeze")
    freeze_parser.add_argument("--snapshot", type=Path, required=True)
    freeze_parser.add_argument("--w1a-sample", type=Path, required=True)
    freeze_parser.add_argument("--output", type=Path, required=True)
    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("--snapshot", type=Path, required=True)
    validate_parser.add_argument("--freeze", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "snapshot":
        from datasets import load_dataset

        rows = load_dataset(
            DATASET_NAME,
            DATASET_CONFIG,
            split=DATASET_SPLIT,
            revision=DATASET_REVISION,
        )
        _write(args.output, build_candidate_snapshot(rows))
        print(f"wrote W1-C candidate snapshot: {args.output}")
        return 0
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    if args.command == "freeze":
        w1a = json.loads(args.w1a_sample.read_text(encoding="utf-8"))
        value = freeze_sampling(
            snapshot,
            snapshot_sha256=_sha256(args.snapshot),
            w1a_instance_ids=w1a["instance_ids"],
        )
        _write(args.output, value)
        print(f"wrote W1-C sampling freeze: {args.output}")
        return 0
    freeze = json.loads(args.freeze.read_text(encoding="utf-8"))
    problems = validate_freeze(snapshot, freeze, snapshot_sha256=_sha256(args.snapshot))
    print("W1-C sampling validation: " + ("PASS" if not problems else "FAIL"))
    for problem in problems:
        print(f"- {problem}")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
