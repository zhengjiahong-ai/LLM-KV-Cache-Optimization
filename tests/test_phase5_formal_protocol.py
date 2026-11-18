"""Tests for the Phase 5 Formal Protocol contracts and schema validation."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "probes" / "phase5_formal_protocol" / "validate.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("phase5_formal_validate", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _protocol():
    return json.loads(
        (ROOT / "configs/phase5/phase5-formal-protocol-v1.json").read_text(encoding="utf-8")
    )


def _schema():
    return json.loads(
        (ROOT / "configs/phase5/schema/phase5-formal-protocol-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )


def test_valid_protocol_and_contracts() -> None:
    module = _load_module()
    result = module.validate_repository(ROOT)
    assert result["execution_authorized"] is False
    assert result["systems"] == [
        "CONTINUUM_ADAPTED",
        "CONTINUUM_OFFICIAL",
        "COST_AWARE",
        "NATIVE",
    ]
    assert result["manifest_schema"] == "valid"


def test_rejects_execution_authorization() -> None:
    module = _load_module()
    protocol = _protocol()
    protocol["execution_authorized"] = True
    try:
        module.validate_protocol(protocol, _schema())
    except ValueError as error:
        assert "non-executable" in str(error) or "schema" in str(error)
    else:
        raise AssertionError("authorized protocol was accepted")


def test_rejects_wrong_system_set() -> None:
    module = _load_module()
    protocol = _protocol()
    protocol["systems"] = protocol["systems"][:3]
    try:
        module.validate_protocol(protocol, _schema())
    except ValueError as error:
        assert "four registered" in str(error) or "schema" in str(error)
    else:
        raise AssertionError("three-system protocol was accepted")


def test_rejects_bad_sample_bounds() -> None:
    module = _load_module()
    protocol = _protocol()
    protocol["workload"]["sample_plan"]["groups_per_stratum_min"] = 20
    try:
        module.validate_protocol(protocol, _schema())
    except ValueError as error:
        assert "sample-size" in str(error)
    else:
        raise AssertionError("invalid sample bounds were accepted")


def test_rejects_missing_unresolved_decisions() -> None:
    module = _load_module()
    protocol = _protocol()
    protocol["unresolved"] = protocol["unresolved"][:-1]
    try:
        module.validate_protocol(protocol, _schema())
    except ValueError as error:
        assert "unresolved" in str(error)
    else:
        raise AssertionError("missing unresolved decisions were accepted")


def test_rejects_missing_primary_contrast() -> None:
    module = _load_module()
    protocol = _protocol()
    protocol["statistics"]["primary_contrasts"] = protocol["statistics"]["primary_contrasts"][:2]
    try:
        module.validate_protocol(protocol, _schema())
    except ValueError as error:
        assert "contrasts" in str(error)
    else:
        raise AssertionError("two-contrast protocol was accepted")


def test_rejects_session_below_four_turns() -> None:
    module = _load_module()
    protocol = _protocol()
    protocol["workload"]["min_turns_per_session"] = 3
    try:
        module.validate_protocol(protocol, _schema())
    except ValueError as error:
        assert "four turns" in str(error)
    else:
        raise AssertionError("three-turn qualification was accepted")


def test_rejects_prompt_plus_generation_over_context() -> None:
    module = _load_module()
    protocol = _protocol()
    protocol["workload"]["max_prompt_tokens"] = 32768
    try:
        module.validate_protocol(protocol, _schema())
    except ValueError as error:
        assert "prompt plus generation" in str(error)
    else:
        raise AssertionError("over-context prompt was accepted")


def test_rejects_non_provisional_cost_aware_candidate() -> None:
    module = _load_module()
    protocol = _protocol()
    protocol["cost_aware_candidate"]["status"] = "FROZEN"
    try:
        module.validate_protocol(protocol, _schema())
    except ValueError as error:
        assert "DVA_ER_V1" in str(error) or "PROVISIONAL" in str(error)
    else:
        raise AssertionError("prematurely frozen candidate was accepted")


def test_rejects_insufficient_gpu_budget() -> None:
    module = _load_module()
    protocol = _protocol()
    protocol["calibration"]["gpu_hours_minimum"] = 36
    try:
        module.validate_protocol(protocol, _schema())
    except ValueError as error:
        assert "48 hours" in str(error)
    else:
        raise AssertionError("36-hour budget was accepted for the minimum sample")


def test_contracts_and_manifest_schema_are_valid() -> None:
    module = _load_module()
    contracts_schema = json.loads(
        (ROOT / "configs/phase5/schema/phase5-contracts-v1.schema.json").read_text(encoding="utf-8")
    )
    contracts = module.validate_contracts(ROOT, contracts_schema)
    assert set(contracts) == {
        "metrics",
        "workload_qualification",
        "calibration_sample_size",
        "cost_aware_candidate",
    }
    module.validate_manifest_schema(ROOT)
