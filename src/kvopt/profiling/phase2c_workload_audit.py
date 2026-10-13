"""Read-only Phase 2C audit of the sealed H1 workload and APC evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "phase2c.workload_reuse_audit.v1"
RUN_KIND = "NON_HOLDOUT_WORKLOAD_AUDIT"
RUNTIME_EVIDENCE = (
    "artifacts/phase2a-h1-formal-level-a-derived-v1/"
    "request_runtime_evidence.jsonl"
)
RUNS = "artifacts/phase2a-h1-formal-level-a-derived-v1/runs.jsonl"
CAMPAIGN_PREFIX = "artifacts/phase2a-h1-formal-level-a-campaign-v1/"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _jsonl(data: bytes) -> list[dict[str, Any]]:
    return [json.loads(line) for line in data.decode("utf-8").splitlines()]


def _member_bytes(archive: tarfile.TarFile, name: str) -> bytes:
    member = archive.getmember(name)
    stream = archive.extractfile(member)
    if stream is None:
        raise ValueError(f"archive member is not a regular file: {name}")
    return stream.read()


def _hash_chain(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(value) for value in row.get("native_apc_block_hashes") or ())


def summarize_historical_rows(
    rows: Iterable[dict[str, Any]],
    runs: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Recompute historical APC counts without mutating sealed evidence."""
    rows = list(rows)
    runs = list(runs)
    turns = [row for row in rows if row.get("kind") == "turn"]
    pressure = [row for row in rows if row.get("kind") == "pressure"]
    eligible = [row for row in turns if int(row["eligible_prefix_tokens"]) > 0]

    run_metadata = {str(row["run_id"]): row for row in runs}
    outcome_counts = Counter(str(row["apc_outcome"]) for row in eligible)
    family_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in eligible:
        family = str(run_metadata[str(row["run_id"])]["scenario_family_id"])
        family_counts[family][str(row["apc_outcome"])] += 1

    by_program: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in turns:
        by_program[(str(row["run_id"]), str(row["program_id"]))].append(row)
    same_program_comparisons = 0
    same_program_identical = 0
    first_to_second_comparisons = 0
    first_to_second_identical = 0
    first_rows_by_run: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (run_id, _program_id), program_rows in by_program.items():
        program_rows.sort(key=lambda row: int(str(row["request_id"]).rsplit(":", 1)[-1]))
        first = program_rows[0]
        first_rows_by_run[run_id].append(first)
        for later in program_rows[1:]:
            same_program_comparisons += 1
            same_program_identical += _hash_chain(first) == _hash_chain(later)
        if len(program_rows) >= 2:
            first_to_second_comparisons += 1
            first_to_second_identical += (
                _hash_chain(first) == _hash_chain(program_rows[1])
            )

    cross_program_comparisons = 0
    cross_program_equal = 0
    for first_rows in first_rows_by_run.values():
        for left_index, left in enumerate(first_rows):
            for right in first_rows[left_index + 1 :]:
                cross_program_comparisons += 1
                cross_program_equal += _hash_chain(left) == _hash_chain(right)

    seed_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in eligible:
        scenario = str(run_metadata[str(row["run_id"])]["scenario_id"])
        seed_groups[(scenario, str(row["request_id"]))].append(row)
    complete_seed_groups = [group for group in seed_groups.values() if len(group) == 3]
    seed_identical = sum(
        len({(row["apc_outcome"], row["native_cached_prefix_tokens"]) for row in group})
        == 1
        for group in complete_seed_groups
    )

    return {
        "all_request_rows": len(rows),
        "turn_rows": len(turns),
        "pressure_rows": len(pressure),
        "eligible_turn_rows": len(eligible),
        "successful_runs": sum(row.get("status") == "success" for row in runs),
        "successful_scenario_draws": len(
            {row["scenario_id"] for row in runs if row.get("status") == "success"}
        ),
        "eligible_apc_outcomes": dict(sorted(outcome_counts.items())),
        "family_apc_outcomes": {
            family: dict(sorted(counts.items()))
            for family, counts in sorted(family_counts.items())
        },
        "same_program_first_to_second_hash_chain": {
            "identical": first_to_second_identical,
            "compared": first_to_second_comparisons,
        },
        "same_program_first_to_all_later_hash_chain": {
            "identical": same_program_identical,
            "compared": same_program_comparisons,
        },
        "different_program_first_hash_chain": {
            "equal": cross_program_equal,
            "compared": cross_program_comparisons,
        },
        "three_seed_outcome_and_cached_tokens": {
            "identical": seed_identical,
            "compared": len(complete_seed_groups),
        },
        "partial_hit_independent_positions": sum(
            all(row["apc_outcome"] == "PARTIAL_HIT" for row in group)
            for group in complete_seed_groups
        ),
    }


def audit_archive(archive_path: Path) -> dict[str, Any]:
    with tarfile.open(archive_path, "r:gz") as archive:
        rows = _jsonl(_member_bytes(archive, RUNTIME_EVIDENCE))
        runs = _jsonl(_member_bytes(archive, RUNS))
        config_names = sorted(
            name
            for name in archive.getnames()
            if name.startswith(CAMPAIGN_PREFIX)
            and name.endswith(".config.json")
            and not Path(name).name.startswith("._")
        )
        configs = [json.loads(_member_bytes(archive, name)) for name in config_names]

    historical = summarize_historical_rows(rows, runs)
    historical["campaign_config_count"] = len(configs)
    historical["max_concurrent_requests_values"] = sorted(
        {config["batching"]["max_concurrent_requests"] for config in configs}
    )
    historical["max_new_tokens_values"] = sorted(
        {config["generation"]["max_new_tokens"] for config in configs}
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "run_kind": RUN_KIND,
        "scope": "historical_read_only_diagnostic_and_workload_design",
        "source_archive": {
            "path": archive_path.as_posix(),
            "sha256": _sha256(archive_path),
        },
        "historical_counts": historical,
        "findings": {
            "H-DATA-1": {
                "verdict": "SUPPORTED",
                "reason": "same-program native hash chains were invariant across later turns",
            },
            "H-DATA-2": {
                "verdict": "SUPPORTED",
                "reason": "three runtime seeds produced identical APC labels and cached-token counts",
            },
            "H-DATA-3": {
                "verdict": "PARTIALLY_SUPPORTED",
                "reason": "content identity and residency can be separated, but historical eviction content ownership is unavailable",
            },
            "H-DATA-4": {
                "verdict": "NOT_OBSERVABLE",
                "reason": "a bounded native pilot has not been authorized or executed",
            },
        },
        "unobservable_dimensions": [
            "exact historical submitted token IDs",
            "native eviction-time logical ownership",
            "counterfactual APC outcome without the observed pressure sequence",
        ],
        "proposed_topologies": [
            "W-COLD",
            "W-EXACT",
            "W-XPROGRAM",
            "W-ROOT-FORK",
            "W-NESTED",
            "W-TURN-GROW",
            "W-HOT-COLD",
            "W-PRESSURE",
        ],
        "native_pilot": None,
        "formal_campaign_authorized": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    report = audit_archive(arguments.archive)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote Phase 2C workload reuse audit: {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
