import json
from dataclasses import replace
from pathlib import Path

import pytest

from kvopt.profiling.level_b_validation import _case_assertion
from kvopt.profiling.runtime_evidence import RequestRuntimeEvidenceRow
from kvopt.workload.phase2 import load_phase2_trace
from kvopt.workload.phase2_level_b_validation import (
    materialize_seam_validation_campaign,
)

BASE_CONFIG = (
    Path(__file__).parents[1] / "configs" / "phase2" / "metal-observability-config.json"
)


def _row() -> RequestRuntimeEvidenceRow:
    return RequestRuntimeEvidenceRow(
        run_id="run",
        request_id="agent-a:turn:2",
        program_id="agent-a",
        kind="turn",
        observation_event_index=4,
        native_request_id="native-2",
        availability="AVAILABLE",
        unavailable_reason=None,
        native_prompt_tokens=257,
        native_cached_prefix_tokens=128,
        native_apc_block_hashes=("01",),
        native_hash_block_size=16,
        native_hash_process_id="process",
        native_hash_function="sha256",
        eligible_prefix_tokens=256,
        actual_prefill_tokens=129,
        observed_recomputed_tokens=128,
        apc_outcome="PARTIAL_HIT",
        invariant_status="valid",
        native_clock_domain="engine_core_monotonic",
        native_queued_timestamp=1.0,
        native_scheduler_admission_timestamp=1.1,
        native_first_token_timestamp=1.3,
        native_queue_delay_seconds=0.1,
        native_queue_delay_status="available",
        native_prefill_to_first_token_seconds=0.2,
        native_prefill_to_first_token_status="available",
        isolated_native_prefill_elapsed_seconds=0.15,
        isolated_native_prefill_elapsed_status="available",
        backend_submission_timestamp=2.0,
        backend_completion_timestamp=2.5,
        backend_service_e2e_seconds=0.5,
        backend_service_e2e_status="available",
    )


def test_materializes_nonformal_s1_to_s5_campaign(tmp_path: Path) -> None:
    manifest_path = materialize_seam_validation_campaign(
        BASE_CONFIG,
        tmp_path / "seam-validation",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["campaign_kind"] == "instrumentation_seam_validation"
    assert not manifest["formal_h1_evidence"]
    assert not manifest["formal_h1_execution_authorized"]
    assert [item["case_id"][:2] for item in manifest["scenarios"]] == [
        "s1",
        "s2",
        "s3",
        "s4",
        "s5",
    ]
    for scenario in manifest["scenarios"]:
        config_path = manifest_path.parent / scenario["config"]
        config = json.loads(config_path.read_text(encoding="utf-8"))
        trace = load_phase2_trace(manifest_path.parent / config["trace"])
        assert config["campaign_kind"] == "instrumentation_seam_validation"
        assert config["cache"]["block_override"] * 16 >= 528
        assert trace.requests


def test_partial_and_fresh_suffix_cases_have_bounded_pressure(
    tmp_path: Path,
) -> None:
    manifest_path = materialize_seam_validation_campaign(
        BASE_CONFIG,
        tmp_path / "seam-validation",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_case = {item["case_id"]: item for item in manifest["scenarios"]}

    for case_id in (
        "s3-controlled-partial-hit",
        "s5-old-prefix-fresh-suffix",
    ):
        config_path = manifest_path.parent / by_case[case_id]["config"]
        config = json.loads(config_path.read_text(encoding="utf-8"))
        assert config["pressure"]["initial_shortage_blocks"] > 0
        assert config["backend_options"]["pressure_stage_prompt_tokens"]


@pytest.mark.parametrize(
    ("case_id", "row"),
    [
        (
            "s1-cold-no-eligible-prefix",
            replace(
                _row(),
                native_prompt_tokens=257,
                native_cached_prefix_tokens=0,
                eligible_prefix_tokens=0,
                actual_prefill_tokens=257,
                observed_recomputed_tokens=0,
                apc_outcome="NO_REUSE_ELIGIBLE_PREFIX",
            ),
        ),
        (
            "s2-no-eviction-full-hit",
            replace(
                _row(),
                native_cached_prefix_tokens=256,
                actual_prefill_tokens=1,
                observed_recomputed_tokens=0,
                apc_outcome="FULL_HIT",
            ),
        ),
        ("s3-controlled-partial-hit", _row()),
        (
            "s4-controlled-full-loss",
            replace(
                _row(),
                native_cached_prefix_tokens=0,
                actual_prefill_tokens=257,
                observed_recomputed_tokens=256,
                apc_outcome="MISS",
            ),
        ),
        ("s5-old-prefix-fresh-suffix", _row()),
    ],
)
def test_s1_to_s5_assertions_accept_frozen_semantics(
    case_id: str,
    row: RequestRuntimeEvidenceRow,
) -> None:
    assert _case_assertion(case_id, row) == (True, None)
