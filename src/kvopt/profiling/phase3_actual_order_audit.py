"""Read-only sensitivity audit using observed Native submission order."""

from __future__ import annotations

import hashlib
import json
import tarfile
from collections.abc import Mapping, Sequence
from contextlib import closing, nullcontext
from pathlib import Path

from kvopt.workload.phase3_option_f import evaluate_option_f_results

from .ingestion import ArtifactValidationError
from .phase3_nec import (
    _chain,
    _common_prefix,
    _concurrent_visibility_audit,
    _derive_request,
    _event_index,
    _identity,
    _integer,
    _object,
)

ARMS = ("N0", "A0", "A1", "A2", "A3", "E0")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def classify_observed_sequences(
    sequences: Mapping[str, Sequence[str]], frozen: Sequence[str]
) -> str:
    """Classify exact-to-frozen and cross-arm execution-order equality."""

    if set(sequences) != set(ARMS):
        raise ArtifactValidationError("observed sequence audit requires all six arms")
    rows = [tuple(sequences[arm]) for arm in ARMS]
    if all(row == tuple(frozen) for row in rows):
        return "EXACT_TO_FROZEN"
    if len(set(rows)) == 1:
        return "CROSS_ARM_IDENTICAL_BUT_FROZEN_MISMATCH"
    return "CROSS_ARM_DIFFERENT"


def _events_by_type(
    events: Sequence[Mapping[str, object]], event_type: str
) -> list[Mapping[str, object]]:
    return sorted(
        (row for row in events if row.get("event_type") == event_type),
        key=lambda row: _event_index(row, event_type),
    )


def observed_submission_sequence(
    events: Sequence[Mapping[str, object]], expected_request_ids: frozenset[str]
) -> tuple[str, ...]:
    rows = _events_by_type(events, "VLLM_REQUEST_SUBMITTED")
    sequence = tuple(
        str(row["request_id"])
        for row in rows
        if row.get("request_id") in expected_request_ids
    )
    if len(sequence) != len(expected_request_ids) or set(sequence) != expected_request_ids:
        raise ArtifactValidationError("actual Native submission request set is incomplete")
    return sequence


def _logical_completion_indices(
    events: Sequence[Mapping[str, object]], expected: frozenset[str]
) -> dict[str, int]:
    result = {}
    for row in _events_by_type(events, "CONTROLLED_REPLAY_TIME_ADVANCED"):
        payload = _object(row.get("payload"), "logical replay event payload")
        boundary = payload.get("boundary_id")
        if not isinstance(boundary, str) or not boundary.startswith("completion:"):
            continue
        request_id = boundary.removeprefix("completion:")
        if request_id in expected:
            result[request_id] = _event_index(row, "logical completion")
    return result


