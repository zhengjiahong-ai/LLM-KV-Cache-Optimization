from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import kvopt.profiling.continuum_bounded_report as report_module
import kvopt.workload.continuum_bounded_pipeline as pipeline_module


def _evaluated(binding: dict[str, object], *, mechanism: str) -> dict[str, object]:
    return {
        "run_id": binding["run_id"],
        "group_id": binding["group_id"],
        "pressure_regime": binding["pressure_regime"],
        "arm": binding["arm"],
        "status": "VALID",
        "mechanism_status": mechanism,
        "request_outcomes": {"request": {"N": 16}},
        "totals": {
            "aggregate_recomputed_tokens": 1,
            "aggregate_actual_prefill_tokens": 1,
            "aggregate_new_suffix_tokens": 0,
        },
        "selection_sequence": [],
        "physical_eviction_signature": [],
        "profile_cost_ordering_status": "NOT_APPLICABLE_COLD_START",
    }


def _manifest() -> dict[str, object]:
    runs: list[dict[str, object]] = []
    for group_index in range(1, 10):
        group_id = f"g{group_index:02d}-group"
        for regime in ("moderate", "deep"):
            for arm in ("A0", "A1", "A2"):
                runs.append(
                    {
                        "run_id": f"{group_id}-{regime}-{arm.lower()}-repeat-1",
                        "group_id": group_id,
                        "pressure_regime": regime,
                        "arm": arm,
                    }
                )
    return {"runs": runs}


def test_report_keeps_not_realized_run_without_invalidating_metrics(
    tmp_path: Path, monkeypatch,
) -> None:
    manifest = _manifest()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    runs_root = tmp_path / "runs"
    for row in manifest["runs"]:  # type: ignore[index]
        (runs_root / row["run_id"]).mkdir(parents=True)  # type: ignore[index]

    def fake_evaluate(_run_dir: Path, binding: dict[str, object]) -> dict[str, object]:
        mechanism = "NOT_REALIZED" if binding["run_id"] == manifest["runs"][0]["run_id"] else "REALIZED"  # type: ignore[index]
        return _evaluated(binding, mechanism=mechanism)

    monkeypatch.setattr(report_module, "evaluate_run", fake_evaluate)
    report = report_module.build_report(
        manifest_path=manifest_path,
        runs_root=runs_root,
    )

    assert report["gate"] == "PASS"
    assert report["mechanism_status_counts"] == {"NOT_REALIZED": 1, "REALIZED": 53}
    assert report["statistical_unit_count"] == 9


def test_integrated_fidelity_fails_when_mechanism_is_not_realized(
    tmp_path: Path, monkeypatch,
) -> None:
    rows = [
        {
            "run_id": f"formal-{arm.lower()}",
            "group_id": "g01-short-extreme",
            "pressure_regime": "moderate",
            "arm": arm,
            "config": f"{arm.lower()}.json",
        }
        for arm in ("A0", "A1", "A2")
    ]
    manifest_path = tmp_path / "campaign" / "manifest.json"
    manifest_path.parent.mkdir()
    manifest_path.write_text(json.dumps({"runs": rows}), encoding="utf-8")
    for row in rows:
        (manifest_path.parent / row["config"]).write_text("{}", encoding="utf-8")
    output_root = tmp_path / "preflight"

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        run_id = command[command.index("--run-id") + 1]
        run_dir = output_root / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "run.json").write_text("{}", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    def fake_evaluate(_run_dir: Path, binding: dict[str, object]) -> dict[str, object]:
        return _evaluated(
            binding,
            mechanism="NOT_REALIZED" if binding["arm"] == "A2" else "REALIZED",
        )

    monkeypatch.setattr(pipeline_module.subprocess, "run", fake_run)
    monkeypatch.setattr(pipeline_module, "evaluate_run", fake_evaluate)
    result = pipeline_module._run_fidelity_preflight(
        repository=tmp_path,
        manifest_path=manifest_path,
        output_root=output_root,
    )

    assert result["status"] == "FAIL"
    assert result["cross_arm_native_prompt_tokens_equal"] is True
