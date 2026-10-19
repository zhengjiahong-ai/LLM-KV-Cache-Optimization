import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kvopt.workload import phase2g_a2_gate2_runner as runner

TOOLING_SHA = "a1" * 20
A2_SHA = "b2" * 20


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bound_files(tmp_path: Path) -> tuple[Path, Path]:
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    trace = campaign / "scenario.trace.json"
    config = campaign / "run-1.config.json"
    trace.write_text('{"trace": 1}\n', encoding="utf-8")
    config.write_text(
        json.dumps(
            {
                "trace": trace.name,
                "phase2g_stage": {
                    "scenario_id": "scenario-1",
                    "policy": "A2",
                    "repeat": 1,
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "phase2g.a2_gate2_materialization.v1",
        "tested_a2_implementation_git_sha": A2_SHA,
        "runs": [
            {
                "run_id": "run-1",
                "scenario_id": "scenario-1",
                "policy": "A2",
                "repeat": 1,
                "config": config.name,
                "config_sha256": _sha(config),
                "trace": trace.name,
                "trace_sha256": _sha(trace),
            }
        ],
        "scenarios": [
            {
                "scenario_id": "scenario-1",
                "trace_sha256": _sha(trace),
            }
        ],
    }
    manifest_path = campaign / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    authorization = {
        "schema_version": "phase2g.a2_gate2_authorization.v1",
        "formal_native_execution_authorized": True,
        "execution_authorized": True,
        "campaign_manifest_sha256": _sha(manifest_path),
        "tested_a2_implementation_git_sha": A2_SHA,
        "experiment_tooling_git_sha": TOOLING_SHA,
        "authorized_config_sha256": {"run-1": _sha(config)},
        "authorized_trace_sha256": {"scenario-1": _sha(trace)},
    }
    authorization_path = campaign / "authorization.json"
    authorization_path.write_text(json.dumps(authorization), encoding="utf-8")
    return manifest_path, authorization_path


def _clean_git(command: list[str], **_: object) -> SimpleNamespace:
    output = TOOLING_SHA + "\n" if command[1:] == ["rev-parse", "HEAD"] else ""
    return SimpleNamespace(stdout=output)


def test_authorize_campaign_loads_manifest_and_validates_all_bindings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path, authorization_path = _bound_files(tmp_path)
    monkeypatch.setattr(runner.subprocess, "run", _clean_git)

    manifest, authorization = runner.authorize_campaign(
        manifest_path,
        authorization_path,
    )

    assert manifest["runs"][0]["run_id"] == "run-1"
    assert authorization["experiment_tooling_git_sha"] == TOOLING_SHA


def test_binding_mismatch_refuses_before_any_native_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path, authorization_path = _bound_files(tmp_path)
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    authorization["campaign_manifest_sha256"] = "wrong"
    authorization_path.write_text(json.dumps(authorization), encoding="utf-8")
    started: list[str] = []
    monkeypatch.setattr(runner.subprocess, "run", _clean_git)
    monkeypatch.setattr(
        runner,
        "_run_phase2d_stage",
        lambda *args, **kwargs: started.append("started"),
    )

    with pytest.raises(ValueError, match="frozen manifest"):
        runner.run_campaign(
            manifest_path=manifest_path,
            authorization_path=authorization_path,
            output_root=tmp_path / "runs",
        )

    assert started == []


def test_single_run_revalidates_authorization_and_rejects_unknown_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path, authorization_path = _bound_files(tmp_path)
    monkeypatch.setattr(runner.subprocess, "run", _clean_git)
    started: list[str] = []
    monkeypatch.setattr(
        runner,
        "_run_phase2d_stage",
        lambda *args, **kwargs: started.append("started"),
    )

    with pytest.raises(ValueError, match="not uniquely bound"):
        runner.run_single_authorized(
            manifest_path=manifest_path,
            authorization_path=authorization_path,
            output_root=tmp_path / "runs",
            run_id="not-bound",
        )

    assert started == []


def test_isolated_run_uses_fresh_interpreter_and_exact_authorized_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path, authorization_path = _bound_files(tmp_path)
    output_root = tmp_path / "runs"
    output = output_root / "run-1"
    output.mkdir(parents=True)
    (output / "run.json").write_text(
        json.dumps({"execution_status": "success"}), encoding="utf-8"
    )
    commands: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        commands.append(command)
        assert kwargs == {"check": False}
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    assert runner._run_isolated(
        manifest_path=manifest_path,
        authorization_path=authorization_path,
        output_root=output_root,
        run_id="run-1",
    ) == output
    assert commands == [
        [
            runner.sys.executable,
            "-m",
            "kvopt.workload.phase2g_a2_gate2_runner",
            "--manifest",
            str(manifest_path.resolve()),
            "--authorization",
            str(authorization_path.resolve()),
            "--output-root",
            str(output_root.resolve()),
            "--run-id",
            "run-1",
        ]
    ]


def test_campaign_stops_after_isolated_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path, authorization_path = _bound_files(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    second = dict(manifest["runs"][0])
    second["run_id"] = "run-2"
    manifest["runs"].append(second)
    output_root = tmp_path / "runs"
    attempted: list[str] = []
    monkeypatch.setattr(
        runner,
        "authorize_campaign",
        lambda *_: (manifest, {}),
    )

    def fake_isolated(**kwargs: object) -> Path:
        run_id = str(kwargs["run_id"])
        attempted.append(run_id)
        output = output_root / run_id
        output.mkdir(parents=True)
        status = "failed" if run_id == "run-1" else "success"
        (output / "run.json").write_text(
            json.dumps({"execution_status": status}), encoding="utf-8"
        )
        return output

    monkeypatch.setattr(runner, "_run_isolated", fake_isolated)

    outputs = runner.run_campaign(
        manifest_path=manifest_path,
        authorization_path=authorization_path,
        output_root=output_root,
    )

    assert [path.name for path in outputs] == ["run-1"]
    assert attempted == ["run-1"]
