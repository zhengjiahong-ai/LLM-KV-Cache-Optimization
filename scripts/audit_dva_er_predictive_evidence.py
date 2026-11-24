"""Inventory existing evidence for DVA-ER without imputing scores or Native losses."""
import argparse
from collections import Counter
import csv
from hashlib import file_digest
import json
from pathlib import Path, PurePosixPath
import tarfile

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
EXPERIMENTS = DOCS / "experiments"
PHASE2D_SHA = "1bfbbb5314a48569a94a8b1b7c8ff999b73cc4870acf60144bf1ce325094256e"
PHASE2G_SHA = "da932167be664458295bde182284f8a76762cfe66d63c7d6a046afc3bfbad802"
NOT_EVALUABLE = "NOT_EVALUABLE"


def read_json(path):
    return json.loads(path.read_bytes())


def unique_index(rows, key):
    indexed = {}
    for row in rows:
        identity = key(row)
        if identity in indexed:
            raise ValueError(f"Duplicate evidence identity: {identity!r}")
        indexed[identity] = row
    return indexed


def event_archive(path, expected_sha, stage_dirs=()):
    if path is None:
        return {"inspection": "RAW_ARCHIVE_NOT_SUPPLIED"}
    with path.open("rb") as stream:
        if file_digest(stream, "sha256").hexdigest() != expected_sha:
            raise ValueError(f"Unexpected archive SHA-256: {path.name}")

    types, fields = Counter(), Counter()
    run_ids = set()
    excluded_event_files = 0
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            if not member.isfile() or PurePosixPath(member.name).name != "events.jsonl":
                continue
            if stage_dirs and not set(stage_dirs).intersection(PurePosixPath(member.name).parts):
                excluded_event_files += 1
                continue
            events = [json.loads(line) for line in archive.extractfile(member)]
            unique_index(events, lambda event: (event["run_id"], event["event_index"]))
            runs = {event["run_id"] for event in events}
            if len(runs) != 1 or run_ids & runs:
                raise ValueError(f"Ambiguous run identity in {member.name}")
            run_ids.update(runs)
            for event in events:
                kind, payload = event["event_type"], event["payload"]
                types[kind] += 1
                fields["explicit_armed_timer_events"] += (
                    payload.get("pending_tool_gap_source") == "CONTROLLER_ARMED_TIMER"
                    or "CONTROLLER_ARMED_TIMER" in json.dumps(payload)
                )
                fields["dva_named_events"] += (
                    "DVA_ER" in kind.upper() or str(payload.get("policy", "")).upper() == "DVA_ER_V1"
                )
                if kind == "FORCED_RELEASE_DECISION":
                    fields["forced_decisions_with_multiple_candidates"] += len(payload["candidates"]) > 1
                    fields["forced_decisions_with_recorded_queue"] += bool(payload.get("original_free_queue"))
                    fields["forced_decisions_with_explicit_id"] += bool(payload.get("decision_id"))
                if kind == "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED":
                    fields["native_evictions_with_decision_id"] += bool(payload.get("decision_id"))
                    fields["native_evictions_with_refcount"] += payload.get("ref_count_before") is not None
                if kind == "FOLLOWUP_WAITING":
                    fields["waiting_events_with_payload"] += bool(payload)
                if kind == "PRESSURE_REQUEST_COMPLETED":
                    fields["pressure_completions_with_selected_block_ids"] += bool(
                        payload.get("last_selected_block_ids")
                    )
                if kind == "VLLM_NATIVE_REQUEST_OBSERVATION":
                    fields["request_observations_with_hash_process_id"] += bool(
                        payload.get("native_hash_process_id")
                    )
    if not run_ids:
        raise ValueError("No event files in pinned archive")
    relevant = (
        "FORCED_RELEASE_DECISION", "FORCED_RELEASE_DECISION_BINDING",
        "NATIVE_ENTRY_RELEASE_SELECTION_PLAN", "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED",
        "VLLM_REQUEST_SUBMITTED", "VLLM_NATIVE_REQUEST_OBSERVATION", "FOLLOWUP_WAITING",
        "TOOL_GAP_STARTED", "TOOL_GAP_ENDED", "PRESSURE_REQUEST_COMPLETED",
    )
    return {"inspection": "HASH_VERIFIED_RAW_EVENTS", "sha256": expected_sha,
            "event_runs": len(run_ids), "excluded_noncanonical_event_files": excluded_event_files,
            "events": {name: types[name] for name in relevant},
            "event_fields": dict(fields)}


