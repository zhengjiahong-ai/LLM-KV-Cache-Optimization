"""Tests for the E1-A logical-exposure audit."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "probes" / "e1a_logical_exposure" / "audit.py"
FREEZE_PATH = ROOT / "configs" / "phase4" / "e1a-logical-exposure-freeze-v1.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("e1a_audit", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _cell(module):
    requests = (
        module.Request("c1", "p1", "p1:1", 0.0),
        module.Request("c1", "p2", "p2:1", 1.0),
        module.Request("c1", "p1", "p1:2", 10.0),
    )
    decisions = (
        module.Decision("c1", 2.0, 1, (("p1", "a"), ("p2", "b"))),
        module.Decision("c1", 4.0, 1, (("p1", "a"),)),
        module.Decision("c1", 12.0, 1, (("p1", "a"), ("p2", "b"))),
    )
    return module.CellData("c1", requests, decisions)


def test_freeze_config_is_frozen() -> None:
    module = _load_module()
    config = module.load_freeze(FREEZE_PATH)
    assert config["status"] == "FROZEN_BEFORE_EXECUTION"
    assert config["primary_model"]["id"] == "M0_OBSERVED_PHASE3"


def test_observed_exposure_and_denominators() -> None:
    module = _load_module()
    result = module.analyze_observed([_cell(module)], 60.0)
    assert result["decision_count"] == 3
    assert result["candidate_count_distribution"] == {1: 1, 2: 2}
    assert result["multi_candidate_events"] == 2
    assert result["multi_candidate_rate_all_decisions"] == 2 / 3
    assert result["denominators"]["all_forced_release_decision_events"] == 3
    # Event at t=2: p1 has a later request; p2 does not. Program-level differential.
    assert result["candidate_differential_downstream_opportunity"]["numerator_events"] == 1


def test_no_differential_when_all_candidate_programs_have_later_requests() -> None:
    module = _load_module()
    cell = module.CellData(
        "c1",
        (
            module.Request("c1", "p1", "p1:1", 0.0),
            module.Request("c1", "p2", "p2:1", 1.0),
            module.Request("c1", "p1", "p1:2", 10.0),
            module.Request("c1", "p2", "p2:2", 11.0),
        ),
        (module.Decision("c1", 2.0, 1, (("p1", "a"), ("p2", "b"))),),
    )
    result = module.analyze_observed([cell], 60.0)
    assert result["candidate_differential_downstream_opportunity"]["numerator_events"] == 0


def test_data_sources_report_absence() -> None:
    module = _load_module()
    config = module.load_freeze(FREEZE_PATH)
    result = module.audit_data_sources(config, ROOT)
    assert result["w1c_raw_traces_status"] == "W1C_RAW_TRACES_NOT_PRESENT_IN_WORKSPACE"
    assert result["protected_entry_snapshot_status"] == "PROTECTED_ENTRY_SNAPSHOT_NOT_PRESENT"


def test_sensitivity_models_are_not_fabricated() -> None:
    module = _load_module()
    config = module.load_freeze(FREEZE_PATH)
    data = module.audit_data_sources(config, ROOT)
    models = module.models_report(config, data)
    statuses = {model["id"]: model["status"] for model in models}
    assert statuses["M0_OBSERVED_PHASE3"] == "EXECUTABLE"
    assert statuses["M1_RETENTION_X2"] == "NOT_EXECUTABLE_MISSING_PROTECTED_ENTRY_SNAPSHOT"
    assert statuses["M2_RETENTION_X4"] == "NOT_EXECUTABLE_MISSING_PROTECTED_ENTRY_SNAPSHOT"
    assert statuses["M3_RETENTION_X8"] == "NOT_EXECUTABLE_MISSING_PROTECTED_ENTRY_SNAPSHOT"


def test_freeze_rejects_nonfrozen() -> None:
    module = _load_module()
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "freeze.json"
        path.write_text(
            json.dumps({"status": "DRAFT", "primary_model": {"status": "EXECUTABLE"}}),
            encoding="utf-8",
        )
        try:
            module.load_freeze(path)
        except ValueError as error:
            assert "not frozen" in str(error)
        else:
            raise AssertionError("non-frozen config was accepted")
