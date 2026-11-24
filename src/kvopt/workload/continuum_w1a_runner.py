"""Run one frozen W1-A SWE-bench task with observation-only wrappers."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .continuum_w1a_acquisition import (
    AcquisitionRecorder,
    ObservedEnvironment,
    ObservedModel,
)
from .phase5_replay import canonical_sha256

CONFIG_SCHEMAS = {
    "continuum.w1a_acquisition_config.v1",
    "continuum.w1a_acquisition_config.v2",
    "continuum.w1c_acquisition_config.v1",
    "phase3.agent_acquisition_config.v1",
    "phase5.swe_historical_reacquisition_config.v1",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_sha(repository: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def load_acquisition_config(
    path: Path, *, repository: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("schema_version") not in CONFIG_SCHEMAS:
        raise ValueError("unsupported W1-A acquisition config")
    schema = config.get("schema_version")
    w1c = schema == "continuum.w1c_acquisition_config.v1"
    phase3 = schema == "phase3.agent_acquisition_config.v1"
    phase5_historical = schema == "phase5.swe_historical_reacquisition_config.v1"
    expected_scope = (
        "PHASE5_HISTORICAL_W1C_FRESH_REACQUISITION_NO_NATIVE_CAMPAIGN"
        if phase5_historical
        else (
            "PHASE3_FROZEN_COHORT_AGENT_ACQUISITION_NO_NATIVE_CAMPAIGN"
            if phase3
            else (
                "W1C_BOUNDED_PAIRED_STEP_LIMIT_FEASIBILITY_PILOT"
                if w1c
                else "W1A_BOUNDED_TRAJECTORY_ACQUISITION_NO_NATIVE_CAMPAIGN"
            )
        )
    )
    if config.get("scope") != expected_scope:
        raise ValueError("bounded acquisition scope mismatch")
    authorization = config.get(
        "execution_budget" if (w1c or phase3 or phase5_historical) else "acquisition"
    )
    if not isinstance(authorization, dict) or authorization.get(
        "formal_native_campaign_authorized"
    ) is not False:
        raise ValueError("acquisition config must keep Native campaign authorization false")
    if w1c and authorization.get("full_100_task_acquisition_authorized") is not False:
        raise ValueError("W1-C full acquisition must remain unauthorized")
    sample_path = repository / str(config["sample_manifest"])
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    sample_dataset = sample.get("source", sample.get("dataset", {}))
    if config["dataset"]["revision"] != sample_dataset["revision"]:
        raise ValueError("dataset revision does not match the W0 frozen sample")
    if phase5_historical:
        if authorization.get("agent_acquisition_authorized") is not True:
            raise ValueError("Phase 5 historical reacquisition is not authorized")
        if authorization.get("historical_w1c_reacquisition_authorized") is not True:
            raise ValueError("historical W1-C reacquisition authorization is absent")
        if sample.get("schema_version") != "phase5.swe_sampling_frame.v1":
            raise ValueError("Phase 5 SWE sampling-frame schema mismatch")
        if sample.get("status") != "FROZEN_ACQUISITION_FRAME_NOT_FORMAL_COHORT":
            raise ValueError("Phase 5 SWE sampling frame is not frozen")
        if _sha256(sample_path) != config.get("sampling_frame_file_sha256"):
            raise ValueError("Phase 5 SWE sampling-frame file SHA-256 mismatch")
        sample_payload = dict(sample)
        expected_frame_sha = sample_payload.pop("frame_sha256", None)
        if canonical_sha256(sample_payload) != expected_frame_sha:
            raise ValueError("Phase 5 SWE sampling-frame canonical SHA-256 mismatch")
        if config.get("sampling_frame_canonical_sha256") != expected_frame_sha:
            raise ValueError("Phase 5 config does not bind the frozen frame identity")
        authorization_path = repository / str(config.get("authorization_record"))
        if not authorization_path.is_file() or _sha256(authorization_path) != config.get(
            "authorization_record_sha256"
        ):
            raise ValueError("Phase 5 historical authorization binding mismatch")
        authorization_record = json.loads(authorization_path.read_text(encoding="utf-8"))
        authorization_payload = dict(authorization_record)
        authorization_sha = authorization_payload.pop("authorization_sha256", None)
        if canonical_sha256(authorization_payload) != authorization_sha:
            raise ValueError("Phase 5 historical authorization canonical hash mismatch")
        if authorization_record.get("execution_authorized") is not True:
            raise ValueError("Phase 5 historical authorization record is disabled")
        if config["author_runner"].get("effective_step_limit") != 100:
            raise ValueError("Phase 5 reacquisition requires the frozen 100-step limit")
    elif phase3:
        if authorization.get("agent_acquisition_authorized") is not True:
            raise ValueError("Phase 3 Agent Acquisition is not authorized")
        if sample.get("schema_version") != "phase3.cohort_candidate_plan.v1":
            raise ValueError("Phase 3 candidate-plan schema mismatch")
        if sample.get("status") != "PREREGISTERED_NOT_ACQUIRED":
            raise ValueError("Phase 3 candidate plan is not preregistered")
        if _sha256(sample_path) != config.get("candidate_plan_sha256"):
            raise ValueError("Phase 3 candidate-plan SHA-256 mismatch")
        if config["author_runner"].get("effective_step_limit") != 100:
            raise ValueError("Phase 3 acquisition requires the frozen 100-step limit")
    elif w1c:
        if sample.get("scope") != "W1C_SAMPLING_DESIGN_AND_BOUNDED_S50_S100_PILOT_ONLY":
            raise ValueError("W1-C sample scope mismatch")
        condition = config.get("condition")
        expected_limit = sample.get("pilot_conditions", {}).get(condition, {}).get("step_limit")
        if expected_limit != config["author_runner"].get("effective_step_limit"):
            raise ValueError("W1-C step-limit condition does not match the sample freeze")
        snapshot_path = repository / str(config["candidate_snapshot"])
        if not snapshot_path.is_file() or _sha256(snapshot_path) != config.get(
            "candidate_snapshot_sha256"
        ):
            raise ValueError("W1-C candidate snapshot binding mismatch")
    elif config["author_runner"]["commit"] != sample["trajectory_source"][
        "repository_commit"
    ]:
        raise ValueError("author runner revision does not match the W0 audit")
    return config, sample


def validate_instance_id(instance_id: str, sample: dict[str, Any]) -> None:
    candidates = sample.get("candidates")
    if isinstance(candidates, list):
        identities = [
            row.get("instance_id") for row in candidates if isinstance(row, dict)
        ]
    else:
        identities = sample.get("pilot_instance_ids", sample.get("instance_ids"))
    if not isinstance(identities, list) or instance_id not in identities:
        raise ValueError("instance_id is not in the frozen acquisition sample")


def _load_author_path(source_checkout: Path, expected_sha: str) -> Path:
    if _git_sha(source_checkout) != expected_sha:
        raise ValueError("Continuum author checkout SHA mismatch")
    package_root = source_checkout / "mini-swe-agent" / "src"
    if not package_root.is_dir():
        raise FileNotFoundError("bundled Mini-SWE-Agent package is missing")
    sys.path.insert(0, str(package_root))
    return package_root


def _tokenizer_observer(model_config: dict[str, Any]):
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        model_config["tokenizer_name"],
        revision=model_config["tokenizer_revision"],
        local_files_only=True,
    )

    def observe(messages):
        rendered = tokenizer.apply_chat_template(
            list(messages), tokenize=False, add_generation_prompt=True
        )
        token_ids = tokenizer.encode(rendered, add_special_tokens=False)
        return rendered, token_ids

    return observe


def run_one(
    *,
    repository: Path,
    source_checkout: Path,
    config_path: Path,
    instance_id: str,
    output_root: Path,
) -> Path:
    config, sample = load_acquisition_config(config_path, repository=repository)
    validate_instance_id(instance_id, sample)
    _load_author_path(source_checkout, config["author_runner"]["commit"])

    import yaml
    from datasets import load_dataset
    from minisweagent.agents.default import DefaultAgent
    from minisweagent.environments import get_environment
    from minisweagent.models import get_model
    from minisweagent.run.extra.swebench import get_swebench_docker_image_name
    from minisweagent.run.utils.save import save_traj

    run_dir = output_root.resolve() / instance_id
    if run_dir.exists():
        raise FileExistsError(f"W1-A output already exists: {run_dir}")
    run_dir.mkdir(parents=True)
    manifest_path = run_dir / "run.json"
    trajectory_path = run_dir / f"{instance_id}.traj.json"
    sidecar_path = run_dir / "acquisition-sidecar.json"
    started_monotonic = time.monotonic()
    manifest: dict[str, object] = {
        "schema_version": "continuum.w1a_acquisition_run.v1",
        "status": "running",
        "instance_id": instance_id,
        "config_path": str(config_path.resolve()),
        "config_sha256": _sha256(config_path),
        "repository_git_sha": _git_sha(repository),
        "author_repository_git_sha": _git_sha(source_checkout),
        "dataset": copy.deepcopy(config["dataset"]),
        "model": copy.deepcopy(config["model"]),
        "server_runtime": copy.deepcopy(config["server_runtime"]),
        "environment": copy.deepcopy(config["environment"]),
        "condition": config.get("condition", "W1A"),
        "effective_step_limit": config["author_runner"].get(
            "effective_step_limit", config["author_runner"].get("step_limit")
        ),
        "cost_limit": config["author_runner"].get("cost_limit"),
        "max_model_len": config["server_runtime"]["max_model_len"],
        "started_at_utc": datetime.now(UTC).isoformat(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    agent = None
    recorder = None
    exit_status = "NOT_STARTED"
    result = ""
    extra_info = None
    try:
        dataset = load_dataset(
            config["dataset"]["name"],
            config["dataset"]["config"],
            split=config["dataset"]["split"],
            revision=config["dataset"]["revision"],
        )
        matching = [row for row in dataset if row["instance_id"] == instance_id]
        if len(matching) != 1:
            raise ValueError("frozen instance was not uniquely found in the pinned dataset")
        instance = dict(matching[0])

        author_config_path = source_checkout / config["author_runner"]["agent_config"]
        agent_config = yaml.safe_load(author_config_path.read_text(encoding="utf-8"))
        effective_step_limit = int(
            config["author_runner"].get(
                "effective_step_limit", config["author_runner"].get("step_limit", 0)
            )
        )
        agent_config.setdefault("agent", {})["step_limit"] = effective_step_limit
        agent_config["agent"]["cost_limit"] = float(
            config["author_runner"].get(
                "cost_limit", agent_config["agent"].get("cost_limit", 0.0)
            )
        )
        model_config = copy.deepcopy(config["model"])
        model_config.pop("model_revision")
        model_config.pop("tokenizer_name")
        model_config.pop("tokenizer_revision")
        model_config.pop("paper_example_difference")
        model_config["step_limit"] = effective_step_limit
        model = get_model(config=model_config)
        environment_config = copy.deepcopy(agent_config.get("environment", {}))
        environment_config.update(
            {
                "environment_class": config["environment"]["environment_class"],
                "image": get_swebench_docker_image_name(instance),
                "timeout": config["environment"]["tool_timeout_seconds"],
            }
        )
        manifest["environment_image"] = environment_config["image"]
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        environment = get_environment(environment_config)
        recorder = AcquisitionRecorder(
            program_id=instance_id,
            provenance={
                "dataset": copy.deepcopy(config["dataset"]),
                "author_runner": copy.deepcopy(config["author_runner"]),
                "model": copy.deepcopy(config["model"]),
                "repository_git_sha": manifest["repository_git_sha"],
            },
            tokenize_messages=_tokenizer_observer(config["model"]),
        )
        observed_model = ObservedModel(model, recorder)
        observed_environment = ObservedEnvironment(environment, recorder)
        agent = DefaultAgent(
            observed_model, observed_environment, **agent_config.get("agent", {})
        )
        exit_status, result = agent.run(instance["problem_statement"])
        manifest["status"] = "completed"
        manifest["agent_exit_status"] = exit_status
        manifest["agent_outcome"] = (
            "SUBMITTED" if exit_status == "Submitted" else "INCOMPLETE"
        )
    except Exception as error:  # noqa: BLE001 - the failed attempt is evidence
        exit_status, result = type(error).__name__, str(error)
        extra_info = {"traceback": traceback.format_exc()}
        manifest["status"] = "failed"
        manifest["agent_exit_status"] = exit_status
        manifest["agent_outcome"] = "FAILED"
        manifest["failure_reason"] = f"{type(error).__name__}: {error}"
    finally:
        if agent is not None and recorder is not None:
            save_traj(
                agent,
                trajectory_path,
                exit_status=exit_status,
                result=result,
                extra_info=extra_info,
                instance_id=instance_id,
                print_path=False,
            )
            recorder.write(sidecar_path, trajectory_path=trajectory_path)
            manifest["trajectory_sha256"] = _sha256(trajectory_path)
            manifest["sidecar_sha256"] = _sha256(sidecar_path)
            manifest["model_call_count"] = len(recorder.model_calls)
            manifest["tool_call_count"] = len(recorder.tool_calls)
            manifest["tool_execution_demonstrated"] = bool(recorder.tool_calls)
        else:
            manifest["model_call_count"] = 0
            manifest["tool_call_count"] = 0
            manifest["tool_execution_demonstrated"] = False
        manifest["finished_at_utc"] = datetime.now(UTC).isoformat()
        manifest["wall_elapsed_seconds"] = time.monotonic() - started_monotonic
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"{manifest['status']}: {run_dir}")
    return run_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--source-checkout", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    run_one(
        repository=args.repository.resolve(),
        source_checkout=args.source_checkout.resolve(),
        config_path=args.config.resolve(),
        instance_id=args.instance_id,
        output_root=args.output_root,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