def comparative_geometry(candidates, need, losses):
    """Retrospective comparison on existing P2-verified paths and Stage 0 labels."""
    indexed = unique_index(candidates, lambda row: row["program"])
    if set(indexed) != set(losses) or len(indexed) != 2:
        raise ValueError("Geometry and loss candidates differ")
    surviving = {}
    for program, row in indexed.items():
        depth, length = row["first_victim_depth"], row["chain_length"]
        if not 1 <= depth <= length or length - depth + 1 != need:
            raise ValueError("Expected the P2-verified contiguous victim suffix")
        surviving[program] = depth - 1
    longest = max(surviving.values())
    best_geometry = {p for p, depth in surviving.items() if depth == longest}
    # Counts and contiguous candidate suffix size tie by construction for this strict subset.
    return {
        "minimum_surviving_prefix_blocks": surviving,
        "deeper_prefix_best_candidates": sorted(best_geometry),
        "deeper_prefix_ordinal": (
            "TIED_LABEL" if len(set(losses.values())) == 1
            else "TIED_GEOMETRY" if len(best_geometry) == 2
            else "CONCORDANT" if losses[next(iter(best_geometry))] == min(losses.values())
            else "DISCORDANT"
        ),
    }


def historical_comparison(native_a0, stage0, p2):
    competitive = unique_index(
        (r for r in native_a0 if int(r["candidate_count"]) > 1),
        lambda r: (r["group_id"], r["condition"].lower(), int(r["forced_event_index"])),
    )
    real_geometry = unique_index((r for r in p2["rows"] if r["label"] == "REAL"),
                                 lambda r: (r["cell"], r["decision_index"]))
    cells = unique_index(stage0["cells"], lambda r: r["cell"])
    results = []
    used_geometry = set()
    for record in stage0["p2"]["rows"]:
        cell = record["cell"]
        group, condition = cell.split("-")
        source = competitive.pop((group, condition, record["decision_event_index"]))
        observed = cells[cell]
        [index] = observed["competitive_indices"]
        [alt] = observed["alternatives"]
        [alternative] = alt["competitive_programs"]
        [chosen] = json.loads(source["selected_programs"])
        need = record["need"]
        if (chosen != record["a0_program"] or chosen == alternative
                or observed["competitive_a0_programs"] != [chosen]
                or int(source["decision_ordinal"]) != index + 1
                or observed["need"] != need
                or int(source["matched_physical_blocks"]) != need
                or observed["baseline_recomputed"] - alt["total_recomputed"] != alt["gain_tokens"]):
            raise ValueError(f"Stage 0 and Native audit evidence differ: {cell}")
        losses = {chosen: 0, alternative: -alt["gain_tokens"]}
        row = {"cell": cell, "run_id": source["run_id"], "decision_id": source["decision_id"],
               "forced_event_index": record["decision_event_index"], "a0_program": chosen,
               "relative_stage0_window_loss_tokens": losses,
               "assumed_victim_blocks": dict.fromkeys(losses, need),
               "score": NOT_EVALUABLE, "native_candidate_recompute_attribution": "NOT_ESTABLISHED"}
        geometry = real_geometry.get((cell, index))
        if geometry is not None:
            if geometry["a0_program"] != chosen:
                raise ValueError(f"P2 selected Entry differs from the A0 record: {cell}")
            row.update(comparative_geometry(geometry["candidates"], need, losses))
            used_geometry.add((cell, index))
        results.append(row)
    if competitive or used_geometry != set(real_geometry):
        raise ValueError("Unmatched competitive decision or P2 geometry")
    return results


