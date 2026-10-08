"""Validate, analyze, and seal formal H2 M2/M3 native-token outcomes."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

from kvopt.workload.phase2_h2_mechanism import _load_authorization
from kvopt.workload.phase2_h2_mechanism_runner import (
    _validate_campaign,
    _validate_direct_evidence,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _return_observation(directory: Path, probe_id: str) -> dict[str, Any]:
    events = [
        json.loads(line)
        for line in (directory / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    matches = [
        event
        for event in events
        if event.get("event_type") == "VLLM_NATIVE_REQUEST_OBSERVATION"
        and event.get("request_id") == f"{probe_id}:turn:2"
    ]
    if len(matches) != 1 or not isinstance(matches[0].get("payload"), dict):
        raise ValueError("formal run lacks one native return observation")
    return matches[0]["payload"]


def _m2_outcome(rows: list[dict[str, Any]]) -> dict[str, object]:
    by_probe: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_probe[row["probe_id"]].append(row)
    results: list[dict[str, object]] = []
    for probe_id in (
        "m2-k0",
        "m2-k16",
        "m2-k32",
        "m2-k48",
        "m2-k64",
        "m2-no-eviction-control",
    ):
        probe_rows = sorted(by_probe[probe_id], key=lambda row: row["repeat_index"])
        if len(probe_rows) != 9:
            raise ValueError("M2 probe must contain nine measured repetitions")
        expected_cached = probe_rows[0]["expected_cached_prefix_tokens"]
        expected_recomputed = probe_rows[0]["expected_recomputed_prefill_tokens"]
        exact = all(
            row["native_cached_prefix_tokens"] == expected_cached
            and row["recomputed_prefill_tokens"] == expected_recomputed
            for row in probe_rows
        )
        results.append(
            {
                "probe_id": probe_id,
                "expected_cached_prefix_tokens": expected_cached,
                "expected_recomputed_prefill_tokens": expected_recomputed,
                "exact_repetition_count": sum(
                    row["native_cached_prefix_tokens"] == expected_cached
                    and row["recomputed_prefill_tokens"] == expected_recomputed
                    for row in probe_rows
                ),
                "all_repetitions_exact": exact,
                "repetitions": probe_rows,
            }
        )
    control_ids = {"m2-k0", "m2-k64", "m2-no-eviction-control"}
    controls_valid = all(
        result["all_repetitions_exact"]
        for result in results
        if result["probe_id"] in control_ids
    )
    partials_valid = all(
        result["all_repetitions_exact"]
        for result in results
        if result["probe_id"] not in control_ids
    )
    if not controls_valid:
        candidate = "INCONCLUSIVE_PENDING_REVIEW"
    elif partials_valid:
        candidate = "PASS_PENDING_REVIEW"
    else:
        candidate = "FAIL_PENDING_REVIEW"
    return {
        "schema_version": "phase2a.h2_formal_m2_outcome.v1",
        "measurement": "M2",
        "rule": {
            "block_size_tokens": 16,
            "prefix_blocks": 64,
            "token_tolerance": 0,
            "measured_repeats_per_probe": 9,
            "requires_no_eviction_full_hit_control": True,
        },
        "controls_valid": controls_valid,
        "partial_prefix_variants_valid": partials_valid,
        "candidate_outcome": candidate,
        "formal_verdict_authorized": False,
        "probe_results": results,
    }


def _m3_outcome(rows: list[dict[str, Any]]) -> dict[str, object]:
    by_arm: dict[tuple[str, str], dict[int, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        key = (row["cell_id"], row["position"])
        repeat = row["repeat_index"]
        if repeat in by_arm[key]:
            raise ValueError("duplicate M3 measured repetition")
        by_arm[key][repeat] = row
    cells: list[dict[str, object]] = []
    for prefix_tokens in (512, 2048, 8192, 24576):
        for evicted_blocks in (1, 4, 16):
            cell_id = f"m3-r{prefix_tokens}-j{evicted_blocks}"
            leading = by_arm[(cell_id, "leading")]
            trailing = by_arm[(cell_id, "trailing")]
            if set(leading) != set(range(1, 10)) or set(trailing) != set(range(1, 10)):
                raise ValueError("M3 cell must contain nine paired repetitions")
            pairs = []
            for repeat in range(1, 10):
                difference = (
                    leading[repeat]["recomputed_prefill_tokens"]
                    - trailing[repeat]["recomputed_prefill_tokens"]
                )
                pairs.append(
                    {
                        "repeat_index": repeat,
                        "leading_recomputed_prefill_tokens": leading[repeat][
                            "recomputed_prefill_tokens"
                        ],
                        "trailing_recomputed_prefill_tokens": trailing[repeat][
                            "recomputed_prefill_tokens"
                        ],
                        "difference_tokens": difference,
                        "resolved_effect": difference >= 16,
                    }
                )
            supporting = sum(pair["resolved_effect"] for pair in pairs)
            no_effect = sum(pair["difference_tokens"] < 16 for pair in pairs)
            cells.append(
                {
                    "cell_id": cell_id,
                    "prefix_tokens": prefix_tokens,
                    "evicted_blocks": evicted_blocks,
                    "supporting_repetition_count": supporting,
                    "no_resolved_effect_repetition_count": no_effect,
                    "supports_position": supporting >= 8,
                    "has_no_resolved_effect": no_effect >= 8,
                    "paired_repetitions": pairs,
                }
            )
    supporting_cells = sum(cell["supports_position"] for cell in cells)
    no_effect_cells = sum(cell["has_no_resolved_effect"] for cell in cells)
    if supporting_cells >= 10:
        candidate = "PASS_PENDING_REVIEW"
    elif no_effect_cells >= 10:
        candidate = "FAIL_PENDING_REVIEW"
    else:
        candidate = "INCONCLUSIVE_PENDING_REVIEW"
    return {
        "schema_version": "phase2a.h2_formal_m3_outcome.v1",
        "measurement": "M3",
        "rule": {
            "resolved_effect_tokens": 16,
            "supporting_repeats_required": 8,
            "supporting_cells_required": 10,
            "total_cells": 12,
        },
        "supporting_cell_count": supporting_cells,
        "no_resolved_effect_cell_count": no_effect_cells,
        "candidate_outcome": candidate,
        "formal_verdict_authorized": False,
        "cell_results": cells,
    }


def _write_json(path: Path, value: object) -> str:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return _sha(path)


def build_h2_m2_m3_outcome_bundle(
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
    campaign, authorization_sha, selected = _validate_campaign(
        campaign_path,
        authorization_path,
    )
    authorization = _load_authorization(authorization_path)
    analysis_git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    analysis_dirty = subprocess.run(
        [
            "git", "status", "--porcelain", "--untracked-files=normal", "--",
            "src", "scripts", "configs",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if analysis_dirty:
        raise ValueError("commit analysis source/config changes before sealing")
    execution = json.loads(execution_path.read_text(encoding="utf-8"))
    if execution.get("schema_version") != "phase2a.h2_formal_m2_m3_execution.v1":
        raise ValueError("unsupported formal M2/M3 execution summary")
    if execution.get("campaign_sha256") != _sha(campaign_path):
        raise ValueError("execution summary campaign hash mismatch")
    if execution.get("authorization_sha256") != authorization_sha:
        raise ValueError("execution summary authorization hash mismatch")
    if (
        execution.get("formal_measurement") is not True
        or execution.get("formal_verdict_authorized") is not False
        or execution.get("b1_authorized") is not False
    ):
        raise ValueError("execution summary authorization state is invalid")
    results = execution.get("results")
    if not isinstance(results, list) or len(results) != len(selected):
        raise ValueError("execution summary must contain all 330 runs")
    result_by_id = {result.get("run_id"): result for result in results}
    if len(result_by_id) != 330:
        raise ValueError("execution summary run IDs must be unique")
    measured_rows: list[dict[str, Any]] = []
    raw_bindings: list[dict[str, object]] = []
    for _config_path, probe, run in selected:
        run_id = run["run_id"]
        result = result_by_id.get(run_id)
        if not isinstance(result, dict) or result.get("status") not in {
            "success",
            "skipped_existing",
        }:
            raise ValueError(f"formal execution result is invalid: {run_id}")
        directory = run_root / run_id
        manifest_path = directory / "run.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            manifest.get("status") != "success"
            or manifest.get("git_sha") != execution.get("git_sha")
            or manifest.get("git_dirty") is not False
            or manifest.get("config_sha256") != probe["runtime_config_sha256"]
            or manifest.get("trace_sha256") != probe["trace_sha256"]
        ):
            raise ValueError(f"formal raw provenance is invalid: {run_id}")
        _validate_direct_evidence(directory, probe)
        raw_bindings.append(
            {
                "run_id": run_id,
                "run_manifest_sha256": _sha(manifest_path),
                "events_sha256": _sha(directory / "events.jsonl"),
            }
        )
        if run["role"] != "measured":
            continue
        payload = _return_observation(directory, probe["probe_id"])
        prefix_tokens = probe["prefix_tokens"]
        cached = payload["native_cached_prefix_tokens"]
        repeat_index = int(run_id.rsplit("-", 1)[1])
        row = {
            "run_id": run_id,
            "probe_id": probe["probe_id"],
            "repeat_index": repeat_index,
            "prefix_tokens": prefix_tokens,
            "native_cached_prefix_tokens": cached,
            "recomputed_prefill_tokens": prefix_tokens - cached,
        }
        if probe["measurement"] == "M2":
            retained = probe["retained_leading_blocks"]
            row.update(
                expected_cached_prefix_tokens=retained * 16,
                expected_recomputed_prefill_tokens=prefix_tokens - retained * 16,
            )
        else:
            row.update(
                cell_id=probe["cell_id"],
                position=probe["position"],
                evicted_blocks=probe["evicted_blocks"],
            )
        measured_rows.append(row)
    m2_rows = [row for row in measured_rows if row["probe_id"].startswith("m2-")]
    m3_rows = [row for row in measured_rows if row["probe_id"].startswith("m3-")]
    if len(m2_rows) != 54 or len(m3_rows) != 216:
        raise ValueError("formal measured row counts are incomplete")
    m2 = _m2_outcome(m2_rows)
    m3 = _m3_outcome(m3_rows)
    failed_attempts = []
    failed_root = run_root / ".failed-attempts"
    if failed_root.is_dir():
        for manifest_path in sorted(failed_root.glob("*/run.json")):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            reason = manifest.get("failure_reason")
            if (
                manifest.get("status") != "failed"
                or manifest.get("event_count") != 0
                or not isinstance(reason, str)
                or not reason.startswith("ConnectError:")
                or "SSL" not in reason
            ):
                raise ValueError("excluded attempt was not a zero-event failure")
            failed_attempts.append(
                {
                    "directory": manifest_path.parent.name,
                    "failure_reason": manifest.get("failure_reason"),
                    "run_manifest_sha256": _sha(manifest_path),
                }
            )
    provenance = {
        "schema_version": "phase2a.h2_formal_m2_m3_provenance.v1",
        "measurement_git_sha": execution["git_sha"],
        "analysis_git_sha": analysis_git_sha,
        "analysis_code_sha256": _sha(Path(__file__)),
        "authorization_sha256": authorization_sha,
        "campaign_sha256": _sha(campaign_path),
        "execution_summary_sha256": _sha(execution_path),
        "runtime_identity": authorization["runtime_identity"],
        "formal_measurement": True,
        "formal_verdict_authorized": False,
        "b1_authorized": False,
        "validated_run_count": len(raw_bindings),
        "measured_row_count": len(measured_rows),
        "excluded_zero_event_infrastructure_attempts": failed_attempts,
        "raw_bindings": raw_bindings,
    }
    output.mkdir(parents=True, exist_ok=False)
    m2_sha = _write_json(output / "m2-outcome.json", m2)
    m3_sha = _write_json(output / "m3-outcome.json", m3)
    provenance_sha = _write_json(output / "provenance.json", provenance)
    seal = {
        "schema_version": "phase2a.h2_formal_m2_m3_seal.v1",
        "campaign_id": campaign["campaign_id"],
        "formal_measurement": True,
        "formal_verdict_authorized": False,
        "b1_authorized": False,
        "review_state": "PENDING_M1_M4_FORMAL_VERDICT_REVIEW",
        "candidate_outcomes": {
            "M2": m2["candidate_outcome"],
            "M3": m3["candidate_outcome"],
        },
        "files": {
            "m2-outcome.json": m2_sha,
            "m3-outcome.json": m3_sha,
            "provenance.json": provenance_sha,
        },
    }
    path = output / "seal.json"
    _write_json(path, seal)
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--execution", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        "wrote sealed H2 M2/M3 outcome bundle: "
        f"{build_h2_m2_m3_outcome_bundle(args.campaign, args.authorization, args.execution, args.run_root, args.output)}"
    )
