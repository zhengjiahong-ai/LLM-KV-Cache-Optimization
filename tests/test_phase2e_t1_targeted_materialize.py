import json
from pathlib import Path

from kvopt.workload.phase2e_t1_targeted_materialize import materialize_targeted_t1

FIXTURE = (
    Path(__file__).parents[1]
    / "configs"
    / "phase2"
    / "phase2e-t1-targeted-forced-release-v1.json"
)


def test_materializes_non_measured_continuum_forced_release_smoke(
    tmp_path: Path,
) -> None:
    path = materialize_targeted_t1(
        fixture_path=FIXTURE,
        output_dir=tmp_path / "campaign",
    )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    config = json.loads(
        (path.parent / manifest["run"]["config"]).read_text(encoding="utf-8")
    )
    trace = json.loads(
        (path.parent / manifest["run"]["trace"]).read_text(encoding="utf-8")
    )

    assert manifest["measured_campaign"] is False
    assert manifest["joint_freeze_complete"] is False
    assert config["policy"] == "continuum-baseline"
    assert config["cache"]["block_override"] == 33
    assert trace["pressure_stages"][0]["stop_on_forced_release"] is True
