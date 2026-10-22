"""Run one frozen W1-A SWE-bench task with observation-only wrappers."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any

from .continuum_w1a_acquisition import (
    AcquisitionRecorder,
    ObservedEnvironment,
    ObservedModel,
)

CONFIG_SCHEMAS = {
    "continuum.w1a_acquisition_config.v1",
    "continuum.w1a_acquisition_config.v2",
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
    if config.get("scope") != "W1A_BOUNDED_TRAJECTORY_ACQUISITION_NO_NATIVE_CAMPAIGN":
        raise ValueError("W1-A acquisition scope mismatch")
    acquisition = config.get("acquisition")
    if not isinstance(acquisition, dict) or acquisition.get("formal_native_campaign_authorized") is not False:
        raise ValueError("W1-A config must keep Native campaign authorization false")
    sample_path = repository / str(config["sample_manifest"])
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    if config["dataset"]["revision"] != sample["dataset"]["revision"]:
        raise ValueError("dataset revision does not match the W0 frozen sample")
    if config["author_runner"]["commit"] != sample["trajectory_source"]["repository_commit"]:
        raise ValueError("author runner revision does not match the W0 audit")
    return config, sample


def validate_instance_id(instance_id: str, sample: dict[str, Any]) -> None:
    identities = sample.get("instance_ids")
    if not isinstance(identities, list) or instance_id not in identities:
        raise ValueError("instance_id is not in the frozen W1-A sample")


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
        model_config = copy.deepcopy(config["model"])
        model_config.pop("model_revision")
        model_config.pop("tokenizer_name")
        model_config.pop("tokenizer_revision")
        model_config.pop("paper_example_difference")
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
