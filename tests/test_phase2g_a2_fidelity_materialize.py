import json
from pathlib import Path

import pytest

from kvopt.workload.phase2g_a2_fidelity_materialize import materialize_fidelity

FIXTURE = (
    Path(__file__).parents[1]
    / "configs"
    / "phase2"
    / "phase2g-a2-native-evidence-fidelity-v1.json"
)


def test_materializes_six_nonformal_lifecycle_cases(tmp_path: Path) -> None:
    output = tmp_path / "campaign"

    manifest_path = materialize_fidelity(fixture_path=FIXTURE, output_dir=output)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["formal"] is False
    assert manifest["formal_campaign_execution_authorized"] is False
    assert manifest["planned_run_count"] == 6
    assert set(manifest["case_kinds"]) == {
        "COMPLETE_CHAIN",
        "PARTIAL_EVICTION",
        "SHARED_CONTENT",
        "PROGRAM_COMPLETION",
        "SLOT_REUSE",
        "INCOMPLETE_EVIDENCE",
    }
    for row in manifest["runs"]:
        config = json.loads((output / row["config"]).read_text(encoding="utf-8"))
        assert config["campaign_kind"] == "phase2g_a2_native_evidence_fidelity"
        assert config["backend_options"]["phase2g_block_policy"] == "A2"
        assert config["phase2g_fidelity_stage"]["formal"] is False


def test_partial_and_slot_reuse_cases_freeze_native_interventions(
    tmp_path: Path,
) -> None:
    output = tmp_path / "campaign"
    manifest_path = materialize_fidelity(fixture_path=FIXTURE, output_dir=output)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    configs = {
        row["case_kind"]: json.loads(
            (output / row["config"]).read_text(encoding="utf-8")
        )
        for row in manifest["runs"]
    }

    assert configs["PARTIAL_EVICTION"]["backend_options"][
        "h2_native_prefix_interventions"
    ] == {"fidelity-a:1": {"position": "trailing", "count": 2}}
    assert configs["SLOT_REUSE"]["backend_options"][
        "h2_native_prefix_interventions"
    ] == {"fidelity-a:1": {"position": "leading", "count": 8}}
    assert configs["INCOMPLETE_EVIDENCE"]["backend_options"][
        "phase2g_a2_identity_mode"
    ] == "missing"


def test_rejects_formal_scope(tmp_path: Path) -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    fixture["boundaries"]["formal_campaign"] = True
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")

    with pytest.raises(ValueError, match="must remain non-formal"):
        materialize_fidelity(fixture_path=path, output_dir=tmp_path / "campaign")
