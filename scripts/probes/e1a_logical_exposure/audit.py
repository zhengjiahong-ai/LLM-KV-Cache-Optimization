"""E1-A: CPU-only logical candidate-exposure feasibility audit.

This audit reads the frozen Phase 3 A0 archive and, if present, existing W1-C
traces.  It does not run a model, GPU, Native smoke, or production algorithm.

The frozen deployment models, denominators, and data-qualification labels are in
``configs/phase4/e1a-logical-exposure-freeze-v1.json``.  The primary model uses
only the actual ``FORCED_RELEASE_DECISION.candidates`` list.  Modeled retention
models require a protected-entry snapshot that is not present in the current
workspace; they are reported as NOT_EXECUTABLE rather than fabricated from
post-hoc candidate inference.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Request:
    cell: str
    program: str
    request_id: str
    timestamp: float


@dataclass(frozen=True)
class Decision:
    cell: str
    timestamp: float
    required_blocks: int | None
    candidates: tuple[tuple[str, str], ...]  # (program, prefix_id)


@dataclass(frozen=True)
class CellData:
    cell: str
    requests: tuple[Request, ...]
    decisions: tuple[Decision, ...]


def load_freeze(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("status") != "FROZEN_BEFORE_EXECUTION":
        raise ValueError("E1-A freeze config is not frozen before execution")
    if config.get("primary_model", {}).get("status") != "EXECUTABLE":
        raise ValueError("primary model is not executable")
    return config


def load_phase3(evidence: Path) -> list[CellData]:
    runs = sorted((evidence / "native-runs").glob("*-a0"))
    if not runs:
        raise ValueError("no A0 runs found")
    cells: list[CellData] = []
    for run in runs:
        events = [
            json.loads(line)
            for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        cell = run.name.removeprefix("phase3-main-").split("-r1")[0]
        requests = tuple(
            Request(
                cell=cell,
                program=event["program_id"],
                request_id=event.get("request_id", ""),
                timestamp=float(event["timestamp"]),
            )
            for event in events
            if event.get("event_type") == "REQUEST_ARRIVED"
        )
        decisions = []
        for event in events:
            if event.get("event_type") != "FORCED_RELEASE_DECISION":
                continue
            payload = event["payload"]
            decisions.append(
                Decision(
                    cell=cell,
                    timestamp=float(event["timestamp"]),
                    required_blocks=payload.get("required_blocks"),
                    candidates=tuple(
                        (str(candidate["program_id"]), str(candidate.get("prefix_id", "")))
                        for candidate in payload.get("candidates", [])
                    ),
                )
            )
        cells.append(CellData(cell=cell, requests=requests, decisions=tuple(decisions)))
    return cells


def _later_requests(cell: CellData, decision: Decision, horizon: float) -> list[Request]:
    return [
        request
        for request in cell.requests
        if decision.timestamp < request.timestamp <= decision.timestamp + horizon
    ]


def analyze_observed(cells: list[CellData], horizon: float) -> dict[str, Any]:
    decisions = [decision for cell in cells for decision in cell.decisions]
    distribution = Counter(len(decision.candidates) for decision in decisions)
    multi = [decision for decision in decisions if len(decision.candidates) >= 2]
    multi_groups = sorted({decision.cell.split("-")[0] for decision in multi})
    differential = []
    differential_groups: set[str] = set()
    downstream_counts = []
    for decision in multi:
        cell = next(cell for cell in cells if cell.cell == decision.cell)
        later = _later_requests(cell, decision, horizon)
        candidate_programs = {program for program, _ in decision.candidates}
        later_programs = {request.program for request in later}
        has_one_candidate_program = bool(candidate_programs & later_programs)
        has_missing_candidate_program = bool(candidate_programs - later_programs)
        downstream_counts.append(len(later))
        if has_one_candidate_program and has_missing_candidate_program:
            differential_groups.add(decision.cell.split("-")[0])
            differential.append(
                {
                    "cell": decision.cell,
                    "decision_timestamp": decision.timestamp,
                    "candidate_programs": sorted(candidate_programs),
                    "later_programs": sorted(later_programs),
                    "downstream_request_count": len(later),
                }
            )
    denominator_all = len(decisions)
    denominator_live = sum(1 for decision in decisions if decision.candidates)
    return {
        "decision_count": denominator_all,
        "decision_cells": len({decision.cell for decision in decisions}),
        "candidate_count_distribution": dict(sorted(distribution.items())),
        "multi_candidate_events": len(multi),
        "multi_candidate_groups": multi_groups,
        "multi_candidate_group_count": len(multi_groups),
        "multi_candidate_rate_all_decisions": len(multi) / denominator_all
        if denominator_all
        else 0.0,
        "multi_candidate_rate_live_decisions": len(multi) / denominator_live
        if denominator_live
        else 0.0,
        "denominators": {
            "all_forced_release_decision_events": denominator_all,
            "events_with_at_least_one_candidate": denominator_live,
        },
        "candidate_differential_downstream_opportunity": {
            "horizon_seconds": horizon,
            "numerator_events": len(differential),
            "denominator_multi_candidate_events": len(multi),
            "rate": len(differential) / len(multi) if multi else 0.0,
            "groups": sorted(differential_groups),
            "group_count": len(differential_groups),
            "events": differential,
            "label": "PROGRAM_LEVEL_DIFFERENTIAL_OPPORTUNITY",
            "not_a_prefix_hit_claim": True,
        },
        "downstream_request_counts": downstream_counts,
    }


def analyze_secondary_horizons(cells: list[CellData], horizons: list[float]) -> dict[str, Any]:
    return {str(horizon): analyze_observed(cells, horizon) for horizon in horizons}


def audit_data_sources(freeze: dict[str, Any], workspace: Path) -> dict[str, Any]:
    w1c_candidates = [
        workspace / "local" / "phase2-w1c-evidence",
        workspace / "local" / "continuum-w1c",
        workspace / "artifacts" / "phase2-w1c",
        workspace / "local" / "phase2-w1c",
    ]
    w1c_found = [str(path.relative_to(workspace)) for path in w1c_candidates if path.exists()]
    snapshot = freeze.get("data_sources", {}).get("protected_entry_snapshot", "")
    snapshot_path = (
        workspace / snapshot if snapshot and not snapshot.startswith("REQUIRED") else None
    )
    return {
        "w1c_report_available": (workspace / freeze["data_sources"]["w1c_report"]).exists(),
        "w1c_raw_trace_roots": w1c_found,
        "w1c_raw_traces_status": "PRESENT"
        if w1c_found
        else "W1C_RAW_TRACES_NOT_PRESENT_IN_WORKSPACE",
        "protected_entry_snapshot_status": (
            "PRESENT"
            if snapshot_path and snapshot_path.exists()
            else "PROTECTED_ENTRY_SNAPSHOT_NOT_PRESENT"
        ),
        "data_qualification": list(freeze.get("data_qualification", [])),
    }


def models_report(freeze: dict[str, Any], data_sources: dict[str, Any]) -> list[dict[str, Any]]:
    models = [freeze["primary_model"]]
    for model in freeze.get("sensitivity_models", []):
        if (
            model.get("candidate_source") == "protected_entry_snapshot"
            and data_sources["protected_entry_snapshot_status"] != "PRESENT"
        ):
            models.append(
                {
                    "id": model["id"],
                    "status": "NOT_EXECUTABLE_MISSING_PROTECTED_ENTRY_SNAPSHOT",
                    "reason": "the frozen archive exposes actual candidates, not the full protected-entry set; no modeled candidate expansion is fabricated",
                }
            )
        else:
            models.append(
                {
                    "id": model["id"],
                    "status": "NOT_EXECUTED_IN_E1A",
                    "reason": "E1-A only executes the primary observed-candidate model",
                }
            )
    return models


def render_report(campaign: dict[str, Any]) -> str:
    observed = campaign["observed"]
    diff = observed["candidate_differential_downstream_opportunity"]
    data = campaign["data_sources"]
    lines = [
        "# E1-A：Logical Candidate Exposure Feasibility Audit",
        "",
        "**Status:** `E1A_EXECUTED_DATA_GAP_FOR_MODELED_EXPOSURE`  ",
        "**Scope:** CPU-only, read-only existing Phase 3 archive; no W1-C raw traces were present.  ",
        "**Freeze config:** `configs/phase4/e1a-logical-exposure-freeze-v1.json`  ",
        f"**Freeze SHA-256:** `{campaign['freeze_sha256']}`",
        "",
        "## 0. Short answer",
        "",
        (
            f"- Phase 3 observed **{observed['multi_candidate_events']}/{observed['decision_count']}** multi-candidate decision events "
            f"({observed['multi_candidate_rate_all_decisions']:.3%}) across {observed['multi_candidate_group_count']} Groups; this is the already-known observed exposure, not a new natural-workload estimate."
        ),
        (
            f"- The primary program-level differential downstream-opportunity rate is **{diff['numerator_events']}/{diff['denominator_multi_candidate_events']}** "
            f"({diff['rate']:.3%}) at H={diff['horizon_seconds']:.0f}s across {diff['group_count']} Groups. This is a **program-level** opportunity, not a prefix-hit claim."
        ),
        "- The modeled retention models **cannot be executed**: the archive exposes actual candidate lists but not the full protected-entry set, and no W1-C raw traces are present in the workspace.",
        "- Therefore E1-A **does not establish natural/logical candidate expansion** and does not justify P1-B on current data.",
        "",
        "## 1. Frozen model and denominators",
        "",
        "| Item | Value |",
        "|---|---|",
        "| Primary model | `M0_OBSERVED_PHASE3` |",
        "| Candidate source | actual `FORCED_RELEASE_DECISION.candidates` |",
        "| Primary denominator | all forced-release decision events |",
        "| Secondary denominator | events with at least one candidate |",
        "| Primary H | 60s |",
        "| Secondary H | 15s / 300s (300s descriptive only; Phase 4 censoring 54.2%) |",
        "",
        "## 2. Observed exposure",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Decision events | {observed['decision_count']} |",
        f"| Cells | {observed['decision_cells']} |",
        f"| Candidate-count distribution | {observed['candidate_count_distribution']} |",
        f"| Multi-candidate events | {observed['multi_candidate_events']} |",
        f"| Multi-candidate Groups | {observed['multi_candidate_group_count']} |",
        f"| Rate over all decision events | {observed['multi_candidate_rate_all_decisions']:.3%} |",
        f"| Rate over live-candidate decision events | {observed['multi_candidate_rate_live_decisions']:.3%} |",
        "",
        "**Program-level differential downstream opportunity:**",
        "",
        f"- numerator: {diff['numerator_events']} multi-candidate events with a later request in a candidate program but not every candidate program;",
        f"- denominator: {diff['denominator_multi_candidate_events']} multi-candidate events;",
        f"- rate: {diff['rate']:.3%};",
        f"- differential Groups: {diff['group_count']} ({', '.join(diff['groups'])});",
        "- this is `PROGRAM_LEVEL_DIFFERENTIAL_OPPORTUNITY`, not a Native prefix-hit or physical-victim claim.",
        "",
        "### 2.1 Secondary horizons",
        "",
        "| H (s) | multi-candidate events | differential events | differential rate | note |",
        "|---:|---:|---:|---:|---|",
    ]
    for horizon, block in campaign["secondary_horizons"].items():
        block_diff = block["candidate_differential_downstream_opportunity"]
        note = "descriptive only (54.2% censored in Phase 4)" if float(horizon) >= 300 else ""
        lines.append(
            f"| {float(horizon):g} | {block['multi_candidate_events']} | "
            f"{block_diff['numerator_events']} | {block_diff['rate']:.3%} | {note} |"
        )
    lines += [
        "",
        "## 3. Data availability and why the modeled part is not executed",
        "",
        "| Item | Status |",
        "|---|---|",
        f"| W1-C report | {'present' if data['w1c_report_available'] else 'absent'} |",
        f"| W1-C raw traces | {data['w1c_raw_traces_status']} |",
        f"| Protected-entry snapshot | {data['protected_entry_snapshot_status']} |",
        "",
        "The frozen Phase 3 archive records actual candidate lists and free-queue snapshots, but not the complete set of protected entries that would be needed to generate counterfactual candidates under a different retention window. The W1-C report provides aggregate LCP/context statistics but no per-request raw trajectories in this workspace. E1-A therefore reports the observed exposure and declines to fabricate a modeled exposure rate.",
        "",
        "## 4. Model status",
        "",
        "| Model | Status |",
        "|---|---|",
    ]
    for model in campaign["models"]:
        lines.append(f"| {model['id']} | {model['status']} |")
    lines += [
        "",
        "The sensitivity models remain **pre-registered but not executable**; they are not dropped and no post-hoc model is substituted.",
        "",
        "## 5. Recommendation",
        "",
        "**Do not proceed to P1-B on the current data.** The observed Phase 3 exposure is still 7/127, and the modeled logical-expansion question cannot be answered without a representative multi-session trace or a protected-entry snapshot. The appropriate next action is either:",
        "",
        "1. provide a real W1-C raw-trace bundle and a protected-entry snapshot, then re-run this frozen audit; or",
        "2. stop P1-B on this workload family and report the exposure/evidence result.",
        "",
        "No GPU, Native smoke, production algorithm change, Protocol v5, or new data acquisition was performed.",
        "",
        "## 6. Reproduction",
        "",
        "```bash",
        "python scripts/probes/e1a_logical_exposure/audit.py \\",
        "    --evidence local/phase3-option-f-unified-270-runs-v2-evidence/phase3-option-f-unified-270-runs-v2 \\",
        "    --freeze  configs/phase4/e1a-logical-exposure-freeze-v1.json \\",
        "    --out     docs/experiments/e1a-logical-exposure-data",
        "```",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, default=Path("."))
    args = parser.parse_args(argv)

    freeze = load_freeze(args.freeze)
    cells = load_phase3(args.evidence)
    observed = analyze_observed(cells, float(freeze["primary_model"]["horizon_seconds"]))
    secondary = analyze_secondary_horizons(
        cells, [float(value) for value in freeze["metrics"]["secondary_horizons_seconds"]]
    )
    data_sources = audit_data_sources(freeze, args.workspace.resolve())
    models = models_report(freeze, data_sources)

    if observed["decision_count"] != 127 or observed["candidate_count_distribution"] != {
        1: 120,
        2: 7,
    }:
        raise ValueError("observed Phase 3 exposure does not match the frozen 127/120/7 archive")

    campaign = {
        "schema_version": "phase4.e1a_logical_exposure.v1",
        "status": "E1A_EXECUTED_DATA_GAP_FOR_MODELED_EXPOSURE",
        "authorization": freeze["authorization"],
        "freeze_sha256": hashlib.sha256(args.freeze.read_bytes()).hexdigest(),
        "observed": observed,
        "secondary_horizons": secondary,
        "data_sources": data_sources,
        "models": models,
        "recommendation": "DO_NOT_PROCEED_P1B_ON_CURRENT_DATA",
        "limitations": [
            "No W1-C raw per-request traces are present in the workspace.",
            "No complete protected-entry snapshot is present, so modeled candidate expansion is not identifiable.",
            "The observed candidate counts are actual Phase 3 decision payloads, not a natural multi-session serving estimate.",
            "The downstream differential metric is program-level, not a Native prefix-hit or physical-victim result.",
        ],
    }

    args.out.mkdir(parents=True, exist_ok=True)
    evidence_path = args.out / "e1a-logical-exposure-evidence.json"
    evidence_path.write_text(
        json.dumps(campaign, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    report_path = args.out / "e1a-logical-exposure-report.md"
    report_path.write_text(render_report(campaign), encoding="utf-8")
    files = [
        Path(__file__),
        Path(__file__).resolve().parents[3] / "tests" / "test_e1a_logical_exposure.py",
        Path(__file__).resolve().parents[3]
        / "configs"
        / "phase4"
        / "e1a-logical-exposure-freeze-v1.json",
        Path(__file__).resolve().parent / "README.md",
        evidence_path,
        report_path,
    ]
    manifest = []
    for path in files:
        manifest.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.as_posix()}")
    (args.out / "sha256-manifest.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    print(
        json.dumps({"status": campaign["status"], "observed": observed, "models": models}, indent=2)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
