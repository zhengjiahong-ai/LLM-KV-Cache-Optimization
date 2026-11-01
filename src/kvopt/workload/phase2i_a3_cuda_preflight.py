"""Materialize and evaluate the authorized Phase 2I A3 CUDA preflight."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import platform
import subprocess
import tarfile
import time
from collections.abc import Mapping
from pathlib import Path

from .phase2_runner import run_phase2
from .phase2i_a3_preflight import evaluate_a3_native_preflight

MODEL_REVISION = "d18ecad881a290f0c792f1c2b5dbee1820d4a424"
RUN_ID = "phase2i-a3-target-cuda-native-replacement-preflight-02"
FIRST_PREFLIGHT_RUN_ID = "phase2i-a3-target-cuda-native-preflight"
FIRST_PREFLIGHT_FREEZE_SCHEMA = "phase2i.a3_target_cuda_preflight_freeze.v1"
AUTHORIZATION_SCHEMA = "phase2i.a3_replacement_execution_authorization.v1"
AUTHORIZATION_ALGORITHM = "SSH-ED25519"
EXPECTED_ENVIRONMENT = {
    "gpu_name": "NVIDIA GeForce RTX 4090 D",
    "vllm": "0.27.1",
    "torch": "2.13.0+cu130",
    "torch_cuda": "13.0",
}
PRESSURE_BOUNDARIES = frozenset(
    {
        "pressure:after-round-40",
        "pressure:after-round-50",
        "pressure:after-round-55",
    }
)
_CAPABILITY_SENTINEL = object()


class _InheritedExecutionCapability:
    __slots__ = ("nonce", "parent_pid", "run_id")

    def __init__(self, sentinel: object, *, parent_pid: int, run_id: str, nonce: str):
        if sentinel is not _CAPABILITY_SENTINEL:
            raise RuntimeError("bounded execution capability cannot be constructed directly")
        self.parent_pid = parent_pid
        self.run_id = run_id
        self.nonce = nonce


def read_bounded_parent_capability(descriptor: int) -> _InheritedExecutionCapability:
    """Consume a capability delivered only through an inherited anonymous pipe."""
    if descriptor < 3:
        raise RuntimeError("bounded execution capability descriptor is invalid")
    with os.fdopen(descriptor, "rb", closefd=True) as stream:
        raw = stream.read(4096)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeError("bounded execution capability is invalid") from error
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != "phase2i.bounded_parent_capability.v1"
        or value.get("run_id") != RUN_ID
        or type(value.get("parent_pid")) is not int
        or value.get("parent_pid") != os.getppid()
        or not isinstance(value.get("nonce"), str)
        or len(value["nonce"]) < 32
    ):
        raise RuntimeError("bounded execution capability parent binding failed")
    command_path = Path(f"/proc/{value['parent_pid']}/cmdline")
    try:
        parent_command = command_path.read_bytes().split(b"\0")
    except OSError as error:
        raise RuntimeError("bounded execution parent command is not observable") from error
    if (
        b"scripts.spikes.run_phase2i_a3_cuda_preflight" not in parent_command
        or b"run" not in parent_command
        or b"_run-once" in parent_command
    ):
        raise RuntimeError("bounded execution capability did not originate from run parent")
    return _InheritedExecutionCapability(
        _CAPABILITY_SENTINEL,
        parent_pid=value["parent_pid"],
        run_id=value["run_id"],
        nonce=value["nonce"],
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _archive_json_members(archive_path: Path) -> dict[str, tuple[bytes, dict[str, object]]]:
    members: dict[str, tuple[bytes, dict[str, object]]] = {}
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            for member in archive.getmembers():
                if not member.isfile() or not member.name.endswith(".json"):
                    continue
                stream = archive.extractfile(member)
                if stream is None:
                    continue
                raw = stream.read()
                value = json.loads(raw)
                if isinstance(value, dict):
                    members[member.name] = (raw, value)
    except (tarfile.TarError, json.JSONDecodeError) as error:
        raise ValueError("predecessor archive is not valid Phase 2I evidence") from error
    return members


def _load_predecessor_evidence(
    archive_path: Path,
) -> tuple[dict[str, object], dict[str, str], dict[str, object], dict[str, object]]:
    """Read the immutable run-01 freeze, report, and Native run manifest."""
    members = _archive_json_members(archive_path)
    candidates: list[tuple[str, bytes, dict[str, object]]] = []
    for name, (raw, value) in members.items():
        if (
            name.endswith("freeze-record.json")
            and value.get("schema_version") == FIRST_PREFLIGHT_FREEZE_SCHEMA
            and value.get("run_id") == FIRST_PREFLIGHT_RUN_ID
        ):
            candidates.append((name, raw, value))
    if not candidates:
        raise ValueError("predecessor archive lacks the original authoritative freeze record")
    canonical = {_canonical_sha(value) for _name, _raw, value in candidates}
    if len(canonical) != 1:
        raise ValueError("predecessor archive contains conflicting freeze records")
    freeze = candidates[0][2]
    member_hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw, _ in candidates}
    reports = [
        value
        for name, (_raw, value) in members.items()
        if name.endswith(("native-preflight-report.json", "offline-gate-diagnostic.json"))
        and value.get("status") == "FAIL_CLOSED"
        and value.get("run_id", FIRST_PREFLIGHT_RUN_ID) == FIRST_PREFLIGHT_RUN_ID
    ]
    run_manifests = [
        value
        for name, (_raw, value) in members.items()
        if name.endswith(f"/{FIRST_PREFLIGHT_RUN_ID}/run.json")
        and value.get("run_id") == FIRST_PREFLIGHT_RUN_ID
    ]
    if len(reports) != 1 or len(run_manifests) != 1:
        raise ValueError(
            "predecessor archive requires one failed Native report and one run manifest"
        )
    report, run_manifest = reports[0], run_manifests[0]
    if report.get("git_sha", freeze.get("git_sha")) != freeze.get("git_sha"):
        raise ValueError("predecessor freeze and report Git SHA do not cohere")
    if report.get("freeze_record_sha256", _canonical_sha(freeze)) != _canonical_sha(
        freeze
    ):
        raise ValueError("predecessor freeze and report Freeze SHA do not cohere")
    if report.get("run_status", run_manifest.get("status")) != run_manifest.get(
        "status"
    ):
        raise ValueError("predecessor freeze, report, and run manifest do not cohere")
    return freeze, member_hashes, report, run_manifest


def _validate_predecessor_bindings(
    freeze: Mapping[str, object],
    *,
    source_config: Mapping[str, object],
    source_config_path: Path,
    source_trace_path: Path,
    profile_path: Path,
) -> None:
    source = freeze.get("source")
    if not isinstance(source, Mapping):
        raise TypeError("predecessor freeze source bindings are missing")
    backend = source_config.get("backend_options")
    controlled = source_config.get("controlled_sparse_replay")
    if not isinstance(backend, Mapping) or not isinstance(controlled, Mapping):
        raise TypeError("replacement source bindings are incomplete")
    expected = {
        "config_sha256": _sha(source_config_path),
        "trace_sha256": _sha(source_trace_path),
        "profile_sha256": _sha(profile_path),
        "explicit_token_ids_sha256": _canonical_sha(
            backend["replay_token_ids_by_request"]
        ),
        "pressure_token_ids_sha256": _canonical_sha(
            backend["pressure_token_ids_by_stage"]
        ),
        "logical_sequence_sha256": controlled["logical_sequence_sha256"],
    }
    for field, value in expected.items():
        if source.get(field) != value:
            raise ValueError(f"replacement input drifted from predecessor: {field}")


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", *arguments),
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _validate_frozen_source(config: dict[str, object], trace: dict[str, object]) -> None:
    backend = config.get("backend_options")
    if not isinstance(backend, dict):
        raise TypeError("source backend_options are missing")
    expected = {
        "campaign_kind": "phase2h_history_rich_native_smoke",
        "runtime_mode": "vllm-cuda-observability",
        "policy": "continuum-a1-entry-native-lru",
    }
    for field, value in expected.items():
        if config.get(field) != value:
            raise ValueError(f"source {field} does not match frozen HR02/A1 input")
    if config.get("model") != {
        "name": "Qwen/Qwen2.5-Coder-1.5B-Instruct",
        "revision": MODEL_REVISION,
    } or config.get("tokenizer") != {
        "name": "Qwen/Qwen2.5-Coder-1.5B-Instruct",
        "revision": MODEL_REVISION,
    }:
        raise ValueError("source model/tokenizer identity is not frozen")
    if config.get("cache") != {"block_override": 2048, "block_size": 16}:
        raise ValueError("source cache geometry is not the frozen 2048-block pool")
    if config.get("pressure") != {
        "initial_shortage_blocks": 128,
        "required_blocks": 379,
        "safety_ceiling": 1,
    }:
        raise ValueError("source HR02 pressure geometry drifted")
    if backend.get("phase2g_release_policy") != "A1" or backend.get(
        "phase2g_block_policy"
    ) != "A0":
        raise ValueError("source must be the frozen HR02/A1 entry arm")
    stages = backend.get("controlled_pressure_stages_by_boundary")
    if not isinstance(stages, dict) or set(stages) != PRESSURE_BOUNDARIES:
        raise ValueError("source pressure barriers drifted")
    requests = trace.get("requests")
    if not isinstance(requests, list) or len(requests) != 180:
        raise ValueError("source trace must contain the frozen 180 requests")
    replay = backend.get("replay_token_ids_by_request")
    submissions = backend.get("expected_native_submission_sha256_by_request")
    if not isinstance(replay, dict) or not isinstance(submissions, dict):
        raise TypeError("source explicit-token bindings are missing")
    if set(replay) != set(submissions) or len(replay) != 180:
        raise ValueError("source explicit-token request membership drifted")
    for request_id, token_ids in replay.items():
        if _canonical_sha(token_ids) != submissions[request_id]:
            raise ValueError(f"explicit-token binding mismatch: {request_id}")


def materialize_preflight(
    *,
    source_config_path: Path,
    source_trace_path: Path,
    profile_path: Path,
    predecessor_archive_path: Path,
    m1_public_key_path: Path,
    output_dir: Path,
    repository: Path,
) -> dict[str, object]:
    """Derive one A3 run while preserving the frozen HR02 execution inputs."""
    if output_dir.exists():
        raise FileExistsError(output_dir)
    source_config = json.loads(source_config_path.read_text(encoding="utf-8"))
    source_trace = json.loads(source_trace_path.read_text(encoding="utf-8"))
    if not isinstance(source_config, dict) or not isinstance(source_trace, dict):
        raise TypeError("source config and trace must be JSON objects")
    _validate_frozen_source(source_config, source_trace)
    if not profile_path.is_file():
        raise FileNotFoundError(profile_path)
    if not predecessor_archive_path.is_file():
        raise FileNotFoundError(predecessor_archive_path)
    if not m1_public_key_path.is_file():
        raise FileNotFoundError(m1_public_key_path)
    public_key_pem = m1_public_key_path.read_text(encoding="utf-8")
    if not public_key_pem.strip().startswith("ssh-ed25519 "):
        raise ValueError("M1 Ed25519 public key is not an OpenSSH public key")
    predecessor_freeze, predecessor_freeze_members, predecessor_report, predecessor_run = _load_predecessor_evidence(
        predecessor_archive_path
    )
    _validate_predecessor_bindings(
        predecessor_freeze,
        source_config=source_config,
        source_config_path=source_config_path,
        source_trace_path=source_trace_path,
        profile_path=profile_path,
    )

    output_dir.mkdir(parents=True)
    trace_path = output_dir / "hr02-short-gap-long-context.trace.json"
    trace_path.write_bytes(source_trace_path.read_bytes())
    copied_profile_path = output_dir / "prefill-profile.json"
    copied_profile_path.write_bytes(profile_path.read_bytes())
    config = copy.deepcopy(source_config)
    config["campaign_kind"] = "phase2i_a3_native_integration"
    config["backend_revision"] = "phase2i-a3-target-cuda-native-preflight-v1"
    config["policy"] = "continuum-a3-entry-native-lru"
    config["trace"] = trace_path.name
    backend = config["backend_options"]
    assert isinstance(backend, dict)
    backend["phase2g_release_policy"] = "A3"
    backend["prefill_profile_path"] = str(copied_profile_path.resolve())
    config_path = output_dir / f"{RUN_ID}.config.json"
    _write(config_path, config)

    git_sha = _git(repository, "rev-parse", "HEAD")
    if _git(repository, "status", "--porcelain"):
        raise ValueError("execution freeze requires a clean Git worktree")
    manifest = {
        "schema_version": "phase2i.a3_target_cuda_replacement_preflight_freeze.v2",
        "execution_authorized": False,
        "authorization_scope": (
            "ONE_REPLACEMENT_TARGET_CUDA_NATIVE_PREFLIGHT_NOT_EFFECT_CAMPAIGN"
        ),
        "run_id": RUN_ID,
        "git_sha": git_sha,
        "m1_authorization_trust": {
            "algorithm": AUTHORIZATION_ALGORITHM,
            "public_key_pem": public_key_pem,
            "public_key_sha256": hashlib.sha256(public_key_pem.encode()).hexdigest(),
        },
        "predecessor": {
            "execution_id": "PHASE2I_A3_TARGET_CUDA_PREFLIGHT_01",
            "status": "FAIL_CLOSED",
            "archive_path": str(predecessor_archive_path.resolve()),
            "archive_sha256": _sha(predecessor_archive_path),
            "immutable": True,
            "internal_freeze_schema": predecessor_freeze["schema_version"],
            "internal_freeze_run_id": predecessor_freeze["run_id"],
            "internal_freeze_canonical_sha256": _canonical_sha(predecessor_freeze),
            "internal_freeze_member_sha256": predecessor_freeze_members,
            "native_report_canonical_sha256": _canonical_sha(predecessor_report),
            "run_manifest_canonical_sha256": _canonical_sha(predecessor_run),
        },
        "source": {
            "config_sha256": _sha(source_config_path),
            "trace_sha256": _sha(source_trace_path),
            "profile_sha256": _sha(profile_path),
            "explicit_token_ids_sha256": _canonical_sha(
                backend["replay_token_ids_by_request"]
            ),
            "pressure_token_ids_sha256": _canonical_sha(
                backend["pressure_token_ids_by_stage"]
            ),
            "logical_sequence_sha256": config["controlled_sparse_replay"][
                "logical_sequence_sha256"
            ],
        },
        "derived": {
            "config": config_path.name,
            "config_sha256": _sha(config_path),
            "trace": trace_path.name,
            "trace_sha256": _sha(trace_path),
            "profile_path": str(copied_profile_path.resolve()),
            "profile_sha256": _sha(copied_profile_path),
            "explicit_token_ids_sha256": _canonical_sha(
                backend["replay_token_ids_by_request"]
            ),
            "pressure_token_ids_sha256": _canonical_sha(
                backend["pressure_token_ids_by_stage"]
            ),
            "logical_sequence_sha256": config["controlled_sparse_replay"][
                "logical_sequence_sha256"
            ],
        },
        "frozen": {
            "model_revision": MODEL_REVISION,
            "cache_blocks": 2048,
            "request_count": 180,
            "pressure_boundaries": sorted(PRESSURE_BOUNDARIES),
            "release_policy": "A3",
            "block_policy": "A0",
        },
    }
    freeze_path = output_dir / "freeze-record.json"
    _write(freeze_path, manifest)
    _write(
        output_dir / "m1-authorization-request.json",
        {
            "schema_version": "phase2i.a3_execution_authorization_request.v1",
            "execution_authorized": False,
            "run_id": RUN_ID,
            "git_sha": git_sha,
            "freeze_record_sha256": _sha(freeze_path),
            "predecessor_archive_sha256": manifest["predecessor"]["archive_sha256"],
            "maximum_execution_count": 1,
            "timeout_seconds": 1800,
            "termination_grace_seconds": 60,
            "signature_algorithm": AUTHORIZATION_ALGORITHM,
            "m1_public_key_sha256": manifest["m1_authorization_trust"]["public_key_sha256"],
        },
    )
    return manifest


def _verify_freeze(input_dir: Path, repository: Path) -> tuple[dict[str, object], Path]:
    manifest_path = input_dir / "freeze-record.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != (
        "phase2i.a3_target_cuda_replacement_preflight_freeze.v2"
    ):
        raise ValueError("unsupported Phase 2I preflight freeze record")
    if manifest.get("execution_authorized") is not False:
        raise ValueError("replacement freeze candidate must not self-authorize execution")
    if _git(repository, "rev-parse", "HEAD") != manifest.get("git_sha"):
        raise ValueError("execution Git SHA does not match freeze record")
    if _git(repository, "status", "--porcelain"):
        raise ValueError("execution requires a clean Git worktree")
    derived = manifest.get("derived")
    if not isinstance(derived, dict):
        raise TypeError("freeze record derived bindings are missing")
    predecessor = manifest.get("predecessor")
    if not isinstance(predecessor, dict):
        raise TypeError("replacement preflight predecessor binding is missing")
    predecessor_path = Path(str(predecessor.get("archive_path")))
    if (
        predecessor.get("status") != "FAIL_CLOSED"
        or predecessor.get("immutable") is not True
        or not predecessor_path.is_file()
        or _sha(predecessor_path) != predecessor.get("archive_sha256")
    ):
        raise ValueError("replacement preflight predecessor archive binding mismatch")
    predecessor_freeze, predecessor_members, predecessor_report, predecessor_run = _load_predecessor_evidence(
        predecessor_path
    )
    if (
        _canonical_sha(predecessor_freeze)
        != predecessor.get("internal_freeze_canonical_sha256")
        or predecessor_members != predecessor.get("internal_freeze_member_sha256")
    ):
        raise ValueError("replacement predecessor internal freeze binding mismatch")
    if (
        _canonical_sha(predecessor_report)
        != predecessor.get("native_report_canonical_sha256")
        or _canonical_sha(predecessor_run)
        != predecessor.get("run_manifest_canonical_sha256")
    ):
        raise ValueError("replacement predecessor execution evidence binding mismatch")
    predecessor_source = predecessor_freeze.get("source")
    replacement_source = manifest.get("source")
    if not isinstance(predecessor_source, Mapping) or not isinstance(
        replacement_source, Mapping
    ):
        raise TypeError("predecessor/replacement source bindings are missing")
    for field in (
        "config_sha256",
        "trace_sha256",
        "profile_sha256",
        "explicit_token_ids_sha256",
        "pressure_token_ids_sha256",
        "logical_sequence_sha256",
    ):
        if predecessor_source.get(field) != replacement_source.get(field):
            raise ValueError(f"replacement source binding mismatch: {field}")
    config_path = input_dir / str(derived["config"])
    trace_path = input_dir / str(derived["trace"])
    profile_path = Path(str(derived["profile_path"]))
    for path, field in (
        (config_path, "config_sha256"),
        (trace_path, "trace_sha256"),
        (profile_path, "profile_sha256"),
    ):
        if not path.is_file() or _sha(path) != derived.get(field):
            raise ValueError(f"freeze binding mismatch: {field}")
    return manifest, config_path


def _verify_authorization(
    authorization_path: Path,
    *,
    input_dir: Path,
    freeze: Mapping[str, object],
) -> tuple[dict[str, object], Path, str]:
    try:
        authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("M1 execution authorization record is unreadable") from error
    if not isinstance(authorization, dict):
        raise TypeError("M1 execution authorization must be a JSON object")
    predecessor = freeze.get("predecessor")
    if not isinstance(predecessor, Mapping):
        raise TypeError("freeze predecessor binding is missing")
    expected = {
        "schema_version": AUTHORIZATION_SCHEMA,
        "execution_authorized": True,
        "run_id": RUN_ID,
        "git_sha": freeze["git_sha"],
        "freeze_record_sha256": _sha(input_dir / "freeze-record.json"),
        "predecessor_archive_sha256": predecessor["archive_sha256"],
        "maximum_execution_count": 1,
        "timeout_seconds": 1800,
        "termination_grace_seconds": 60,
    }
    for field, value in expected.items():
        if authorization.get(field) != value:
            raise ValueError(f"M1 execution authorization mismatch: {field}")
    authorization_id = authorization.get("authorization_id")
    if not isinstance(authorization_id, str) or not authorization_id:
        raise ValueError("M1 execution authorization ID is missing")
    trust = freeze.get("m1_authorization_trust")
    if not isinstance(trust, Mapping):
        raise TypeError("freeze M1 authorization trust root is missing")
    if authorization.get("signature_algorithm") != AUTHORIZATION_ALGORITHM:
        raise ValueError("M1 execution authorization signature algorithm mismatch")
    signature = authorization.get("signature")
    if not isinstance(signature, str) or not signature:
        raise ValueError("M1 execution authorization signature is missing")
    signed = dict(authorization)
    signed.pop("signature", None)
    payload = json.dumps(signed, sort_keys=True, separators=(",", ":")).encode()
    public_key = str(trust.get("public_key_pem", ""))
    if hashlib.sha256(public_key.encode()).hexdigest() != trust.get("public_key_sha256"):
        raise ValueError("M1 public-key trust root hash mismatch")
    import tempfile
    with tempfile.TemporaryDirectory(prefix="phase2i-m1-signature-") as directory:
        root = Path(directory)
        (root / "allowed_signers").write_text(
            f"M1 {public_key.strip()}\n", encoding="utf-8"
        )
        (root / "payload.bin").write_bytes(payload)
        (root / "payload.bin.sig").write_text(signature, encoding="utf-8")
        verification = subprocess.run(
            (
                "ssh-keygen", "-Y", "verify", "-f", str(root / "allowed_signers"),
                "-I", "M1", "-n", "phase2i-replacement-preflight",
                "-s", str(root / "payload.bin.sig"),
            ),
            input=payload,
            check=False,
            capture_output=True,
        )
    if verification.returncode != 0:
        raise ValueError("M1 execution authorization signature verification failed")
    authorization_sha = _sha(authorization_path)
    predecessor_path = Path(str(predecessor["archive_path"]))
    ledger = (
        predecessor_path.parent
        / ".phase2i-authorization-ledger"
        / f"{_canonical_sha({'run_id': RUN_ID, 'freeze': expected['freeze_record_sha256']})}.consumed.json"
    )
    return authorization, ledger, authorization_sha


def _consume_authorization(
    ledger_path: Path,
    *,
    authorization: Mapping[str, object],
    authorization_sha256: str,
    output_root: Path,
) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "phase2i.a3_execution_authorization_consumption.v1",
        "authorization_id": authorization["authorization_id"],
        "authorization_sha256": authorization_sha256,
        "run_id": RUN_ID,
        "output_root": str(output_root.resolve()),
        "consumed_at_unix_seconds": time.time(),
    }
    try:
        descriptor = os.open(
            ledger_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError as error:
        raise RuntimeError("M1 execution authorization was already consumed") from error
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _validate_environment(environment: Mapping[str, object]) -> None:
    if environment.get("cuda_available") is not True:
        raise RuntimeError("target CUDA preflight requires an available CUDA GPU")
    for field, expected in EXPECTED_ENVIRONMENT.items():
        if environment.get(field) != expected:
            raise RuntimeError(
                f"target CUDA environment mismatch: {field}="
                f"{environment.get(field)!r}, expected {expected!r}"
            )


def _right_censoring_evidence(
    config: Mapping[str, object], events: tuple[Mapping[str, object], ...]
) -> dict[str, object]:
    backend = config.get("backend_options")
    expected = (
        set(backend.get("w1b_right_censored_end_request_ids") or ())
        if isinstance(backend, Mapping)
        else set()
    )
    observed = {
        str(row.get("request_id"))
        for row in events
        if row.get("event_type") == "W1B_RIGHT_CENSORED_REPLAY_WINDOW_ENDED"
        and row.get("request_id")
    }
    return {
        "right_censoring_preserved": bool(expected) and observed == expected,
        "expected_right_censored_request_ids": sorted(expected),
        "observed_right_censored_request_ids": sorted(observed),
    }


def _environment() -> dict[str, object]:
    import torch
    import vllm

    nvidia_smi = subprocess.run(
        (
            "nvidia-smi",
            "--query-gpu=name,memory.total,driver_version,compute_cap",
            "--format=csv,noheader,nounits",
        ),
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "vllm": vllm.__version__,
        "torch": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "gpu_memory_bytes": (
            torch.cuda.get_device_properties(0).total_memory
            if torch.cuda.is_available()
            else None
        ),
        "nvidia_smi_query": (
            nvidia_smi.stdout.strip() if nvidia_smi.returncode == 0 else None
        ),
        "nvidia_smi_error": (
            None if nvidia_smi.returncode == 0 else nvidia_smi.stderr.strip()
        ),
    }


def _write_sha_manifest(root: Path) -> Path:
    manifest = root / "sha256-manifest.txt"
    rows = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path == manifest:
            continue
        rows.append(f"{_sha(path)}  {path.relative_to(root)}")
    manifest.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return manifest


def run_preflight(
    *,
    input_dir: Path,
    output_root: Path,
    repository: Path,
    authorization_path: Path,
    bounded_capability: _InheritedExecutionCapability,
) -> dict[str, object]:
    """Run once and independently evaluate persisted CUDA Native evidence."""
    if (
        not isinstance(bounded_capability, _InheritedExecutionCapability)
        or bounded_capability.parent_pid != os.getppid()
        or bounded_capability.run_id != RUN_ID
    ):
        raise RuntimeError("GPU execution requires the bounded parent capability")
    freeze, config_path = _verify_freeze(input_dir, repository)
    authorization, ledger_path, authorization_sha = _verify_authorization(
        authorization_path,
        input_dir=input_dir,
        freeze=freeze,
    )
    if output_root.exists():
        raise FileExistsError(output_root)
    environment = _environment()
    _validate_environment(environment)
    output_root.mkdir(parents=True)
    _write(output_root / "freeze-record.json", freeze)
    _write(output_root / "environment.json", environment)
    _write(output_root / "m1-execution-authorization.json", authorization)
    _consume_authorization(
        ledger_path,
        authorization=authorization,
        authorization_sha256=authorization_sha,
        output_root=output_root,
    )
    (output_root / "authorization-consumption.json").write_bytes(
        ledger_path.read_bytes()
    )
    os.environ["VLLM_ENABLE_V1_MULTIPROCESSING"] = "0"
    started = time.perf_counter()
    run_path = run_phase2(
        config_path,
        output_root=output_root / "runs",
        run_id=RUN_ID,
    )
    wall_seconds = time.perf_counter() - started
    run_manifest = json.loads((run_path / "run.json").read_text(encoding="utf-8"))
    events = tuple(
        json.loads(line)
        for line in (run_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    static_report = evaluate_a3_native_preflight(
        events, require_a1_a3_intervention=False
    )
    gates = static_report["gates"]
    config = json.loads(config_path.read_text(encoding="utf-8"))
    right_censoring = _right_censoring_evidence(config, events)
    passed = (
        run_manifest.get("status") == "success"
        and all(gate.get("status") == "PASS" for gate in gates.values())
        and right_censoring["right_censoring_preserved"] is True
    )
    a3_events = [row for row in events if row.get("event_type") == "A3_SUFFIX_RELEASE_DECISION"]
    non_fallback = sum(
        1
        for event in a3_events
        for selection in event.get("payload", {}).get("selection_trace", ())
        if selection.get("fell_back") is not True
    )
    report = {
        "schema_version": "phase2i.a3_target_cuda_native_replacement_preflight.v2",
        "status": "PASS_NATIVE_PREFLIGHT" if passed else "FAIL_CLOSED",
        "claim_scope": (
            "ONE_REPLACEMENT_TARGET_CUDA_NATIVE_PREFLIGHT_NOT_EFFECT_CAMPAIGN"
        ),
        "run_status": run_manifest.get("status"),
        "run_id": RUN_ID,
        "git_sha": freeze["git_sha"],
        "freeze_record_sha256": _canonical_sha(freeze),
        "authorization_sha256": authorization_sha,
        "gates": gates,
        "a3_decision_event_count": len(a3_events),
        "a3_non_fallback_selection_count": non_fallback,
        "wall_elapsed_seconds": wall_seconds,
        "missingness": {
            "physical_eviction_unattributed_count": sum(
                1
                for row in events
                if row.get("event_type") == "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED"
                and row.get("payload", {}).get("physical_attribution")
                != "MATCHED_PENDING_SELECTION_PLAN"
            ),
            **right_censoring,
        },
    }
    _write(output_root / "native-preflight-report.json", report)
    _write_sha_manifest(output_root)
    if not passed:
        raise RuntimeError("Phase 2I target CUDA Native preflight failed closed")
    return report
