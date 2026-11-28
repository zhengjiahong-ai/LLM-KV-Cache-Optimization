"""Resolve the frozen Calibration members to exact private replay evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from .phase5_replay import canonical_sha256


class CalibrationInputError(ValueError):
    """Frozen membership and private evidence do not form one exact input set."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rows(value: object, label: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list) or any(not isinstance(row, Mapping) for row in value):
        raise CalibrationInputError(f"{label} must be a list of objects")
    return list(value)


def _inventory_rows(inventory: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    rows = _rows(inventory.get("existing_qualified_programs"), "existing Programs")
    rows.extend(_rows(inventory.get("fresh_qualified_programs"), "fresh Programs"))
    by_session: dict[str, Mapping[str, object]] = {}
    for row in rows:
        session_id = row.get("session_id")
        if not isinstance(session_id, str) or not session_id or session_id in by_session:
            raise CalibrationInputError("candidate inventory has invalid Session identity")
        by_session[session_id] = row
    return by_session


def materialize_calibration_input_index(
    *,
    calibration_child: Mapping[str, object],
    candidate_inventory: Mapping[str, object],
    evidence_roots: Sequence[Path],
    rematerialization_root: Path | None = None,
) -> dict[str, object]:
    """Bind all 16 frozen Programs to exact normalized/token/fixture files.

    Paths are retained only as private execution hints. Every downstream input
    identity is the accepted SHA-256, so moving the evidence root cannot change
    the workload.
    """

    if calibration_child.get("schema_version") != "phase5.swe_child_manifest.v1":
        raise CalibrationInputError("unsupported Calibration child manifest")
    if calibration_child.get("role") != "CALIBRATION":
        raise CalibrationInputError("child manifest is not Calibration")
    inventory = _inventory_rows(candidate_inventory)
    roots = tuple(path.resolve() for path in evidence_roots)
    if not roots or any(not path.is_dir() for path in roots):
        raise CalibrationInputError("every private evidence root must exist")
    rematerialized: dict[str, Mapping[str, object]] = {}
    resolved_rematerialization_root: Path | None = None
    if rematerialization_root is not None:
        resolved_rematerialization_root = rematerialization_root.resolve()
        summary_path = resolved_rematerialization_root / "collection-summary.json"
        if not summary_path.is_file():
            raise CalibrationInputError("rematerialization summary is missing")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if (
            summary.get("status") != "PASS"
            or summary.get("session_count") != 48
            or summary.get("candidate_inventory_content_sha256")
            != candidate_inventory.get("candidate_inventory_content_sha256")
        ):
            raise CalibrationInputError("rematerialization root is not accepted")
        rows = _rows(summary.get("sessions"), "rematerialized Sessions")
        rematerialized = {str(row.get("session_id")): row for row in rows}
        if len(rematerialized) != 48:
            raise CalibrationInputError("rematerialization Session identities are invalid")

    bindings: list[dict[str, object]] = []
    seen_programs: set[str] = set()
    seen_sessions: set[str] = set()
    for group in _rows(calibration_child.get("groups"), "Calibration Groups"):
        group_id = group.get("group_id")
        if not isinstance(group_id, str) or not group_id:
            raise CalibrationInputError("Calibration Group identity is invalid")
        members = _rows(group.get("members"), f"{group_id} members")
        if len(members) != 4:
            raise CalibrationInputError("each Calibration Group must contain four Programs")
        for member in members:
            program_id = member.get("program_id")
            session_id = member.get("session_id")
            if not isinstance(program_id, str) or not isinstance(session_id, str):
                raise CalibrationInputError("Calibration member identity is invalid")
            if program_id in seen_programs or session_id in seen_sessions:
                raise CalibrationInputError("Calibration input identity is duplicated")
            seen_programs.add(program_id)
            seen_sessions.add(session_id)
            try:
                source = inventory[session_id]
            except KeyError as error:
                raise CalibrationInputError("Calibration Session is absent from inventory") from error
            for field in (
                "program_id",
                "session_id",
                "source_trace_sha256",
                "qualification_sha256",
                "token_materialization_file_sha256",
            ):
                if member.get(field) != source.get(field):
                    raise CalibrationInputError(
                        f"Calibration member differs from accepted inventory: {field}"
                    )

            candidates = [root / "sessions" / session_id for root in roots]
            session_roots = [path for path in candidates if path.is_dir()]
            if not session_roots:
                raise CalibrationInputError(f"private Session evidence is missing: {session_id}")
            resolved: tuple[Path, Path] | None = None
            for session_root in session_roots:
                normalized = session_root / "normalized-trace.json"
                fixtures = session_root / "tool-fixtures.json"
                if not all(path.is_file() for path in (normalized, fixtures)):
                    continue
                if (
                    _sha256(normalized) == source.get("normalized_trace_file_sha256")
                    and _sha256(fixtures) == source.get("tool_fixtures_file_sha256")
                ):
                    resolved = (normalized, fixtures)
                    break
            if resolved is None:
                raise CalibrationInputError(
                    f"no private evidence version matches accepted hashes: {session_id}"
                )
            normalized, fixtures = resolved
            if resolved_rematerialization_root is None:
                tokens = session_roots[0] / "token-materialization.json"
                token_sha256 = str(source["token_materialization_file_sha256"])
                qualification_sha256 = str(source["qualification_sha256"])
                if not tokens.is_file() or _sha256(tokens) != token_sha256:
                    raise CalibrationInputError(
                        f"accepted hashes differ from token evidence: {session_id}"
                    )
                prior_token_sha256 = None
            else:
                row = rematerialized.get(session_id)
                if row is None or row.get("qualification_status") != "QUALIFIED":
                    raise CalibrationInputError(
                        f"rematerialized Session is not qualified: {session_id}"
                    )
                tokens = (
                    resolved_rematerialization_root
                    / "sessions"
                    / session_id
                    / "token-materialization.json"
                )
                token_sha256 = str(row.get("token_materialization_file_sha256"))
                qualification_sha256 = str(row.get("qualification_sha256"))
                prior_token_sha256 = row.get(
                    "prior_token_materialization_file_sha256"
                )
                if (
                    not tokens.is_file()
                    or _sha256(tokens) != token_sha256
                    or prior_token_sha256
                    != source.get("token_materialization_file_sha256")
                ):
                    raise CalibrationInputError(
                        f"rematerialized token lineage mismatch: {session_id}"
                    )
            bindings.append(
                {
                    "group_id": group_id,
                    "ordinal": member.get("ordinal"),
                    "program_id": program_id,
                    "session_id": session_id,
                    "terminal_class": member.get("terminal_class"),
                    "normalized_trace_path": str(normalized),
                    "normalized_trace_file_sha256": source["normalized_trace_file_sha256"],
                    "token_materialization_path": str(tokens),
                    "token_materialization_file_sha256": token_sha256,
                    "prior_token_materialization_file_sha256": prior_token_sha256,
                    "tool_fixtures_path": str(fixtures),
                    "tool_fixtures_file_sha256": source["tool_fixtures_file_sha256"],
                    "source_trace_sha256": source["source_trace_sha256"],
                    "qualification_sha256": qualification_sha256,
                }
            )

    if len(bindings) != 16:
        raise CalibrationInputError("Calibration requires exactly 16 private input bindings")
    portable = [
        {key: value for key, value in row.items() if not key.endswith("_path")}
        for row in bindings
    ]
    payload = {
        "schema_version": "phase5.swe_calibration_input_index.v1",
        "status": "PASS",
        "program_count": 16,
        "group_count": 4,
        "calibration_child_content_sha256": calibration_child.get(
            "child_content_sha256"
        ),
        "candidate_inventory_content_sha256": candidate_inventory.get(
            "candidate_inventory_content_sha256"
        ),
        "bindings": bindings,
        "portable_bindings_sha256": canonical_sha256(portable),
        "private_evidence_in_public_archive": False,
    }
    return {**payload, "input_index_sha256": canonical_sha256(payload)}
