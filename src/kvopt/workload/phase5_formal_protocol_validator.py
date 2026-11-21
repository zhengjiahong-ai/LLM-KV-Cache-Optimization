"""Fail-closed engineering validation for the Phase 5 Formal Protocol.

The M4-owned protocol documents remain the source of research semantics.  This
module only validates their identity and the bindings consumed by an execution
system.  A structurally valid design candidate is deliberately *not* an
executable protocol.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

SYSTEM_IDS = (
    "NATIVE",
    "CONTINUUM_OFFICIAL",
    "CONTINUUM_ADAPTED",
    "A1_ORIGINAL",
    "A3_SUFFIX",
    "DVA_ER_V1",
)
EXECUTABLE_PROTOCOL_STATUS = "M1_FROZEN"


class Phase5ProtocolValidationError(ValueError):
    """Raised when a formal protocol or execution binding fails closed."""


@dataclass(frozen=True)
class ProtocolBundle:
    """Validated protocol documents and their byte-exact identities."""

    protocol: Mapping[str, Any]
    contracts: Mapping[str, Mapping[str, Any]]
    sha256: Mapping[str, str]

    @property
    def protocol_sha256(self) -> str:
        return self.sha256["protocol"]

    @property
    def execution_ready(self) -> bool:
        return (
            self.protocol["status"] == EXECUTABLE_PROTOCOL_STATUS
            and self.protocol["execution_authorized"] is True
            and not self.protocol["unresolved"]
            and _systems_frozen(self.protocol["systems"])
        )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise Phase5ProtocolValidationError(f"{path} must contain a JSON object")
    return value


def _validate_schema(
    document: Mapping[str, Any], schema: Mapping[str, Any], label: str
) -> None:
    jsonschema.Draft202012Validator.check_schema(schema)
    errors = sorted(
        jsonschema.Draft202012Validator(schema).iter_errors(document),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        details = "; ".join(error.message for error in errors[:5])
        raise Phase5ProtocolValidationError(f"{label} schema validation failed: {details}")


def _systems_frozen(systems: Sequence[Mapping[str, Any]]) -> bool:
    by_id = {system["id"]: system for system in systems}
    dva = by_id.get("DVA_ER_V1", {})
    official = by_id.get("CONTINUUM_OFFICIAL", {})
    adapted = by_id.get("CONTINUUM_ADAPTED", {})
    return (
        dva.get("status") == "FROZEN"
        and dva.get("candidate_selection_gate") == "PASS"
        and official.get("compatibility_status") not in {None, "", "AUDIT_REQUIRED"}
        and adapted.get("scheduler_conformance") not in {None, "", "REQUIRED"}
    )


def validate_protocol_bundle(
    *,
    protocol_path: Path,
    protocol_schema_path: Path,
    contract_paths: Mapping[str, Path],
    contracts_schema_path: Path,
    expected_sha256: Mapping[str, str] | None = None,
) -> ProtocolBundle:
    """Validate schemas, references, protocol identity, arms and exact hashes.

    ``expected_sha256`` is optional for design-time inspection.  Execution code
    must provide it and subsequently call :func:`require_execution_ready`.
    """

    protocol = _load(protocol_path)
    _validate_schema(protocol, _load(protocol_schema_path), "protocol")
    if protocol["status"] == "DESIGN_FROZEN_CANDIDATE" and protocol[
        "execution_authorized"
    ] is not False:
        raise Phase5ProtocolValidationError(
            "DESIGN_FROZEN_CANDIDATE must have execution_authorized=false"
        )

    systems = protocol["systems"]
    observed_ids = [system["id"] for system in systems]
    if observed_ids != list(SYSTEM_IDS) or len(set(observed_ids)) != len(SYSTEM_IDS):
        raise Phase5ProtocolValidationError(
            "systems must be the ordered, unique four-arm definition "
            + ",".join(SYSTEM_IDS)
        )
    if protocol["scope"]["systems"] != list(SYSTEM_IDS):
        raise Phase5ProtocolValidationError("scope systems differ from arm definitions")
    workload = protocol["workload"]
    if workload["min_turns_per_session"] != 4:
        raise Phase5ProtocolValidationError("formal Sessions require at least four Turns")
    if "max_turns_per_session" in workload:
        raise Phase5ProtocolValidationError(
            "formal Sessions must not have an additional fixed Turn ceiling"
        )

    contracts_schema = _load(contracts_schema_path)
    contracts: dict[str, Mapping[str, Any]] = {}
    hashes = {"protocol": _sha256(protocol_path)}
    for name, path in contract_paths.items():
        contract = _load(path)
        _validate_schema(contract, contracts_schema, f"{name} contract")
        if contract.get("protocol_id") != protocol["protocol_id"]:
            raise Phase5ProtocolValidationError(
                f"{name} contract protocol_id does not match the protocol"
            )
        reference = protocol["contracts"].get(name)
        if contract.get("schema_version") != reference:
            raise Phase5ProtocolValidationError(
                f"{name} contract schema_version does not match protocol reference"
            )
        contracts[name] = contract
        hashes[name] = _sha256(path)

    qualification = contracts["workload_qualification"]
    unit_contract = qualification["unit_contract"]
    if unit_contract.get("min_turns_per_session") != workload["min_turns_per_session"]:
        raise Phase5ProtocolValidationError(
            "workload qualification minimum Turns differ from protocol"
        )
    if unit_contract.get("additional_turn_ceiling", object()) is not None:
        raise Phase5ProtocolValidationError(
            "workload qualification must define no additional Turn ceiling"
        )
    q6 = {rule["id"]: rule for rule in qualification["qualification_rules"]}
    if "Q6_CONTEXT_AND_EXACT_TOKENS" not in q6:
        raise Phase5ProtocolValidationError(
            "workload qualification is missing the context and exact-token Q6"
        )

    expected_contracts = {
        "metrics",
        "workload_qualification",
        "calibration_sample_size",
        "cost_aware_candidate_family",
        "candidate_evaluation",
    }
    if set(contract_paths) != expected_contracts:
        raise Phase5ProtocolValidationError(
            f"contract files must be exactly {sorted(expected_contracts)}"
        )
    if protocol["contracts"].get("campaign_manifest") != "phase5.campaign_manifest.v1":
        raise Phase5ProtocolValidationError("campaign manifest contract is not v1")

    if expected_sha256 is not None:
        if set(expected_sha256) != set(hashes):
            raise Phase5ProtocolValidationError("frozen hash key set is incomplete")
        mismatches = sorted(
            name
            for name, actual in hashes.items()
            if expected_sha256.get(name) != actual
        )
        if mismatches:
            raise Phase5ProtocolValidationError(
                f"frozen contract hash mismatch: {','.join(mismatches)}"
            )

    return ProtocolBundle(protocol=protocol, contracts=contracts, sha256=hashes)


def require_execution_ready(bundle: ProtocolBundle) -> None:
    """Reject any bundle that has not been fully frozen and authorized by M1."""

    reasons: list[str] = []
    if bundle.protocol["status"] != EXECUTABLE_PROTOCOL_STATUS:
        reasons.append(f"status={bundle.protocol['status']}")
    if bundle.protocol["execution_authorized"] is not True:
        reasons.append("execution_authorized=false")
    if bundle.protocol["unresolved"]:
        reasons.append("unresolved decisions remain")
    if not _systems_frozen(bundle.protocol["systems"]):
        reasons.append("one or more arm configurations are not frozen")
    if reasons:
        raise Phase5ProtocolValidationError(
            "formal execution is not authorized: " + "; ".join(reasons)
        )


def validate_campaign_manifest_set(
    *,
    manifests: Sequence[Mapping[str, Any]],
    manifest_schema: Mapping[str, Any],
    bundle: ProtocolBundle,
    expected_workload_seal_sha256: str,
    expected_runtime_identity: Mapping[str, str],
    expected_system_revisions: Mapping[str, str],
) -> None:
    """Validate one complete four-arm paired manifest set.

    The function checks only identities shared by a paired execution.  It does
    not derive metrics or decide the research cohort.
    """

    if len(manifests) != len(SYSTEM_IDS):
        raise Phase5ProtocolValidationError("paired manifest set must contain six systems")
    required_runtime_keys = {
        "model_revision",
        "tokenizer_revision",
        "sampling_parameters_sha256",
        "engine_configuration_sha256",
        "generation_config_sha256",
        "arrival_realization_sha256",
    }
    if set(expected_runtime_identity) != required_runtime_keys:
        raise Phase5ProtocolValidationError("runtime identity key set is incomplete")
    if set(expected_system_revisions) != set(SYSTEM_IDS):
        raise Phase5ProtocolValidationError("system revision key set is incomplete")

    seen_runs: set[str] = set()
    seen_systems: set[str] = set()
    paired_identity: tuple[str, str, int] | None = None
    for manifest in manifests:
        _validate_schema(manifest, manifest_schema, "campaign manifest")
        if manifest["run_id"] in seen_runs:
            raise Phase5ProtocolValidationError("duplicate campaign run_id")
        seen_runs.add(manifest["run_id"])
        system_id = manifest["system_id"]
        if system_id in seen_systems:
            raise Phase5ProtocolValidationError(f"duplicate arm manifest: {system_id}")
        seen_systems.add(system_id)
        if manifest["protocol_id"] != bundle.protocol["protocol_id"]:
            raise Phase5ProtocolValidationError("manifest protocol_id mismatch")
        if manifest["protocol_sha256"] != bundle.protocol_sha256:
            raise Phase5ProtocolValidationError("manifest protocol_sha256 mismatch")
        if manifest["workload_seal_sha256"] != expected_workload_seal_sha256:
            raise Phase5ProtocolValidationError("manifest workload seal mismatch")
        for key, expected in expected_runtime_identity.items():
            if manifest[key] != expected:
                raise Phase5ProtocolValidationError(
                    f"cross-arm runtime identity mismatch: {key}"
                )
        if manifest["system_revision"] != expected_system_revisions[system_id]:
            raise Phase5ProtocolValidationError(
                f"system revision mismatch for {system_id}"
            )
        identity = (
            manifest["group_id"],
            manifest["stratum"],
            manifest["repeat_index"],
        )
        if paired_identity is None:
            paired_identity = identity
        elif paired_identity != identity:
            raise Phase5ProtocolValidationError("six systems are not paired to one workload")

    if seen_systems != set(SYSTEM_IDS):
        raise Phase5ProtocolValidationError("paired manifest set is missing a registered arm")

