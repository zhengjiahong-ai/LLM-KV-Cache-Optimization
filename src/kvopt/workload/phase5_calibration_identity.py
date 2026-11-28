"""Audit frozen replay token identities against the formal execution protocol."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from .phase5_replay import canonical_sha256


class CalibrationIdentityError(ValueError):
    """The identity evidence cannot be audited mechanically."""


_FIELDS = ("model_revision", "tokenizer_revision", "chat_template_sha256")


def audit_calibration_execution_identity(
    *, protocol: Mapping[str, object], input_index: Mapping[str, object]
) -> dict[str, object]:
    systems = protocol.get("systems")
    bindings = input_index.get("bindings")
    if not isinstance(systems, list) or not isinstance(bindings, list):
        raise CalibrationIdentityError("protocol systems and input bindings are required")
    protocol_rows = [row for row in systems if isinstance(row, Mapping)]
    inherited = next(
        (row for row in protocol_rows if row.get("id") == "CONTINUUM_ADAPTED"), None
    )
    if inherited is None:
        raise CalibrationIdentityError("formal execution identity is missing")
    expected = {
        "model": inherited.get("model"),
        "model_revision": inherited.get("model_revision"),
        "tokenizer_revision": inherited.get("tokenizer_revision"),
    }
    observed: set[tuple[object, ...]] = set()
    for binding in bindings:
        if not isinstance(binding, Mapping):
            raise CalibrationIdentityError("input binding is malformed")
        path = Path(str(binding.get("token_materialization_path")))
        value = json.loads(path.read_text(encoding="utf-8"))
        rows = value if isinstance(value, list) else value.get("requests")
        if not isinstance(rows, list) or not rows:
            raise CalibrationIdentityError("token materialization has no request rows")
        for row in rows:
            if not isinstance(row, Mapping):
                raise CalibrationIdentityError("token materialization row is malformed")
            observed.add(tuple(row.get(field) for field in _FIELDS))
    observed_rows = [dict(zip(_FIELDS, values, strict=True)) for values in sorted(observed)]
    matches = len(observed_rows) == 1 and all(
        observed_rows[0].get(field) == expected.get(field)
        for field in ("model_revision", "tokenizer_revision")
    )
    payload = {
        "schema_version": "phase5.swe_calibration_execution_identity_audit.v1",
        "status": "PASS" if matches else "FAIL_CLOSED_IDENTITY_MISMATCH",
        "program_count": input_index.get("program_count"),
        "expected_execution_identity": expected,
        "observed_token_materialization_identities": observed_rows,
        "same_prompt_token_ids_required": protocol.get("controlled_variables", {}).get(
            "same_prompt_token_ids"
        ) if isinstance(protocol.get("controlled_variables"), Mapping) else None,
        "rematerialization_permitted": False,
        "protocol_mutation_permitted": False,
    }
    return {**payload, "identity_audit_sha256": canonical_sha256(payload)}
