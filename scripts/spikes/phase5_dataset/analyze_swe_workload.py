#!/usr/bin/env python3
"""CPU-only structural analysis of the frozen Phase 5 SWE workload.

This script never selects or changes a Cohort.  It reads the frozen Group
manifest and, when a private processed-evidence root is supplied, computes
context/reuse/tool-gap/overlap summaries from normalized traces and exact token
materials.  Without the private root it emits the structural metadata portion
and a `PENDING_PRIVATE_EVIDENCE_ROOT` status.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from itertools import pairwise
from pathlib import Path
from typing import Any

from kvopt.workload.phase5_dataset_processing import (
    load_normalized_trace,
    load_token_materializations,
)

BLOCK_SIZE = 16
PUBLIC_REFERENCE = {
    "source": "PR #135/#136 Nebius OpenHands public analysis",
    "units": "public OpenHands/Qwen3/Qwen2.5 projections; not Phase 5 Native evidence",
    "initial_input_p50_tokens": 6959,
    "final_input_p50_tokens": 50606,
    "adjacent_exact_lcp_p50_tokens": 30940,
    "adjacent_prefix_reuse_ratio_p50": 0.985,
    "cross_issue_first_request_lcp_p50_tokens": 5816,
    "same_issue_retry_first_request_lcp_p50_tokens": 6962,
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _p(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lo = int(position)
    hi = min(lo + 1, len(ordered) - 1)
    frac = position - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def _lcp(left: list[int], right: list[int]) -> int:
    count = 0
    for a, b in zip(left, right, strict=False):
        if a != b:
            break
        count += 1
    return count


def _block_lcp(left: list[int], right: list[int]) -> int:
    return (_lcp(left, right) // BLOCK_SIZE) * BLOCK_SIZE


def _stats(values: list[float]) -> dict[str, object]:
    if not values:
        return {"count": 0, "p50": None, "mean": None, "max": None}
    return {
        "count": len(values),
        "p50": _p(values, 0.5),
        "mean": statistics.fmean(values),
        "max": max(values),
    }


def _session_tokens(session_dir: Path) -> tuple[Any, dict[str, list[int]]]:
    trace = load_normalized_trace(session_dir / "normalized-trace.json")
    tokens = load_token_materializations(session_dir / "token-materialization.json")
    return trace, {row.request_id: list(row.token_ids) for row in tokens}


def _analyze_trace(
    session_dir: Path,
) -> dict[str, object]:
    trace, tokens = _session_tokens(session_dir)
    request_ids = [turn.request_id for turn in trace.turns]
    lengths = [len(tokens[rid]) for rid in request_ids if rid in tokens]
    consecutive_exact: list[int] = []
    consecutive_block: list[int] = []
    normalized_reuse: list[float] = []
    context_growth: list[int] = []
    exclusive_suffix: list[int] = []
    gaps: list[float] = []
    tool_execution: list[float] = []
    for left, right in pairwise(request_ids):
        if left not in tokens or right not in tokens:
            continue
        left_tokens = tokens[left]
        right_tokens = tokens[right]
        exact = _lcp(left_tokens, right_tokens)
        consecutive_exact.append(exact)
        consecutive_block.append((exact // BLOCK_SIZE) * BLOCK_SIZE)
        normalized_reuse.append(exact / len(right_tokens) if right_tokens else 0.0)
        context_growth.append(len(right_tokens) - len(left_tokens))
        exclusive_suffix.append(len(right_tokens) - exact)
    for turn in trace.turns:
        for message in turn.messages:
            for call in message.tool_calls:
                if call.started_at_seconds is None or call.ended_at_seconds is None:
                    continue
                if call.clock_domain != turn.clock_domain:
                    continue
                duration = call.ended_at_seconds - call.started_at_seconds
                if duration >= 0:
                    tool_execution.append(duration)
    for current, following in pairwise(trace.turns):
        if current.completed_at_seconds is None or following.submitted_at_seconds is None:
            continue
        if current.clock_domain != following.clock_domain:
            continue
        gap = following.submitted_at_seconds - current.completed_at_seconds
        if gap >= 0:
            gaps.append(gap)
    return {
        "program_id": trace.program_id,
        "turn_count": len(trace.turns),
        "request_ids": request_ids,
        "prompt_lengths": lengths,
        "prompt_length_stats": _stats([float(x) for x in lengths]),
        "consecutive_exact_lcp": consecutive_exact,
        "consecutive_block_lcp": consecutive_block,
        "normalized_prefix_reuse_ratio": normalized_reuse,
        "context_growth_tokens": context_growth,
        "exclusive_suffix_tokens": exclusive_suffix,
        "tool_gaps_seconds": gaps,
        "tool_execution_seconds": tool_execution,
        "first_request_tokens": tokens.get(request_ids[0]) if request_ids else None,
        "last_request_tokens": tokens.get(request_ids[-1]) if request_ids else None,
        "duration_seconds": (
            None
            if not trace.turns
            or trace.turns[0].submitted_at_seconds is None
            or trace.turns[-1].completed_at_seconds is None
            else trace.turns[-1].completed_at_seconds - trace.turns[0].submitted_at_seconds
        ),
    }


def _group_metadata(group: dict[str, Any]) -> dict[str, object]:
    repos = Counter(str(member["repository_id"]) for member in group["members"])
    return {
        "group_id": group["group_id"],
        "role": group["role"],
        "repository_counts": dict(sorted(repos.items())),
        "distinct_repositories": len(repos),
        "max_programs_in_repository": max(repos.values()) if repos else 0,
        "terminal_counts": dict(
            sorted(Counter(str(member["terminal_class"]) for member in group["members"]).items())
        ),
        "provenance_counts": dict(
            sorted(
                Counter(str(member["provenance_partition"]) for member in group["members"]).items()
            )
        ),
    }


def _group_trace_summary(
    group: dict[str, Any],
    analyses: dict[str, dict[str, object]],
) -> dict[str, object]:
    members = [analyses[str(member["program_id"])] for member in group["members"]]
    turns = [float(row["turn_count"]) for row in members]
    lengths = [float(v) for row in members for v in row["prompt_lengths"]]
    gaps = [float(v) for row in members for v in row["tool_gaps_seconds"]]
    tool_execution = [float(v) for row in members for v in row["tool_execution_seconds"]]
    exact = [float(v) for row in members for v in row["consecutive_exact_lcp"]]
    block = [float(v) for row in members for v in row["consecutive_block_lcp"]]
    reuse = [float(v) for row in members for v in row["normalized_prefix_reuse_ratio"]]
    growth = [float(v) for row in members for v in row["context_growth_tokens"]]
    suffix = [float(v) for row in members for v in row["exclusive_suffix_tokens"]]
    durations = [
        float(row["duration_seconds"]) for row in members if row["duration_seconds"] is not None
    ]
    return {
        "group_id": group["group_id"],
        "turn_count_stats": _stats(turns),
        "prompt_length_stats": _stats(lengths),
        "tool_gap_stats": _stats(gaps),
        "tool_execution_time_stats": _stats(tool_execution),
        "consecutive_exact_lcp_stats": _stats(exact),
        "consecutive_block_lcp_stats": _stats(block),
        "normalized_prefix_reuse_ratio_stats": _stats(reuse),
        "context_growth_token_stats": _stats(growth),
        "exclusive_suffix_token_stats": _stats(suffix),
        "duration_stats": _stats(durations),
        "missing_tool_gap_sessions": sum(not row["tool_gaps_seconds"] for row in members),
    }


def _cross_program_lcp(
    analyses: dict[str, dict[str, object]],
) -> dict[str, object]:
    first = {
        key: value["first_request_tokens"]
        for key, value in analyses.items()
        if value.get("first_request_tokens") is not None
    }
    pairs = []
    keys = sorted(first)
    for index, left in enumerate(keys):
        for right in keys[index + 1 :]:
            pairs.append(
                {
                    "left": left,
                    "right": right,
                    "exact_lcp": _lcp(first[left], first[right]),
                    "block_lcp": _block_lcp(first[left], first[right]),
                }
            )
    return {
        "pair_count": len(pairs),
        "exact_lcp_stats": _stats([float(row["exact_lcp"]) for row in pairs]),
        "block_lcp_stats": _stats([float(row["block_lcp"]) for row in pairs]),
        "positive_block_lcp_pairs": sum(row["block_lcp"] > 0 for row in pairs),
    }


def _arrival_overlap(
    group: dict[str, Any],
    analyses: dict[str, dict[str, object]],
    arrival_manifest: dict[str, Any],
) -> dict[str, object]:
    schedules = {row["group_id"]: row for row in arrival_manifest["groups"]}
    schedule = schedules.get(str(group["group_id"]))
    if not schedule:
        return {"status": "NO_ARRIVAL_SCHEDULE"}
    starts = {row["program_id"]: float(row["start_offset_seconds"]) for row in schedule["starts"]}
    intervals = []
    for member in group["members"]:
        pid = str(member["program_id"])
        analysis = analyses.get(pid)
        if analysis is None or analysis["duration_seconds"] is None or pid not in starts:
            continue
        start = starts[pid]
        intervals.append((start, start + float(analysis["duration_seconds"]), pid))
    overlaps = []
    for index, (a_start, a_end, a_id) in enumerate(intervals):
        for b_start, b_end, b_id in intervals[index + 1 :]:
            if max(0.0, min(a_end, b_end) - max(a_start, b_start)) > 0:
                overlaps.append({"left": a_id, "right": b_id})
    return {
        "status": "DESCRIPTIVE_ONLY",
        "sessions_with_duration": len(intervals),
        "overlapping_pairs": overlaps,
        "overlap_pair_count": len(overlaps),
        "note": "logical arrival overlap is not evidence of Native residency or legal candidate exposure",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group-manifest", type=Path, required=True)
    parser.add_argument("--arrival-manifest", type=Path, required=True)
    parser.add_argument("--processed-root", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    group_manifest = _load(args.group_manifest)
    arrival_manifest = _load(args.arrival_manifest)
    groups = group_manifest["groups"]
    result: dict[str, object] = {
        "schema_version": "phase5.swe_workload_structure.v1",
        "status": "PENDING_PRIVATE_EVIDENCE_ROOT",
        "cohort": {
            "program_count": sum(len(group["members"]) for group in groups),
            "group_count": len(groups),
            "repository_counts": dict(
                sorted(
                    Counter(
                        str(member["repository_id"])
                        for group in groups
                        for member in group["members"]
                    ).items()
                )
            ),
            "terminal_counts": dict(
                sorted(
                    Counter(
                        str(member["terminal_class"])
                        for group in groups
                        for member in group["members"]
                    ).items()
                )
            ),
            "provenance_counts": dict(
                sorted(
                    Counter(
                        str(member["provenance_partition"])
                        for group in groups
                        for member in group["members"]
                    ).items()
                )
            ),
        },
        "groups": [_group_metadata(group) for group in groups],
        "public_reference": PUBLIC_REFERENCE,
        "claim_boundary": [
            "structural metadata is not Native cache evidence",
            "logical prefix reuse is not Native APC hit rate",
            "arrival overlap is not legal candidate exposure",
            "no Cohort or Group re-selection",
        ],
    }

    roots = [root for root in args.processed_root if root.exists()]
    if roots:
        analyses: dict[str, dict[str, object]] = {}
        for group in groups:
            for member in group["members"]:
                pid = str(member["program_id"])
                session_id = str(member["session_id"])
                candidates = [root / "sessions" / session_id for root in roots]
                candidates.extend(root / pid for root in roots)
                session_dir = next(
                    (
                        candidate
                        for candidate in candidates
                        if (candidate / "normalized-trace.json").exists()
                    ),
                    candidates[0],
                )
                if not (session_dir / "normalized-trace.json").exists():
                    raise FileNotFoundError(
                        f"missing normalized trace for {pid} in processed roots"
                    )
                analyses[pid] = _analyze_trace(session_dir)
        result["status"] = "TRACE_ANALYSIS_COMPLETE"
        result["sessions"] = analyses
        all_members = [member for group in groups for member in group["members"]]
        result["trace_summary"] = _group_trace_summary(
            {"group_id": "SWE_ALL_48", "members": all_members}, analyses
        )
        result["cross_program"] = _cross_program_lcp(analyses)
        result["groups"] = [
            {
                **metadata,
                "trace_summary": _group_trace_summary(group, analyses),
                "arrival_overlap": _arrival_overlap(group, analyses, arrival_manifest),
            }
            for metadata, group in zip(result["groups"], groups, strict=True)
        ]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": result["status"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