def audit_arm_actual_order(
    *,
    arm: str,
    events: Sequence[Mapping[str, object]],
    frozen_requests: Sequence[tuple[str, str]],
    frozen_request_results: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Recompute E from actual earlier submissions and visibility evidence."""

    expected_ids = frozenset(identity[1] for identity in frozen_requests)
    expected_by_id = {identity[1]: identity for identity in frozen_requests}
    frozen_by_id = {
        str(row["request_id"]): row for row in frozen_request_results
    }
    if set(frozen_by_id) != expected_ids:
        raise ArtifactValidationError("frozen N/E/C request inventory mismatch")
    submissions = _events_by_type(events, "VLLM_REQUEST_SUBMITTED")
    submission_by_id = {
        str(row["request_id"]): row
        for row in submissions
        if row.get("request_id") in expected_ids
    }
    actual_order = observed_submission_sequence(events, expected_ids)
    observations = {
        _identity(row, "native observation")[1]: row
        for row in _events_by_type(events, "VLLM_NATIVE_REQUEST_OBSERVATION")
        if row.get("request_id") in expected_ids
    }
    snapshots: dict[str, list[Mapping[str, object]]] = {}
    for row in _events_by_type(events, "VLLM_PREFIX_SNAPSHOT"):
        request_id = row.get("request_id")
        if request_id in expected_ids:
            snapshots.setdefault(str(request_id), []).append(row)
    completions = {
        _identity(row, "request completion")[1]: _integer(
            _object(row.get("payload"), "request completion payload").get(
                "output_token_count"
            ),
            "output_token_count",
        )
        for row in _events_by_type(events, "VLLM_REQUEST_COMPLETED")
        if row.get("request_id") in expected_ids
    }
    logical_completions = _logical_completion_indices(events, expected_ids)
    if set(observations) != expected_ids or set(submission_by_id) != expected_ids:
        raise ArtifactValidationError("actual-order audit lacks request evidence")

    position = {request_id: index for index, request_id in enumerate(actual_order)}
    rows = []
    for request_id in actual_order:
        identity = expected_by_id[request_id]
        observation = observations[request_id]
        current = _chain(
            _object(observation.get("payload"), "native observation payload"),
            hashes_field="native_apc_block_hashes",
            label="native observation",
        )
        consumer_submission_index = _event_index(
            submission_by_id[request_id], "consumer submission"
        )
        prior_snapshots: list[Mapping[str, object]] = []
        visibility_rows = []
        minimum_blocks = 0
        indeterminate_reasons: list[str] = []
        for producer_id in actual_order[: position[request_id]]:
            producer_observation = observations[producer_id]
            producer_chain = _chain(
                _object(
                    producer_observation.get("payload"),
                    "producer native observation payload",
                ),
                hashes_field="native_apc_block_hashes",
                label="producer native observation",
            )
            compatible = (
                producer_chain.process_id == current.process_id
                and producer_chain.hash_function == current.hash_function
                and producer_chain.block_size == current.block_size
            )
            lcp_blocks = (
                _common_prefix(current.hashes, producer_chain.hashes)
                if compatible
                else 0
            )
            if lcp_blocks <= minimum_blocks:
                visibility_rows.append(
                    {
                        "producer_request_id": producer_id,
                        "qualification": "DOMINATED_OR_NO_SHARED_PREFIX",
                        "hash_lcp_blocks": lcp_blocks,
                    }
                )
                continue
            producer_snapshots = snapshots.get(producer_id, [])
            if len(producer_snapshots) != 1:
                indeterminate_reasons.append(
                    f"{producer_id}:SNAPSHOT_COUNT_{len(producer_snapshots)}"
                )
                continue
            producer_snapshot = producer_snapshots[0]
            snapshot_index = _event_index(producer_snapshot, "producer snapshot")
            logical_completion_index = logical_completions.get(producer_id)
            base = {
                "producer_request_id": producer_id,
                "actual_earlier_submission": True,
                "producer_submission_event_index": _event_index(
                    submission_by_id[producer_id], "producer submission"
                ),
                "consumer_submission_event_index": consumer_submission_index,
                "logical_completion_event_index": logical_completion_index,
                "logical_completion_before_consumer_submission": (
                    logical_completion_index is not None
                    and logical_completion_index < consumer_submission_index
                ),
                "snapshot_event_index": snapshot_index,
                "snapshot_before_consumer_submission": (
                    snapshot_index < consumer_submission_index
                ),
                "hash_lcp_blocks": lcp_blocks,
            }
            if snapshot_index < consumer_submission_index:
                prior_snapshots.append(producer_snapshot)
                minimum_blocks = lcp_blocks
                visibility_rows.append(
                    {
                        **base,
                        "qualification": "SNAPSHOT_VISIBLE_BEFORE_CONSUMER_SUBMISSION",
                    }
                )
                continue

            producer_payload = _object(
                producer_observation.get("payload"),
                "producer native observation payload",
            )
            consumer_payload = _object(
                observation.get("payload"), "consumer native observation payload"
            )
            producer_scheduled = producer_payload.get(
                "native_scheduler_admission_timestamp"
            )
            consumer_scheduled = consumer_payload.get(
                "native_scheduler_admission_timestamp"
            )
            if not isinstance(producer_scheduled, (int, float)) or not isinstance(
                consumer_scheduled, (int, float)
            ):
                indeterminate_reasons.append(
                    f"{producer_id}:SCHEDULER_VISIBILITY_TIMESTAMPS_MISSING"
                )
                continue
            if producer_scheduled > consumer_scheduled:
                visibility_rows.append(
                    {
                        **base,
                        "qualification": "PRODUCER_SCHEDULED_AFTER_CONSUMER",
                    }
                )
                continue
            consumer_snapshots = snapshots.get(request_id, [])
            if len(consumer_snapshots) > 1:
                indeterminate_reasons.append(
                    f"{request_id}:CONSUMER_SNAPSHOT_COUNT_{len(consumer_snapshots)}"
                )
                continue
            try:
                audit, qualified = _concurrent_visibility_audit(
                    producer_identity=expected_by_id[producer_id],
                    consumer_identity=identity,
                    producer_observation=producer_observation,
                    consumer_observation=observation,
                    producer_snapshot=producer_snapshot,
                    consumer_snapshot=(
                        consumer_snapshots[0] if consumer_snapshots else None
                    ),
                    minimum_eligible_blocks=minimum_blocks,
                )
            except ArtifactValidationError as error:
                indeterminate_reasons.append(f"{producer_id}:{error}")
                continue
            visibility_rows.append({**base, **audit})
            if qualified:
                prior_snapshots.append(producer_snapshot)
                minimum_blocks = max(minimum_blocks, int(audit["hash_lcp_blocks"]))

        frozen = frozen_by_id[request_id]
        row = {
            "arm": arm,
            "request_id": request_id,
            "program_id": identity[0],
            "actual_submission_position": position[request_id],
            "frozen_eligible_prefix_tokens": frozen.get("eligible_prefix_tokens"),
            "visibility_audits": visibility_rows,
            "indeterminate_reasons": indeterminate_reasons,
        }
        if indeterminate_reasons:
            row.update(
                {
                    "status": "INDETERMINATE",
                    "actual_eligible_prefix_tokens": None,
                    "actual_recomputed_tokens": None,
                }
            )
            rows.append(row)
            continue
        try:
            derived = _derive_request(
                observation,
                prior_snapshots,
                completion_output_tokens=completions.get(request_id),
                concurrent_eligibility_audits=visibility_rows,
            )
        except ArtifactValidationError as error:
            row.update(
                {
                    "status": "INDETERMINATE",
                    "actual_eligible_prefix_tokens": None,
                    "actual_recomputed_tokens": None,
                    "indeterminate_reasons": [str(error)],
                }
            )
            rows.append(row)
            continue
        row.update(
            {
                "status": "DETERMINATE",
                "actual_eligible_prefix_tokens": derived.eligible_prefix_tokens,
                "native_cached_prefix_tokens": derived.native_cached_prefix_tokens,
                "actual_recomputed_tokens": derived.recomputed_tokens,
                "eligible_delta_vs_frozen": (
                    derived.eligible_prefix_tokens
                    - int(frozen["eligible_prefix_tokens"])
                ),
            }
        )
        rows.append(row)
    return {
        "arm": arm,
        "actual_submission_sequence": list(actual_order),
        "actual_submission_sequence_sha256": _canonical_sha(list(actual_order)),
        "status": (
            "PASS" if all(row["status"] == "DETERMINATE" for row in rows)
            else "INDETERMINATE"
        ),
        "requests": rows,
        "aggregate_recomputed_tokens": (
            sum(int(row["actual_recomputed_tokens"]) for row in rows)
            if all(row["status"] == "DETERMINATE" for row in rows)
            else None
        ),
    }


def _member(tar: tarfile.TarFile, suffix: str) -> tarfile.TarInfo:
    matches = [row for row in tar.getmembers() if row.isfile() and row.name.endswith(suffix)]
    if len(matches) != 1:
        raise ValueError(f"archive member is not unique: {suffix}")
    return matches[0]


def _json(tar: tarfile.TarFile, suffix: str) -> dict[str, object]:
    handle = tar.extractfile(_member(tar, suffix))
    if handle is None:
        raise ValueError(f"archive member cannot be read: {suffix}")
    value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"archive member must contain an object: {suffix}")
    return value


def _jsonl(tar: tarfile.TarFile, suffix: str) -> list[dict[str, object]]:
    handle = tar.extractfile(_member(tar, suffix))
    if handle is None:
        raise ValueError(f"archive member cannot be read: {suffix}")
    return [json.loads(line) for line in handle]


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def audit_actual_order_archive(
    *,
    execution_archive: Path,
    cohort_seal: Path,
    classification_path: Path,
    output_directory: Path,
    evidence_directory: Path | None = None,
) -> dict[str, object]:
    """Audit all 40 cells and six arms from the immutable execution archive."""

    if output_directory.exists():
        raise FileExistsError(output_directory)
    output_directory.mkdir(parents=True)
    cohort = json.loads(cohort_seal.read_text(encoding="utf-8"))
    classification = json.loads(classification_path.read_text(encoding="utf-8"))
    if not isinstance(classification, dict):
        raise TypeError("Option F classification must contain an object")
    groups = {
        str(row["group_id"]): row
        for row in cohort["groups"]
        if isinstance(row, dict)
    }
    category_counts = {
        "EXACT_TO_FROZEN": 0,
        "CROSS_ARM_IDENTICAL_BUT_FROZEN_MISMATCH": 0,
        "CROSS_ARM_DIFFERENT": 0,
    }
    cell_reports = []
    actual_results = []
    if evidence_directory is None:
        context = closing(tarfile.open(execution_archive))  # noqa: SIM115
        directory = None
    else:
        directory = evidence_directory.resolve()
        if not directory.is_dir():
            raise FileNotFoundError(directory)
        context = nullcontext(None)

    def read_json(archive: tarfile.TarFile | None, suffix: str) -> dict[str, object]:
        if archive is not None:
            return _json(archive, suffix)
        if directory is None:
            raise RuntimeError("evidence directory reader is unavailable")
        path = directory / suffix
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError(f"evidence file must contain an object: {path}")
        return value

    def read_jsonl(
        archive: tarfile.TarFile | None, suffix: str
    ) -> list[dict[str, object]]:
        if archive is not None:
            return _jsonl(archive, suffix)
        if directory is None:
            raise RuntimeError("evidence directory reader is unavailable")
        path = directory / suffix
        return [json.loads(line) for line in path.read_bytes().splitlines()]

    with context as archive:
        original_main = read_json(archive, "main-report.json")
        for group_id in sorted(groups):
            frozen_order = groups[group_id]["native_enqueue_order"]
            frozen_requests = [
                (request_id.split(":turn:", 1)[0], request_id)
                for request_id in frozen_order
            ]
            for condition in ("c1", "c2"):
                arms = {}
                sequences = {}
                for arm in ARMS:
                    run_id = f"phase3-main-{group_id}-{condition}-r1-{arm.lower()}"
                    events = read_jsonl(
                        archive, f"native-runs/{run_id}/events.jsonl"
                    )
                    frozen_result = read_json(archive, f"results/{run_id}.json")
                    frozen_requests_result = frozen_result.get("nec", {}).get(
                        "requests"
                    )
                    if not isinstance(frozen_requests_result, list):
                        raise TypeError(f"run lacks frozen N/E/C requests: {run_id}")
                    audit = audit_arm_actual_order(
                        arm=arm,
                        events=events,
                        frozen_requests=frozen_requests,
                        frozen_request_results=frozen_requests_result,
                    )
                    audit["run_id"] = run_id
                    arms[arm] = audit
                    sequences[arm] = audit["actual_submission_sequence"]
                    if audit["status"] == "PASS":
                        actual_results.append(
                            {
                                "run_id": run_id,
                                "group_id": group_id,
                                "condition": condition.upper(),
                                "arm": arm,
                                "repeat": 1,
                                "aggregate_recomputed_tokens": audit[
                                    "aggregate_recomputed_tokens"
                                ],
                            }
                        )
                category = classify_observed_sequences(sequences, frozen_order)
                category_counts[category] += 1
                determinate = all(row["status"] == "PASS" for row in arms.values())
                cross_arm_e_equal = False
                if determinate:
                    by_request = []
                    for index in range(len(frozen_order)):
                        values = {
                            arms[arm]["requests"][index][
                                "actual_eligible_prefix_tokens"
                            ]
                            for arm in ARMS
                        }
                        by_request.append(len(values) == 1)
                    cross_arm_e_equal = all(by_request)
                cell = {
                    "group_id": group_id,
                    "condition": condition.upper(),
                    "sequence_classification": category,
                    "frozen_sequence_sha256": _canonical_sha(frozen_order),
                    "observed_sequence_sha256_by_arm": {
                        arm: arms[arm]["actual_submission_sequence_sha256"]
                        for arm in ARMS
                    },
                    "actual_e_status": (
                        "PASS"
                        if determinate and cross_arm_e_equal
                        else "FAIL_CROSS_ARM_E"
                        if determinate
                        else "INDETERMINATE"
                    ),
                    "cross_arm_e_equal": cross_arm_e_equal,
                    "arms": arms,
                }
                _write(
                    output_directory
                    / "cells"
                    / f"{group_id}-{condition}.json",
                    cell,
                )
                cell_reports.append(cell)

    valid_cells = [row for row in cell_reports if row["actual_e_status"] == "PASS"]
    actual_main_report = None
    if len(valid_cells) == 40 and len(actual_results) == 240:
        actual_main_report = evaluate_option_f_results(actual_results, classification)
        actual_effect_status = "RECOMPUTED_FIXED_POPULATION"
    else:
        actual_effect_status = "NOT_CONFIRMATORY_DESCRIPTIVE_ONLY"

    request_audit_rows = [
        request
        for cell in cell_reports
        for arm in cell["arms"].values()
        for request in arm["requests"]
    ]
    frozen_actual_e_difference_count = sum(
        request.get("actual_eligible_prefix_tokens")
        != request.get("frozen_eligible_prefix_tokens")
        for request in request_audit_rows
        if request.get("actual_eligible_prefix_tokens") is not None
    )

    effect_comparison = None
    if actual_main_report is not None:
        original_effects = {
            "primary": original_main["primary"],
            "H3_0": original_main["H3_0"],
            "H3_R": original_main["H3_R"],
        }
        recomputed_effects = {
            "primary": actual_main_report["primary"],
            "H3_0": actual_main_report["H3_0"],
            "H3_R": actual_main_report["H3_R"],
        }
        effect_comparison = {
            "original": original_effects,
            "actual_order_recomputed": recomputed_effects,
            "identical": original_effects == recomputed_effects,
        }
    summary = {
        "schema_version": "phase3.actual_order_sensitivity_audit.v1",
        "source_archive_sha256": _sha256(execution_archive),
        "cell_count": len(cell_reports),
        "sequence_classification_counts": category_counts,
        "actual_e_pass_cell_count": len(valid_cells),
        "actual_e_indeterminate_cell_count": sum(
            row["actual_e_status"] == "INDETERMINATE" for row in cell_reports
        ),
        "actual_e_cross_arm_failure_cell_count": sum(
            row["actual_e_status"] == "FAIL_CROSS_ARM_E" for row in cell_reports
        ),
        "request_audit_count": len(request_audit_rows),
        "frozen_actual_e_difference_count": frozen_actual_e_difference_count,
        "effect_recomputation_status": actual_effect_status,
        "effect_comparison": effect_comparison,
        "original_main_report": original_main,
        "actual_main_report": actual_main_report,
        "actual_results": actual_results,
        "terminology": {
            "protocol_g1": "ARM_ISOLATION",
            "frozen_replay_execution_conformance": (
                "ACTUAL_NATIVE_ENQUEUE_ORDER_EQUALS_COHORT_SEAL"
            ),
            "cross_arm_execution_equality": (
                "ALL_SIX_ARMS_HAVE_IDENTICAL_ACTUAL_NATIVE_ENQUEUE_ORDER"
            ),
        },
    }
    _write(output_directory / "summary.json", summary)
    manifest = []
    for path in sorted(output_directory.rglob("*")):
        if path.is_file() and path.name != "sha256-manifest.txt":
            manifest.append(f"{_sha256(path)}  {path.relative_to(output_directory)}")
    (output_directory / "sha256-manifest.txt").write_text(
        "\n".join(manifest) + "\n", encoding="utf-8"
    )
    return summary
