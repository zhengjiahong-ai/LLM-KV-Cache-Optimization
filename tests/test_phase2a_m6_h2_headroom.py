import json
from pathlib import Path

from kvopt.workload.phase2_h2_headroom import materialize_formal_m4


def test_formal_m4_materializes_frozen_grid_and_repeats(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    campaign_path = materialize_formal_m4(
        root / "configs/phase2/h2-measurement-authorization.json",
        tmp_path / "formal-m4",
    )

    campaign = json.loads(campaign_path.read_text())

    assert campaign["planned_run_count"] == 264
    assert campaign["formal_measurement"]
    assert not campaign["formal_verdict_authorized"]
    assert not campaign["b1_authorized"]
    assert len(campaign["probes"]) == 24
    assert {
        (probe["prefix_tokens"], probe["evicted_blocks"])
        for probe in campaign["probes"]
    } == {
        (prefix, evicted)
        for prefix in (512, 2048, 8192, 24576)
        for evicted in (1, 4, 16)
    }
    for probe in campaign["probes"]:
        assert [run["role"] for run in probe["runs"]] == [
            "warmup", "warmup", *("measured" for _ in range(9))
        ]
        assert {run["repeat_index"] for run in probe["runs"] if run["role"] == "measured"} == set(range(1, 10))
        config = json.loads((campaign_path.parent / probe["config"]).read_text())
        if probe["arm"] == "entry":
            assert len(config["backend_options"]["h2_m4_prefill_curve_sha256"]) == 64
