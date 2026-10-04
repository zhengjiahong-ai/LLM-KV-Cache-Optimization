from test_phase2a_m6_pipeline import _load_current_schema_smoke_run

from kvopt.profiling.pipeline import build_derived_dataset_bundle


def test_method_support_pack_preserves_constraints_and_traceability(
    tmp_path,
) -> None:
    bundle = build_derived_dataset_bundle(
        (_load_current_schema_smoke_run(tmp_path),)
    )
    pack = bundle.method_support_pack

    assert pack.schema_version == "phase2a.method-support.v2"
    assert pack.gate_outcome == "INSUFFICIENT-EVENTS"
    assert "normalized_regret" in pack.constraints.future_only_forbidden_online
    assert "decision_native_lru_position" in pack.constraints.safe_online_features
    assert "horizon_sensitivity.jsonl" in pack.source_tables
    assert "decisions.jsonl" in pack.source_tables
    assert pack.constraints.unavailable_capabilities
