"""Materialize and validate token-exact W1-B Native replay inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA = "continuum.w1b_native_replay_manifest.v1"
SESSION_SCHEMA = "continuum.w1b_native_replay_session.v1"


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _token_digest(tokens: list[int]) -> str:
    payload = json.dumps(tokens, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _git_sha(repository: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _outcome(run: dict[str, Any], trajectory: dict[str, Any]) -> tuple[str, bool]:
    info = trajectory.get("info")
    if not isinstance(info, dict) or info.get("exit_status") != run.get(
        "agent_exit_status"
    ):
        raise ValueError("run and trajectory exit status mismatch")
    outcome = run.get("agent_outcome")
    if outcome == "SUBMITTED" and info.get("exit_status") == "Submitted":
        return "OBSERVED_COMPLETE", False
    if outcome == "INCOMPLETE" and info.get("exit_status") in {
        "LimitsExceeded",
        "ContextLengthExceeded",
    }:
        return "RIGHT_CENSORED_INCOMPLETE", True
    raise ValueError("unsupported or inconsistent W1-A outcome")


def materialize_replay(
    *,
    repository: Path,
    runs_root: Path,
    sample_manifest_path: Path,
    acquisition_config_path: Path,
    contract_path: Path,
    output_root: Path,
) -> tuple[dict[str, Any], Path]:
    sample = _load_object(sample_manifest_path)
    config = _load_object(acquisition_config_path)
    contract = _load_object(contract_path)
    expected = sample.get("instance_ids")
    if not isinstance(expected, list) or any(not isinstance(item, str) for item in expected):
        raise TypeError("sample instance_ids must be strings")
    if len(expected) != len(set(expected)):
        raise ValueError("sample contains duplicate instance IDs")
    if contract.get("formal_performance_campaign_authorized") is not False:
        raise ValueError("W1-B replay contract must keep formal campaign closed")
    if config.get("dataset", {}).get("revision") != sample.get("dataset", {}).get(
        "revision"
    ):
        raise ValueError("W1-A config and W0 sample dataset revisions differ")
    actual = sorted(path.parent.name for path in runs_root.glob("*/run.json"))
    if set(actual) != set(expected) or len(actual) != len(expected):
        raise ValueError("W1-B source cohort does not exactly match frozen W1-A sample")
    if output_root.exists():
        raise FileExistsError(f"W1-B replay output already exists: {output_root}")
    sessions_root = output_root / "sessions"
    sessions_root.mkdir(parents=True)
    sessions: list[dict[str, Any]] = []

    for instance_id in expected:
        run_dir = runs_root / instance_id
        run_path = run_dir / "run.json"
        trajectory_path = run_dir / f"{instance_id}.traj.json"
        sidecar_path = run_dir / "acquisition-sidecar.json"
        evidence_path = run_dir / "converted-v2" / "acquisition-evidence.json"
        validation_path = run_dir / "converted-v2" / "validation-report.json"
        for path in (run_path, trajectory_path, sidecar_path, evidence_path, validation_path):
            if not path.is_file():
                raise FileNotFoundError(f"missing frozen W1-A evidence: {path}")
        run = _load_object(run_path)
        trajectory = _load_object(trajectory_path)
        sidecar = _load_object(sidecar_path)
        evidence = _load_object(evidence_path)
        validation = _load_object(validation_path)
        if run.get("instance_id") != instance_id or sidecar.get("program_id") != instance_id:
            raise ValueError("W1-A source identity mismatch")
        if validation.get("verdict") != "CONDITIONAL_PASS":
            raise ValueError("W1-A source conversion is not conditionally valid")
        completion_status, right_censored = _outcome(run, trajectory)
        calls = sidecar.get("model_calls")
        evidence_rows = evidence.get("requests")
        if not isinstance(calls, list) or not isinstance(evidence_rows, list):
            raise TypeError("W1-A request evidence must be lists")
        if len(calls) != len(evidence_rows) or not calls:
            raise ValueError("W1-A model and converted request counts differ")
        requests: list[dict[str, Any]] = []
        previous_tokens: list[int] | None = None
        for index, (call, row) in enumerate(zip(calls, evidence_rows, strict=True), start=1):
            if not isinstance(call, dict) or not isinstance(row, dict):
                raise TypeError("W1-A request evidence rows must be objects")
            request_id = f"{instance_id}:turn:{index}"
            if call.get("request_id") != request_id or row.get("request_id") != request_id:
                raise ValueError("W1-A request identity sequence mismatch")
            prompt = call.get("rendered_prompt")
            tokens = call.get("submitted_token_ids")
            if not isinstance(prompt, str) or not isinstance(tokens, list) or any(
                isinstance(token, bool) or not isinstance(token, int) for token in tokens
            ):
                raise ValueError("W1-A rendered prompt or token IDs are incomplete")
            prefix_tokens = (
                None
                if previous_tokens is None
                else len(previous_tokens)
                if tokens[: len(previous_tokens)] == previous_tokens
                else 0
            )
            if previous_tokens is not None and prefix_tokens == 0:
                raise ValueError("W1-A session loses observed token-prefix growth")
            requests.append(
                {
                    "request_id": request_id,
                    "turn_index": index,
                    "rendered_prompt": prompt,
                    "rendered_prompt_sha256": hashlib.sha256(
                        prompt.encode("utf-8")
                    ).hexdigest(),
                    "token_ids": tokens,
                    "token_ids_sha256": _token_digest(tokens),
                    "token_count": len(tokens),
                    "observed_parent_prefix_tokens": prefix_tokens,
                    "source_model_submit_monotonic_seconds": call.get(
                        "model_submit_monotonic_seconds"
                    ),
                    "source_model_completion_monotonic_seconds": call.get(
                        "model_completion_monotonic_seconds"
                    ),
                    "source_tool_evidence": row.get("tool_evidence"),
                    "native_submission_status": "PENDING_NATIVE_FIDELITY_GATE",
                }
            )
            previous_tokens = tokens
        session = {
            "schema_version": SESSION_SCHEMA,
            "session_id": instance_id,
            "completion_status": completion_status,
            "right_censored": right_censored,
            "request_count": len(requests),
            "model": {
                "name": config["model"]["model_name"],
                "revision": config["model"]["model_revision"],
                "tokenizer_name": config["model"]["tokenizer_name"],
                "tokenizer_revision": config["model"]["tokenizer_revision"],
            },
            "source_bindings": {
                "run_sha256": _sha256(run_path),
                "trajectory_sha256": _sha256(trajectory_path),
                "sidecar_sha256": _sha256(sidecar_path),
                "acquisition_evidence_sha256": _sha256(evidence_path),
                "validation_sha256": _sha256(validation_path),
            },
            "requests": requests,
        }
        session_path = sessions_root / f"{instance_id}.json"
        session_path.write_text(
            json.dumps(session, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        sessions.append(
            {
                "session_id": instance_id,
                "path": str(session_path.relative_to(output_root)),
                "sha256": _sha256(session_path),
                "request_count": len(requests),
                "completion_status": completion_status,
                "right_censored": right_censored,
                "initial_token_count": requests[0]["token_count"],
                "maximum_token_count": max(row["token_count"] for row in requests),
            }
        )

    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "scope": contract["scope"],
        "repository_git_sha": _git_sha(repository),
        "source_bindings": {
            "sample_manifest_path": str(sample_manifest_path),
            "sample_manifest_sha256": _sha256(sample_manifest_path),
            "acquisition_config_path": str(acquisition_config_path),
            "acquisition_config_sha256": _sha256(acquisition_config_path),
            "contract_path": str(contract_path),
            "contract_sha256": _sha256(contract_path),
        },
        "model": {
            "name": config["model"]["model_name"],
            "revision": config["model"]["model_revision"],
            "tokenizer_name": config["model"]["tokenizer_name"],
            "tokenizer_revision": config["model"]["tokenizer_revision"],
        },
        "session_count": len(sessions),
        "request_count": sum(row["request_count"] for row in sessions),
        "sessions": sessions,
        "replay_semantics": contract["replay_semantics"],
        "native_input_equivalence": "PENDING_NATIVE_FIDELITY_GATE",
        "native_comparability_smoke_executed": False,
        "formal_performance_campaign_authorized": False,
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest, manifest_path


def validate_replay(manifest_path: Path) -> dict[str, Any]:
    manifest = _load_object(manifest_path)
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise ValueError("unsupported W1-B replay manifest schema")
    if manifest.get("formal_performance_campaign_authorized") is not False:
        raise ValueError("W1-B replay cannot authorize a formal campaign")
    sessions = manifest.get("sessions")
    if not isinstance(sessions, list) or len(sessions) != manifest.get("session_count"):
        raise ValueError("W1-B replay session count mismatch")
    root = manifest_path.parent
    identities: set[str] = set()
    request_count = 0
    for binding in sessions:
        if not isinstance(binding, dict):
            raise TypeError("W1-B session binding must be an object")
        session_id = binding.get("session_id")
        if not isinstance(session_id, str) or session_id in identities:
            raise ValueError("W1-B replay session identity is invalid or duplicated")
        identities.add(session_id)
        session_path = root / str(binding.get("path"))
        if _sha256(session_path) != binding.get("sha256"):
            raise ValueError("W1-B replay session SHA-256 mismatch")
        session = _load_object(session_path)
        if session.get("schema_version") != SESSION_SCHEMA or session.get(
            "session_id"
        ) != session_id:
            raise ValueError("W1-B replay session schema or identity mismatch")
        requests = session.get("requests")
        if not isinstance(requests, list) or len(requests) != binding.get("request_count"):
            raise ValueError("W1-B replay request count mismatch")
        previous: list[int] | None = None
        for index, request in enumerate(requests, start=1):
            if not isinstance(request, dict):
                raise TypeError("W1-B replay request must be an object")
            tokens = request.get("token_ids")
            prompt = request.get("rendered_prompt")
            if not isinstance(tokens, list) or not isinstance(prompt, str):
                raise TypeError("W1-B replay request content is incomplete")
            if request.get("request_id") != f"{session_id}:turn:{index}":
                raise ValueError("W1-B replay request identity sequence mismatch")
            if request.get("token_ids_sha256") != _token_digest(tokens):
                raise ValueError("W1-B replay token digest mismatch")
            if request.get("rendered_prompt_sha256") != hashlib.sha256(
                prompt.encode("utf-8")
            ).hexdigest():
                raise ValueError("W1-B replay prompt digest mismatch")
            if previous is not None and tokens[: len(previous)] != previous:
                raise ValueError("W1-B replay token-prefix growth mismatch")
            previous = tokens
        request_count += len(requests)
    if request_count != manifest.get("request_count"):
        raise ValueError("W1-B replay aggregate request count mismatch")
    return {
        "schema_version": "continuum.w1b_native_replay_validation.v1",
        "manifest_sha256": _sha256(manifest_path),
        "session_count": len(sessions),
        "request_count": request_count,
        "checks": {
            "session_hashes_valid": True,
            "request_identity_complete": True,
            "token_and_prompt_digests_valid": True,
            "within_session_token_prefix_growth_valid": True,
            "right_censoring_explicit": True,
            "native_input_equivalence_pending": True,
        },
        "verdict": "PASS_MATERIALIZATION_NATIVE_FIDELITY_PENDING",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    materialize = subparsers.add_parser("materialize")
    materialize.add_argument("--repository", type=Path, default=Path.cwd())
    materialize.add_argument("--runs-root", type=Path, required=True)
    materialize.add_argument("--sample-manifest", type=Path, required=True)
    materialize.add_argument("--acquisition-config", type=Path, required=True)
    materialize.add_argument("--contract", type=Path, required=True)
    materialize.add_argument("--output-root", type=Path, required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--manifest", type=Path, required=True)
    validate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "materialize":
        manifest, path = materialize_replay(
            repository=args.repository.resolve(),
            runs_root=args.runs_root,
            sample_manifest_path=args.sample_manifest,
            acquisition_config_path=args.acquisition_config,
            contract_path=args.contract,
            output_root=args.output_root,
        )
        print(
            f"wrote W1-B replay: {manifest['session_count']} sessions, "
            f"{manifest['request_count']} requests -> {path}"
        )
        return 0
    report = validate_replay(args.manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"W1-B replay validation: {report['verdict']} -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
