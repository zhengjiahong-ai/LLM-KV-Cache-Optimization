"""Read-only Phase 5 session-turn sensitivity analysis."""

from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

TURN_CAPS: tuple[int | None, ...] = (16, 32, 50, 64, 100, None)
MIN_TURNS = 4
MAX_PROMPT_TOKENS = 32640
NATURAL_EXIT_STATUSES = frozenset({"Submitted"})
STEP_LIMIT_EXIT_STATUSES = frozenset({"LimitsExceeded"})
CONTEXT_EXIT_STATUSES = frozenset({"ContextLengthExceeded"})
INFRASTRUCTURE_EXIT_STATUSES = frozenset({"JobTimeoutError"})


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _relative(path: Path, repository: Path) -> str:
    try:
        return str(path.resolve().relative_to(repository.resolve()))
    except ValueError:
        return str(path.resolve())


def _lcp(first: Sequence[int], second: Sequence[int]) -> int:
    count = 0
    for left, right in zip(first, second, strict=False):
        if left != right:
            break
        count += 1
    return count


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    return float(ordered[lower] * (1 - fraction) + ordered[upper] * fraction)


def _distribution(values: Iterable[float]) -> dict[str, float | int | None]:
    rows = list(values)
    return {
        "count": len(rows),
        "minimum": min(rows) if rows else None,
        "p25": _percentile(rows, 0.25),
        "median": _percentile(rows, 0.5),
        "p75": _percentile(rows, 0.75),
        "p95": _percentile(rows, 0.95),
        "maximum": max(rows) if rows else None,
        "mean": sum(rows) / len(rows) if rows else None,
    }


def _terminal_class(exit_status: str) -> str:
    if exit_status in NATURAL_EXIT_STATUSES:
        return "NATURAL_COMPLETION"
    if exit_status in STEP_LIMIT_EXIT_STATUSES:
        return "STEP_LIMIT_RIGHT_CENSORED"
    if exit_status in CONTEXT_EXIT_STATUSES:
        return "CONTEXT_LIMIT_FAILURE"
    if exit_status in INFRASTRUCTURE_EXIT_STATUSES:
        return "INFRASTRUCTURE_FAILURE"
    return "OTHER_FAILURE_OR_INCOMPLETE"


@dataclass(frozen=True, slots=True)
class SessionRow:
    source_stratum: str
    acquisition_origin: str
    task_id: str
    program_id: str
    session_id: str
    trace_id: str
    raw_run_identity: str
    attempt_source: str
    raw_run_path: str
    raw_run_sha256: str
    raw_sidecar_path: str
    raw_sidecar_sha256: str
    adapted_record_path: str
    adapted_record_sha256: str
    normalized_trace_path: str
    normalized_trace_sha256: str
    token_materialization_path: str
    token_materialization_sha256: str
    qualification_path: str
    qualification_sha256: str
    source_revision: str
    acquisition_config_path: str
    acquisition_config_sha256: str
    execution_step_limit: int
    turn_count: int
    request_id_sequence: tuple[str, ...]
    prompt_token_counts: tuple[int, ...]
    prompt_token_minimum: int
    prompt_token_maximum: int
    prompt_token_total: int
    prompt_token_first: int
    prompt_token_last: int
    adjacent_prefix_pair_count: int
    adjacent_prefix_lcp_counts: tuple[int, ...]
    adjacent_prefix_lcp_total: int
    adjacent_prefix_lcp_mean: float
    adjacent_prefix_lcp_maximum: int
    tool_call_count: int
    tool_wait_seconds_total: float
    tool_wait_seconds_maximum: float
    inter_turn_gap_seconds_total: float
    inter_turn_gap_seconds_maximum: float
    session_duration_seconds: float
    raw_exit_status: str
    terminal_class: str
    right_censored: bool
    q1: bool
    q2: bool
    q3: bool
    q4: bool
    q5: bool
    q6: bool
    q7: bool
    q8: bool
    q9: bool
    failed_rules: tuple[str, ...]
    failure_reason: str | None

    def to_csv_row(self) -> dict[str, object]:
        value = asdict(self)
        for name in (
            "request_id_sequence",
            "prompt_token_counts",
            "adjacent_prefix_lcp_counts",
            "failed_rules",
        ):
            value[name] = json.dumps(value[name], separators=(",", ":"))
        return value