def phase3_inventory():
    exposure = EXPERIMENTS / "phase3-algorithm-exposure-audit-data"
    with (exposure / "decision-audit.csv").open(encoding="utf-8", newline="") as stream:
        decisions = list(csv.DictReader(stream))
    unique_index(decisions, lambda r: (r["run_id"], r["decision_id"]))
    if any(r["arm"] not in {"A0", "A1", "A2", "A3", "E0"}
           or r["downstream_recompute_attribution"] != "NOT_ESTABLISHED" for r in decisions):
        raise ValueError("Phase 3 scope has changed; inspect the new downstream evidence")
    source = read_json(exposure / "summary.json")
    arms = {}
    submissions = {}
    per_request_count = 0
    for path in sorted((EXPERIMENTS / "phase3-actual-order-audit-data/cells").glob("*.json")):
        cell = read_json(path)
        for arm, run in cell["arms"].items():
            run_id = run["run_id"]
            if run_id in submissions:
                raise ValueError(f"Duplicate observed-order run {run_id}")
            requests = unique_index(run["requests"], lambda r: r["request_id"])
            order = run["actual_submission_sequence"]
            if len(order) != len(requests) or set(order) != set(requests):
                raise ValueError(f"Request order and outcome identity differ: {run_id}")
            submissions[run_id] = (cell["group_id"], cell["condition"], arm)
            per_request_count += len(requests)
    for row in decisions:
        if submissions.get(row["run_id"]) != (row["group_id"], row["condition"], row["arm"]):
            raise ValueError(f"Cannot match Native decision to observed-order run: {row['run_id']}")
    for arm in sorted({r["arm"] for r in decisions}):
        rows = [r for r in decisions if r["arm"] == arm]
        arms[arm] = {
            "forced_decisions": len(rows),
            "competitive": sum(int(r["candidate_count"]) > 1 for r in rows),
            "physical_outcome_statuses": dict(Counter(r["physical_outcome_status"] for r in rows)),
            "downstream_attribution": dict(Counter(r["downstream_recompute_attribution"] for r in rows)),
        }
    stage0 = read_json(EXPERIMENTS / "phase3-stage0-oracle-data/stage0-evidence.json")
    p2 = read_json(EXPERIMENTS / "phase3-p2-depth-data/p2-depth-evidence.json")
    a0 = [r for r in decisions if r["arm"] == "A0"]
    pairs = historical_comparison(a0, stage0, p2)
    return {
        "raw_archive": {"filename": source["source_archive"], "sha256": source["source_archive_sha256"],
                        "inspection": "CHECKED_IN_DERIVATIVES_ONLY"},
        "main_runs_with_observed_request_order": len(submissions),
        "main_request_arm_outcomes": per_request_count, "arms": arms,
        "legacy_candidate_comparison": {
            "label": "EXISTING_A0_ANCHORED_STAGE0_COUNTERFACTUAL_WINDOW_DELTA",
            "distinct_groups": len({r["cell"].split("-")[0] for r in pairs}),
            "equal_victim_budget_pairs": len(pairs),
            "unequal_window_losses": sum(len(set(r["relative_stage0_window_loss_tokens"].values())) > 1
                                         for r in pairs),
            "strict_p2_geometry_pairs": sum("deeper_prefix_ordinal" in r for r in pairs),
            "depth_order_by_label": dict(Counter(r["deeper_prefix_ordinal"] for r in pairs
                                                 if "deeper_prefix_ordinal" in r)),
            "cases": pairs,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase2d", type=Path)
    parser.add_argument("--phase2g", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    phase2d = read_json(DOCS / "phase2d-m6-headroom-result.json")
    phase4 = read_json(EXPERIMENTS / "phase4-session-continuation-data/phase4-session-continuation-evidence.json")
    result = {
        "phase2d": {"raw": event_archive(args.phase2d, PHASE2D_SHA, (
                        "phase2d-e2-runs-v1", "phase2d-e3-paired-headroom-runs-v1",
                        "phase2d-e4-concurrency-runs-v1",
                    )),
                    "paired_intervention": phase2d["stages"]["E3"]},
        "phase2g_gate2_v3": event_archive(args.phase2g, PHASE2G_SHA),
        "phase3": phase3_inventory(),
        "phase4_same_archive": {"status": phase4["status"], "audit": phase4["audit"]},
        "native_predictive_gate": {
            "matched_score_victim_request_labels": 0,
            "status": NOT_EVALUABLE,
            "scope": "Audited sources only. No complete DVA-ER decision-time score to Native loss join.",
        },
    }
    for archive in (result["phase2d"]["raw"], result["phase2g_gate2_v3"]):
        if archive.get("event_fields", {}).get("dva_named_events", 0):
            raise ValueError("Unexpected DVA-ER event in historical archive; extend the evidence audit")
    body = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(body, encoding="utf-8", newline="\n")
    else:
        print(body, end="")


if __name__ == "__main__":
    main()
