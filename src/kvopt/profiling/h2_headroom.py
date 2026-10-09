"""Validate, analyze, and seal the formal H2 M4 headroom outcome."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

from kvopt.workload.phase2_h2_headroom_validation_runner import (
    _events,
    _return_recomputed,
    _validate_block,
    _validate_entry,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def analyze_m4_rows(rows: list[dict[str, object]]) -> dict[str, object]:
    by_arm: dict[tuple[str, str], dict[int, dict[str, object]]] = defaultdict(dict)
    for row in rows:
        key = (str(row["cell_id"]), str(row["arm"]))
        repeat = int(row["repeat_index"])
        if repeat in by_arm[key]:
            raise ValueError("duplicate M4 measured repetition")
        by_arm[key][repeat] = row
    cells = []
    for prefix_tokens in (512, 2048, 8192, 24576):
        for evicted_blocks in (1, 4, 16):
            cell_id = f"m4-r{prefix_tokens}-j{evicted_blocks}"
            entry = by_arm[(cell_id, "entry")]
            block = by_arm[(cell_id, "block")]
            if set(entry) != set(range(1, 10)) or set(block) != set(range(1, 10)):
                raise ValueError("M4 cell must contain nine paired repetitions")
            pairs = []
            for repeat in range(1, 10):
                entry_recomputed = int(entry[repeat]["observed_recomputed_tokens"])
                block_recomputed = int(block[repeat]["observed_recomputed_tokens"])
                headroom = entry_recomputed - block_recomputed
                pairs.append(
                    {
                        "repeat_index": repeat,
                        "entry_recomputed_tokens": entry_recomputed,
                        "block_recomputed_tokens": block_recomputed,
                        "headroom_tokens": headroom,
                        "resolved_headroom": headroom >= 16,
                        "no_resolved_headroom": headroom < 16,
                    }
                )
            supporting = sum(pair["resolved_headroom"] for pair in pairs)
            no_effect = sum(pair["no_resolved_headroom"] for pair in pairs)
            cells.append(
                {
                    "cell_id": cell_id,
                    "prefix_tokens": prefix_tokens,
                    "evicted_blocks": evicted_blocks,
                    "supporting_repetition_count": supporting,
                    "no_resolved_headroom_repetition_count": no_effect,
                    "supports_headroom": supporting >= 8,
                    "has_no_resolved_headroom": no_effect >= 8,
                    "paired_repetitions": pairs,
                }
            )
    supporting_cells = sum(cell["supports_headroom"] for cell in cells)
    no_effect_cells = sum(cell["has_no_resolved_headroom"] for cell in cells)
    if supporting_cells >= 10:
        candidate = "PASS_PENDING_REVIEW"
    elif no_effect_cells >= 10:
        candidate = "FAIL_PENDING_REVIEW"
    else:
        candidate = "INCONCLUSIVE_PENDING_REVIEW"
    return {
        "schema_version": "phase2a.h2_formal_m4_outcome.v1",
        "measurement": "M4",
        "scope": "single_prefix_controlled_mechanism_headroom_only",
        "interpretation_exclusion": "not_global_multi_entry_eviction_policy_benefit",
        "rule": {
            "headroom": "entry_recomputed_tokens_minus_block_recomputed_tokens",
            "resolved_effect_tokens": 16,
            "supporting_repeats_required": 8,
            "supporting_cells_required": 10,
            "total_cells": 12,
        },
        "supporting_cell_count": supporting_cells,
        "no_resolved_headroom_cell_count": no_effect_cells,
        "candidate_outcome": candidate,
        "formal_verdict_authorized": False,
        "b1_authorized": False,
        "cell_results": cells,
    }


def build_h2_m4_outcome_bundle(
    campaign_path: Path,
    authorization_path: Path,
    execution_path: Path,
    run_root: Path,
    output: Path,
) -> Path:
    campaign_path = campaign_path.resolve()
    authorization_path = authorization_path.resolve()
    execution_path = execution_path.resolve()
    run_root = run_root.resolve()
    campaign = json.loads(campaign_path.read_text())
    execution = json.loads(execution_path.read_text())
    authorization_sha = _sha(authorization_path)
    if campaign.get("schema_version") != "phase2a.h2_formal_m4_campaign.v1":
        raise ValueError("unsupported formal M4 campaign")
    if campaign.get("authorization_sha256") != authorization_sha:
        raise ValueError("formal M4 authorization hash mismatch")
    if execution.get("schema_version") != "phase2a.h2_formal_m4_execution.v1":
        raise ValueError("unsupported formal M4 execution")
    if (
        execution.get("campaign_sha256") != _sha(campaign_path)
        or execution.get("authorization_sha256") != authorization_sha
        or execution.get("formal_verdict_authorized") is not False
        or execution.get("b1_authorized") is not False
    ):
        raise ValueError("formal M4 execution binding is invalid")
    results = execution.get("results")
    if not isinstance(results, list) or len(results) != 264:
        raise ValueError("formal M4 execution must contain all 264 runs")
    result_by_id = {row.get("run_id"): row for row in results}
    if len(result_by_id) != 264:
        raise ValueError("formal M4 execution run IDs must be unique")
    measured_rows = []
    raw_bindings = []
    for probe in campaign["probes"]:
        for run in probe["runs"]:
            run_id = run["run_id"]
            summary = result_by_id.get(run_id)
            if not isinstance(summary, dict) or summary.get("status") not in {
                "success", "skipped_existing",
            }:
                raise ValueError(f"formal M4 execution result is invalid: {run_id}")
            directory = run_root / run_id
            manifest_path = directory / "run.json"
            manifest = json.loads(manifest_path.read_text())
            if (
                manifest.get("status") != "success"
                or manifest.get("git_sha") != execution.get("git_sha")
                or manifest.get("git_dirty") is not False
                or manifest.get("config_sha256") != probe["runtime_config_sha256"]
                or manifest.get("trace_sha256") != probe["trace_sha256"]
            ):
                raise ValueError(f"formal M4 raw provenance is invalid: {run_id}")
            events = _events(directory)
            audit: dict[str, Any] = (
                _validate_entry(events, probe)
                if probe["arm"] == "entry"
                else _validate_block(events, probe)
            )
            recomputed = _return_recomputed(
                events, str(probe["probe_id"]), int(probe["prefix_tokens"])
            )
            if (
                recomputed != summary.get("observed_recomputed_tokens")
                or audit["physically_selected_prefix_block_count"]
                != probe["evicted_blocks"]
                or summary.get("physically_selected_prefix_block_count")
                != probe["evicted_blocks"]
            ):
                raise ValueError(f"formal M4 direct evidence mismatch: {run_id}")
            raw_bindings.append(
                {
                    "run_id": run_id,
                    "role": run["role"],
                    "run_manifest_sha256": _sha(manifest_path),
                    "events_sha256": _sha(directory / "events.jsonl"),
                }
            )
            if run["role"] == "measured":
                measured_rows.append(
                    {
                        "run_id": run_id,
                        "cell_id": probe["cell_id"],
                        "arm": probe["arm"],
                        "repeat_index": run["repeat_index"],
                        "observed_recomputed_tokens": recomputed,
                    }
                )
    if len(measured_rows) != 216:
        raise ValueError("formal M4 requires 216 measured arm rows")
    outcome = analyze_m4_rows(measured_rows)
    analysis_git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=normal", "--", "src", "configs"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if dirty:
        raise ValueError("commit analysis source/config changes before sealing")
    output.mkdir(parents=True, exist_ok=False)
    outcome_path = output / "m4-outcome.json"
    outcome_path.write_text(json.dumps(outcome, indent=2, sort_keys=True) + "\n")
    rows_path = output / "measured-rows.json"
    rows_path.write_text(json.dumps(measured_rows, indent=2, sort_keys=True) + "\n")
    provenance = {
        "schema_version": "phase2a.h2_formal_m4_provenance.v1",
        "measurement_git_sha": execution["git_sha"],
        "analysis_git_sha": analysis_git_sha,
        "analysis_code_sha256": _sha(Path(__file__)),
        "authorization_sha256": authorization_sha,
        "campaign_sha256": _sha(campaign_path),
        "execution_summary_sha256": _sha(execution_path),
        "comparator_validation_sha256": campaign["comparator_validation_sha256"],
        "validated_run_count": len(raw_bindings),
        "measured_arm_row_count": len(measured_rows),
        "raw_bindings": raw_bindings,
    }
    provenance_path = output / "provenance.json"
    provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    seal = {
        "schema_version": "phase2a.h2_formal_m4_seal.v1",
        "formal_measurement": True,
        "formal_verdict_authorized": False,
        "b1_authorized": False,
        "review_state": "PENDING_M1_M4_FORMAL_VERDICT_REVIEW",
        "candidate_outcome": outcome["candidate_outcome"],
        "files": {
            path.name: _sha(path)
            for path in (outcome_path, rows_path, provenance_path)
        },
    }
    seal_path = output / "seal.json"
    seal_path.write_text(json.dumps(seal, indent=2, sort_keys=True) + "\n")
    return seal_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--execution", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    path = build_h2_m4_outcome_bundle(
        arguments.campaign, arguments.authorization, arguments.execution,
        arguments.run_root, arguments.output,
    )
    print(f"wrote sealed H2 M4 outcome bundle: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
