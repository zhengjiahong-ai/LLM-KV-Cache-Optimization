import json
from pathlib import Path

from kvopt.workload.phase2_h2_headroom_validation import (
    materialize_h2_headroom_validation,
)
from scripts.spikes.phase2_minimal_observability_metal import (
    _H2M4MeasuredPrefillProvider,
)


def test_h2_m4_measured_prefill_provider_interpolates_without_extrapolation() -> None:
    provider = _H2M4MeasuredPrefillProvider((512, 2048), (0.05, 0.2))

    exact, exact_provenance = provider.estimate(2048)
    interpolated, _ = provider.estimate(1024)

    assert exact == 0.2
    assert interpolated == 0.1
    assert exact_provenance.reason == (
        "formal H2 M1 isolated native-prefill median curve"
    )


def test_headroom_validation_is_small_non_formal_and_paired(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    campaign_path = materialize_h2_headroom_validation(
        root / "configs/phase2/h2-measurement-authorization.json",
        tmp_path / "campaign",
    )

    campaign = json.loads(campaign_path.read_text())

    assert campaign["planned_run_count"] == 6
    assert not campaign["formal_measurement"]
    assert not campaign["formal_verdict"]
    assert not campaign["b1_authorized"]
    assert {probe["arm"] for probe in campaign["probes"]} == {"entry", "block"}
    assert {
        (probe["prefix_tokens"], probe["evicted_blocks"])
        for probe in campaign["probes"]
    } == {(512, 1), (512, 4), (512, 16)}
    for probe in campaign["probes"]:
        config = json.loads((campaign_path.parent / probe["config"]).read_text())
        assert config["h2_measurement"]["measurement"] == "M4"
        assert config["h2_measurement"]["validation_only"]
        if probe["arm"] == "entry":
            assert config["pressure"]["initial_shortage_blocks"] == probe["evicted_blocks"]
            assert config["pressure"]["required_blocks"] == 32
            assert config["cache"]["block_override"] == (
                probe["prefix_tokens"] // 16 + 32 + 1 - probe["evicted_blocks"]
            )
            assert config["backend_options"]["h2_native_prefix_interventions"] == {}
            assert not config["backend_options"]["h2_native_mechanism_only"]
        else:
            intervention = config["backend_options"]["h2_native_prefix_interventions"]
            assert next(iter(intervention.values())) == {
                "position": "trailing",
                "count": probe["evicted_blocks"],
            }
