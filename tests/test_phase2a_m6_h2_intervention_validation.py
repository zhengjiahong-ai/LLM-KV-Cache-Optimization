import json
from pathlib import Path

import pytest

from kvopt.workload.phase2_h2_intervention_validation import (
    materialize_h2_intervention_validation,
)
from kvopt.workload.phase2_h2_intervention_validation_runner import (
    execute_h2_intervention_validation,
)

AUTHORIZATION = (
    Path(__file__).parents[1] / "configs/phase2/h2-measurement-authorization.json"
)
AUDIT = (
    Path(__file__).parents[1]
    / "docs/experiments/phase2a-m6-h2/native-intervention-validation.json"
)
AUDIT_V2 = (
    Path(__file__).parents[1]
    / "docs/experiments/phase2a-m6-h2/native-intervention-validation-v2.json"
)


def test_h2_intervention_validation_is_small_and_non_formal(tmp_path: Path) -> None:
    campaign_path = materialize_h2_intervention_validation(
        AUTHORIZATION,
        tmp_path / "validation",
    )
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))

    assert campaign["planned_run_count"] == 4
    assert not campaign["formal_measurement"]
    assert not campaign["formal_verdict"]
    assert [
        probe["expected_cached_prefix_tokens"] for probe in campaign["probes"]
    ] == [512, 448, 0, 0]
    assert [probe["position"] for probe in campaign["probes"]] == [
        None,
        "trailing",
        "leading",
        "trailing",
    ]
    for probe in campaign["probes"]:
        config = json.loads(
            (campaign_path.parent / probe["config"]).read_text(encoding="utf-8")
        )
        assert config["campaign_kind"] == "h2_intervention_validation"
        assert not config["backend_options"]["isolated_native_prefill_timing"]


def test_h2_intervention_validation_rejects_changed_config(
    tmp_path: Path,
) -> None:
    campaign_path = materialize_h2_intervention_validation(
        AUTHORIZATION,
        tmp_path / "validation",
    )
    config_path = campaign_path.parent / "h2v-leading-j4.config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["backend_options"]["h2_native_prefix_interventions"][
        "h2v-leading-j4:turn:1"
    ]["count"] = 1
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match="config hash mismatch"):
        execute_h2_intervention_validation(
            campaign_path,
            AUTHORIZATION,
            tmp_path / "runs",
        )
    assert not (tmp_path / "runs").exists()


def test_h2_intervention_validation_audit_preserves_non_formal_scope() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))

    assert audit["outcome"] == "PASS"
    assert audit["successful_run_count"] == 3
    assert audit["authorization_state"] == {
        "b1_authorized": False,
        "formal_measurement": False,
        "formal_verdict": False,
    }
    assert [probe["observed_cached_prefix_tokens"] for probe in audit["probes"]] == [
        512,
        448,
        0,
    ]
    assert all(len(probe["events_sha256"]) == 64 for probe in audit["probes"])


def test_h2_intervention_validation_v2_binds_long_context_fix() -> None:
    audit = json.loads(AUDIT_V2.read_text(encoding="utf-8"))

    assert audit["outcome"] == "PASS"
    assert audit["successful_run_count"] == 4
    assert audit["authorization_state"]["formal_measurement"] is False
    assert audit["prior_formal_attempt"]["disposition"].endswith("DO_NOT_RESUME")
    long_context = [
        probe for probe in audit["probes"] if probe["prefix_tokens"] == 1024
    ]
    assert len(long_context) == 1
    assert long_context[0]["observed_cached_prefix_tokens"] == 0