def _completed_attempts_by_hash(ledger: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    attempts = ledger.get("attempts")
    if not isinstance(attempts, list):
        raise TypeError("attempt ledger lacks attempts")
    result: dict[str, Mapping[str, object]] = {}
    for value in attempts:
        if not isinstance(value, Mapping) or value.get("status") != "completed":
            continue
        digest = value.get("run_json_sha256")
        if not isinstance(digest, str):
            raise TypeError("completed attempt lacks run_json_sha256")
        if digest in result:
            raise ValueError(f"duplicate completed run identity: {digest}")
        result[digest] = value
    return result


def load_phase5_swe_sessions(
    *,
    repository: Path,
    processed_root: Path,
    adapted_root: Path,
    attempt_ledger_path: Path,
) -> tuple[list[SessionRow], dict[str, object]]:
    """Rebuild one row per normalized Phase 5 SWE session from bound evidence."""

    repository = repository.resolve()
    ledger = _load_json(attempt_ledger_path)
    completed_by_hash = _completed_attempts_by_hash(ledger)
    session_root = processed_root / "sessions"
    rows: list[SessionRow] = []
    seen_sessions: set[str] = set()
    for directory in sorted(session_root.iterdir()):
        if not directory.is_dir():
            continue
        trace_path = directory / "normalized-trace.json"
        token_path = directory / "token-materialization.json"
        qualification_path = directory / "qualification.json"
        trace = _load_json(trace_path)
        tokens = _load_json(token_path)
        qualification = _load_json(qualification_path)
        task_id = str(trace["task_id"])
        adapted_path = adapted_root / f"{task_id}.json"
        adapted = _load_json(adapted_path)
        run_hash = str(adapted["original_artifact_sha256"]["run.json"])
        attempt = completed_by_hash.get(run_hash)
        if attempt is None:
            raise ValueError(f"no completed attempt binds processed task {task_id}")
        run_path = Path(str(attempt["run_directory"])) / "run.json"
        if not run_path.is_file() or _sha256(run_path) != run_hash:
            raise ValueError(f"raw run binding failed for {task_id}")
        run = _load_json(run_path)
        sidecar_path = run_path.parent / "acquisition-sidecar.json"
        sidecar = _load_json(sidecar_path)
        session_id = str(trace["session_id"])
        if session_id in seen_sessions:
            raise ValueError(f"duplicate normalized session: {session_id}")
        seen_sessions.add(session_id)

        turns = trace["turns"]
        if not isinstance(turns, list) or not turns:
            raise ValueError(f"session {session_id} has no successful model turns")
        token_rows = tokens
        if not isinstance(token_rows, list) or len(token_rows) != len(turns):
            raise ValueError(f"turn/token cardinality mismatch for {session_id}")
        token_by_request = {str(item["request_id"]): item for item in token_rows}
        request_ids = tuple(str(turn["request_id"]) for turn in turns)
        if set(request_ids) != set(token_by_request):
            raise ValueError(f"request/token identity mismatch for {session_id}")
        token_ids = [token_by_request[request_id]["token_ids"] for request_id in request_ids]
        token_counts = tuple(len(value) for value in token_ids)
        lcps = [_lcp(left, right) for left, right in itertools.pairwise(token_ids)]
        inter_turn_gaps = [
            max(
                0.0,
                float(current["submitted_at_seconds"])
                - float(previous["completed_at_seconds"]),
            )
            for previous, current in itertools.pairwise(turns)
        ]
        tool_calls = sidecar.get("tool_calls", [])
        if not isinstance(tool_calls, list):
            raise TypeError(f"tool_calls is not an array for {session_id}")
        tool_waits = [
            max(
                0.0,
                float(call["tool_completion_monotonic_seconds"])
                - float(call["tool_start_monotonic_seconds"]),
            )
            for call in tool_calls
        ]
        checks = qualification["checks"]
        q_values: dict[str, bool] = {}
        for index in range(1, 10):
            matching = [value for name, value in checks.items() if name.startswith(f"Q{index}_")]
            if len(matching) != 1 or not isinstance(matching[0], bool):
                raise ValueError(f"qualification lacks unique Q{index} for {session_id}")
            q_values[f"q{index}"] = matching[0]
        exit_status = str(run.get("agent_exit_status", "UNKNOWN"))
        terminal_class = _terminal_class(exit_status)
        failure_reason = None
        if terminal_class != "NATURAL_COMPLETION":
            limitations = adapted.get("limitations", [])
            failure_reason = "; ".join(map(str, limitations)) or exit_status
        source_revision = str(trace["provenance"]["source_revision"])
        config_path = Path(str(run["config_path"]))
        if not config_path.is_file():
            config_path = repository / "configs/phase3/phase3-agent-acquisition-v1.json"
        rows.append(
            SessionRow(
                source_stratum="SWE",
                acquisition_origin=str(adapted["acquisition_origin"]),
                task_id=task_id,
                program_id=str(trace["program_id"]),
                session_id=session_id,
                trace_id=str(trace["trace_id"]),
                raw_run_identity=f"{attempt['attempt_source']}:{task_id}:{run_hash}",
                attempt_source=str(attempt["attempt_source"]),
                raw_run_path=_relative(run_path, repository),
                raw_run_sha256=run_hash,
                raw_sidecar_path=_relative(sidecar_path, repository),
                raw_sidecar_sha256=_sha256(sidecar_path),
                adapted_record_path=_relative(adapted_path, repository),
                adapted_record_sha256=_sha256(adapted_path),
                normalized_trace_path=_relative(trace_path, repository),
                normalized_trace_sha256=_sha256(trace_path),
                token_materialization_path=_relative(token_path, repository),
                token_materialization_sha256=_sha256(token_path),
                qualification_path=_relative(qualification_path, repository),
                qualification_sha256=_sha256(qualification_path),
                source_revision=source_revision,
                acquisition_config_path=_relative(config_path, repository),
                acquisition_config_sha256=str(run["config_sha256"]),
                execution_step_limit=int(run["effective_step_limit"]),
                turn_count=len(turns),
                request_id_sequence=request_ids,
                prompt_token_counts=token_counts,
                prompt_token_minimum=min(token_counts),
                prompt_token_maximum=max(token_counts),
                prompt_token_total=sum(token_counts),
                prompt_token_first=token_counts[0],
                prompt_token_last=token_counts[-1],
                adjacent_prefix_pair_count=len(lcps),
                adjacent_prefix_lcp_counts=tuple(lcps),
                adjacent_prefix_lcp_total=sum(lcps),
                adjacent_prefix_lcp_mean=sum(lcps) / len(lcps) if lcps else 0.0,
                adjacent_prefix_lcp_maximum=max(lcps, default=0),
                tool_call_count=len(tool_calls),
                tool_wait_seconds_total=sum(tool_waits),
                tool_wait_seconds_maximum=max(tool_waits, default=0.0),
                inter_turn_gap_seconds_total=sum(inter_turn_gaps),
                inter_turn_gap_seconds_maximum=max(inter_turn_gaps, default=0.0),
                session_duration_seconds=max(
                    0.0,
                    float(turns[-1]["completed_at_seconds"])
                    - float(turns[0]["submitted_at_seconds"]),
                ),
                raw_exit_status=exit_status,
                terminal_class=terminal_class,
                right_censored=terminal_class == "STEP_LIMIT_RIGHT_CENSORED",
                failed_rules=tuple(qualification["failed_rules"]),
                failure_reason=failure_reason,
                **q_values,
            )
        )
    metadata = {
        "attempt_count": int(ledger["attempt_count"]),
        "completed_attempt_count": sum(
            1 for value in ledger["attempts"] if value["status"] == "completed"
        ),
        "failed_attempt_count": sum(
            1 for value in ledger["attempts"] if value["status"] == "failed"
        ),
        "unique_completed_count": int(ledger["unique_completed_count"]),
        "processed_session_count": len(rows),
        "deduplication_rule": (
            "one normalized session_id per task; bind the processed raw run SHA-256 "
            "to exactly one completed attempt; failed attempts remain attempt-level only"
        ),
        "attempt_ledger_path": _relative(attempt_ledger_path, repository),
        "attempt_ledger_sha256": _sha256(attempt_ledger_path),
    }
    return rows, metadata


def _other_qualification_passes(row: SessionRow) -> bool:
    return all((row.q1, row.q2, row.q3, row.q4, row.q5, row.q7, row.q8, row.q9))


def classify_for_cap(row: SessionRow, cap: int | None) -> str:
    """Return one mutually exclusive retention classification for a candidate cap."""

    if row.turn_count < MIN_TURNS:
        return "EXCLUDED_BELOW_MIN_TURNS"
    if cap is not None and row.turn_count > cap:
        return "EXCLUDED_ABOVE_TURN_CAP"
    if row.prompt_token_maximum > MAX_PROMPT_TOKENS:
        return "EXCLUDED_CONTEXT_PROMPT_LIMIT"
    if row.terminal_class == "CONTEXT_LIMIT_FAILURE":
        return "EXCLUDED_CONTEXT_LIMIT_FAILURE"
    if row.terminal_class == "INFRASTRUCTURE_FAILURE":
        return "EXCLUDED_INFRASTRUCTURE_FAILURE"
    if row.terminal_class == "OTHER_FAILURE_OR_INCOMPLETE":
        return "EXCLUDED_OTHER_FAILURE"
    if not _other_qualification_passes(row):
        return "EXCLUDED_OTHER_Q1_Q9"
    return "RETAINED"


def _cap_label(cap: int | None) -> str:
    return "OBSERVED_NO_ADDITIONAL_CAP" if cap is None else str(cap)


def analyze_sensitivity(rows: Sequence[SessionRow]) -> dict[str, object]:
    results = []
    strata = sorted({row.source_stratum for row in rows} | {"SWE", "BFCL"})
    for cap in TURN_CAPS:
        by_stratum = []
        for stratum in strata:
            selected = [row for row in rows if row.source_stratum == stratum]
            classifications = Counter(classify_for_cap(row, cap) for row in selected)
            retained = [row for row in selected if classify_for_cap(row, cap) == "RETAINED"]
            context_observable = [
                row
                for row in selected
                if row.terminal_class == "CONTEXT_LIMIT_FAILURE"
                and row.turn_count >= MIN_TURNS
                and (cap is None or row.turn_count <= cap)
            ]
            by_stratum.append(
                {
                    "source_stratum": stratum,
                    "observed_sessions": len(selected),
                    "retained_sessions": len(retained),
                    "excluded_sessions": len(selected) - len(retained),
                    "retained_fraction": len(retained) / len(selected) if selected else None,
                    "excluded_fraction": (
                        (len(selected) - len(retained)) / len(selected)
                        if selected
                        else None
                    ),
                    "turn_window_eligible_sessions": sum(
                        row.turn_count >= MIN_TURNS
                        and (cap is None or row.turn_count <= cap)
                        for row in selected
                    ),
                    "group_count_upper_bound": len(retained) // 4,
                    "retained_natural_completion": sum(
                        row.terminal_class == "NATURAL_COMPLETION" for row in retained
                    ),
                    "retained_step_limit_right_censored": sum(
                        row.terminal_class == "STEP_LIMIT_RIGHT_CENSORED"
                        for row in retained
                    ),
                    "context_failures_observed_within_cap": len(context_observable),
                    "classification_counts": dict(sorted(classifications.items())),
                    "turn_count": _distribution([row.turn_count for row in retained]),
                    "prompt_token_maximum": _distribution(
                        [row.prompt_token_maximum for row in retained]
                    ),
                    "prompt_token_total": _distribution(
                        [row.prompt_token_total for row in retained]
                    ),
                    "prompt_token_growth_first_to_last": _distribution(
                        [row.prompt_token_last - row.prompt_token_first for row in retained]
                    ),
                    "session_duration_seconds": _distribution(
                        [row.session_duration_seconds for row in retained]
                    ),
                    "tool_wait_seconds_total": _distribution(
                        [row.tool_wait_seconds_total for row in retained]
                    ),
                    "tool_wait_seconds_maximum": _distribution(
                        [row.tool_wait_seconds_maximum for row in retained]
                    ),
                    "adjacent_prefix_lcp_total": _distribution(
                        [row.adjacent_prefix_lcp_total for row in retained]
                    ),
                }
            )
        results.append({"turn_cap": _cap_label(cap), "by_stratum": by_stratum})
    return {
        "schema_version": "phase5.session_turn_sensitivity.v1",
        "minimum_turns": MIN_TURNS,
        "prompt_token_limit": MAX_PROMPT_TOKENS,
        "caps": results,
    }


def build_analysis(
    *, rows: Sequence[SessionRow], acquisition_metadata: Mapping[str, object]
) -> dict[str, object]:
    band_counts = Counter(
        "ABOVE_16" if row.turn_count > 16 else "FOUR_TO_16" if row.turn_count >= 4 else "BELOW_4"
        for row in rows
    )
    terminal_counts = Counter(row.terminal_class for row in rows)
    long_rows = [row for row in rows if row.turn_count > 16]
    inputs = {
        "phase5_new_acquisition_sessions": len(rows),
        "bfcl_sessions_available": sum(row.source_stratum == "BFCL" for row in rows),
        "historical_w1_records_included": 0,
        "historical_evidence_role": "SEPARATE_BACKGROUND_NOT_MIXED",
        **dict(acquisition_metadata),
    }
    analysis = {
        "schema_version": "phase5.session_turn_analysis.v1",
        "status": "COMPLETE_WITH_BFCL_DATA_GAP",
        "inputs": inputs,
        "observed_distribution": {
            "session_count": len(rows),
            "turn_band_counts": dict(sorted(band_counts.items())),
            "terminal_counts": dict(sorted(terminal_counts.items())),
            "turn_count": _distribution([row.turn_count for row in rows]),
            "prompt_token_maximum": _distribution(
                [row.prompt_token_maximum for row in rows]
            ),
            "prompt_token_limit_exceeded_by_successful_turn": sum(
                row.prompt_token_maximum > MAX_PROMPT_TOKENS for row in rows
            ),
        },
        "long_session_research_proxies": {
            "session_count_above_16": len(long_rows),
            "successful_turns_above_first_16": sum(
                row.turn_count - 16 for row in long_rows
            ),
            "adjacent_prefix_pairs_above_16_lower_bound": sum(
                row.turn_count - 16 for row in long_rows
            ),
            "long_session_adjacent_prefix_lcp_total": sum(
                row.adjacent_prefix_lcp_total for row in long_rows
            ),
            "long_session_tool_calls": sum(row.tool_call_count for row in long_rows),
            "interpretation": (
                "trajectory-level opportunity only; does not establish Native cache hits, "
                "candidate exposure, physical victims, eviction, recomputation, or benefit"
            ),
        },
        "sensitivity": analyze_sensitivity(rows),
        "recommendation": {
            "decision": "REMOVE_ADDITIONAL_PROTOCOL_TURN_CAP",
            "retain_minimum_turns": MIN_TURNS,
            "retain_prompt_token_limit": MAX_PROMPT_TOKENS,
            "retain_explicit_collection_termination": True,
            "right_censoring_must_remain_explicit": True,
            "rationale": (
                "Within observed Phase 5 SWE data, caps 16 through 64 retain only the two "
                "natural sessions already admitted at 4-16 turns. Cap 100 and no additional "
                "cap both retain 35 sessions: two natural completions and 33 explicitly "
                "step-limit-right-censored sessions. Successful prompts remain <=32640. "
                "The extra cap therefore discards observed multi-turn/prefix evidence without "
                "adding context protection; context and infrastructure failures remain excluded."
            ),
            "limitations": [
                "BFCL acquisition artifacts were not available in this snapshot.",
                "Thirty-three retained long sessions are right-censored at the collector limit.",
                "More turns do not increase the independent statistical unit count beyond groups.",
                "Trajectory proxies cannot establish Native KV behavior or algorithmic benefit.",
            ],
        },
    }
    analysis["analysis_sha256"] = _canonical_sha256(analysis)
    return analysis


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_outputs(
    *,
    repository: Path,
    output_root: Path,
    rows: Sequence[SessionRow],
    analysis: Mapping[str, object],
    base_git_sha: str,
) -> dict[str, str]:
    if output_root.exists():
        raise FileExistsError(output_root)
    output_root.mkdir(parents=True)
    detail_path = output_root / "session-details.csv"
    detail_rows = [row.to_csv_row() for row in rows]
    if not detail_rows:
        raise ValueError("cannot write an empty session detail table")
    with detail_path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=list(detail_rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(detail_rows)
    summary_path = output_root / "turn-cap-sensitivity.json"
    _write_json(summary_path, analysis)
    sensitivity = analysis.get("sensitivity")
    if not isinstance(sensitivity, Mapping) or not isinstance(
        sensitivity.get("caps"), list
    ):
        raise TypeError("analysis lacks sensitivity rows")
    summary_rows: list[dict[str, object]] = []
    for cap in sensitivity["caps"]:
        if not isinstance(cap, Mapping) or not isinstance(cap.get("by_stratum"), list):
            raise TypeError("sensitivity cap row is invalid")
        for stratum in cap["by_stratum"]:
            if not isinstance(stratum, Mapping):
                raise TypeError("sensitivity stratum row is invalid")
            summary_rows.append(
                {
                    "turn_cap": cap["turn_cap"],
                    "source_stratum": stratum["source_stratum"],
                    "observed_sessions": stratum["observed_sessions"],
                    "turn_window_eligible_sessions": stratum[
                        "turn_window_eligible_sessions"
                    ],
                    "retained_sessions": stratum["retained_sessions"],
                    "excluded_sessions": stratum["excluded_sessions"],
                    "retained_fraction": stratum["retained_fraction"],
                    "excluded_fraction": stratum["excluded_fraction"],
                    "retained_natural_completion": stratum[
                        "retained_natural_completion"
                    ],
                    "retained_step_limit_right_censored": stratum[
                        "retained_step_limit_right_censored"
                    ],
                    "context_failures_observed_within_cap": stratum[
                        "context_failures_observed_within_cap"
                    ],
                    "group_count_upper_bound": stratum["group_count_upper_bound"],
                    "classification_counts": json.dumps(
                        stratum["classification_counts"], separators=(",", ":")
                    ),
                }
            )
    summary_csv_path = output_root / "turn-cap-summary.csv"
    with summary_csv_path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=list(summary_rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(summary_rows)
    input_inventory = {
        "schema_version": "phase5.session_turn_input_inventory.v1",
        "base_git_sha": base_git_sha,
        "analysis_code_bindings": [
            {
                "path": path,
                "sha256": _sha256(repository / path),
            }
            for path in (
                "src/kvopt/workload/phase5_turn_sensitivity.py",
                "scripts/probes/phase5_session_turn_sensitivity.py",
            )
        ],
        "read_only_analysis": True,
        "protocol_modified": False,
        "source_files": [],
    }
    source_bindings: dict[str, str] = {}
    for row in rows:
        source_bindings.update(
            {
                row.raw_run_path: row.raw_run_sha256,
                row.raw_sidecar_path: row.raw_sidecar_sha256,
                row.adapted_record_path: row.adapted_record_sha256,
                row.normalized_trace_path: row.normalized_trace_sha256,
                row.token_materialization_path: row.token_materialization_sha256,
                row.qualification_path: row.qualification_sha256,
            }
        )
    analysis_inputs = analysis.get("inputs")
    if not isinstance(analysis_inputs, Mapping):
        raise TypeError("analysis input inventory is missing")
    ledger_relative = analysis_inputs.get("attempt_ledger_path")
    if not isinstance(ledger_relative, str):
        raise TypeError("analysis lacks the attempt ledger path")
    source_bindings[ledger_relative] = _sha256(repository / ledger_relative)
    input_inventory["source_files"] = [
        {"path": path, "sha256": digest}
        for path, digest in sorted(source_bindings.items())
    ]
    inventory_path = output_root / "input-inventory.json"
    _write_json(inventory_path, input_inventory)
    hashes = {
        path.name: _sha256(path)
        for path in (detail_path, summary_csv_path, summary_path, inventory_path)
    }
    manifest_path = output_root / "sha256-manifest.txt"
    manifest_path.write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(hashes.items())),
        encoding="utf-8",
    )
    hashes[manifest_path.name] = _sha256(manifest_path)
    return hashes
