"""Deterministically rematerialize accepted SWE prompts for a frozen tokenizer."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .phase5_dataset_processing import file_sha256, load_normalized_trace
from .phase5_replay import canonical_sha256
from .phase5_trace_contract import TokenMaterialization
from .phase5_workload_qualification import QualificationInputs, qualify_formal_session


class SWERematerializationError(ValueError):
    """The accepted source evidence cannot be rematerialized exactly."""


def _messages(turn: Mapping[str, object]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    rows = turn.get("messages")
    if not isinstance(rows, list):
        raise SWERematerializationError("normalized Turn messages are malformed")
    for value in rows:
        if not isinstance(value, Mapping):
            raise SWERematerializationError("normalized message is malformed")
        role = value.get("role")
        content = value.get("content")
        if not isinstance(role, str) or not role:
            raise SWERematerializationError("normalized message role is invalid")
        row: dict[str, object] = {"role": role}
        if isinstance(content, Mapping):
            row.update(content)
        else:
            row["content"] = content
        result.append(row)
    return result


def rematerialize_trace(
    *,
    normalized_trace: Mapping[str, object],
    tokenizer: Any,
    model_revision: str,
    tokenizer_revision: str,
    chat_template_sha256: str,
) -> tuple[TokenMaterialization, ...]:
    turns = normalized_trace.get("turns")
    if not isinstance(turns, list) or not turns:
        raise SWERematerializationError("normalized trace has no Turns")
    result: list[TokenMaterialization] = []
    for turn in turns:
        if not isinstance(turn, Mapping):
            raise SWERematerializationError("normalized Turn is malformed")
        request_id = turn.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise SWERematerializationError("normalized Turn lacks request identity")
        rendered = tokenizer.apply_chat_template(
            _messages(turn), tokenize=False, add_generation_prompt=True
        )
        if not isinstance(rendered, str):
            raise SWERematerializationError("tokenizer did not render a text prompt")
        encoded = tokenizer(rendered, add_special_tokens=False)
        token_ids = encoded["input_ids"]
        if not isinstance(token_ids, list) or any(
            isinstance(value, bool) or not isinstance(value, int) for value in token_ids
        ):
            raise SWERematerializationError("tokenizer returned invalid Token IDs")
        result.append(
            TokenMaterialization(
                request_id=request_id,
                rendered_prompt_sha256=hashlib.sha256(rendered.encode()).hexdigest(),
                token_ids=tuple(token_ids),
                token_ids_sha256=canonical_sha256(token_ids),
                model_revision=model_revision,
                tokenizer_revision=tokenizer_revision,
                chat_template_sha256=chat_template_sha256,
            )
        )
    return tuple(result)


def materialize_accepted_swe_inventory(
    *,
    candidate_inventory: Mapping[str, object],
    evidence_roots: Sequence[Path],
    output_root: Path,
    tokenizer: Any,
    tokenizer_root: Path,
    model_name: str,
    model_revision: str,
    tokenizer_revision: str,
    protocol_sha256: str,
    qualification_contract_sha256: str,
) -> dict[str, object]:
    """Create a new immutable 1.5B token/qualification evidence root."""

    if output_root.exists():
        raise FileExistsError(output_root)
    chat_template = getattr(tokenizer, "chat_template", None)
    if not isinstance(chat_template, str) or not chat_template:
        raise SWERematerializationError("frozen tokenizer lacks a chat template")
    chat_template_sha256 = hashlib.sha256(chat_template.encode()).hexdigest()
    roots = tuple(path.resolve() for path in evidence_roots)
    rows: list[Mapping[str, object]] = []
    for key in ("existing_qualified_programs", "fresh_qualified_programs"):
        value = candidate_inventory.get(key)
        if not isinstance(value, list) or any(not isinstance(row, Mapping) for row in value):
            raise SWERematerializationError("candidate inventory is malformed")
        rows.extend(value)
    if len(rows) != 48:
        raise SWERematerializationError("accepted inventory must contain 48 Programs")
    output_root.mkdir(parents=True)
    session_rows: list[dict[str, object]] = []
    files: list[dict[str, object]] = []
    for source in rows:
        session_id = str(source.get("session_id"))
        candidates = [root / "sessions" / session_id for root in roots]
        source_root = next((path for path in candidates if path.is_dir()), None)
        if source_root is None:
            raise SWERematerializationError(f"source Session is missing: {session_id}")
        normalized_path = source_root / "normalized-trace.json"
        fixtures_path = source_root / "tool-fixtures.json"
        prior_path = source_root / "qualification.json"
        if (
            file_sha256(normalized_path) != source.get("normalized_trace_file_sha256")
            or file_sha256(fixtures_path) != source.get("tool_fixtures_file_sha256")
            or file_sha256(prior_path) != source.get("qualification_file_sha256")
        ):
            raise SWERematerializationError(f"source evidence hash mismatch: {session_id}")
        normalized_value = json.loads(normalized_path.read_text(encoding="utf-8"))
        trace = load_normalized_trace(normalized_path)
        tokens = rematerialize_trace(
            normalized_trace=normalized_value,
            tokenizer=tokenizer,
            model_revision=model_revision,
            tokenizer_revision=tokenizer_revision,
            chat_template_sha256=chat_template_sha256,
        )
        fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))
        prior = json.loads(prior_path.read_text(encoding="utf-8"))
        fixture_hashes = {
            str(call_id): canonical_sha256(payload)
            for call_id, payload in fixtures.items()
        }
        report = qualify_formal_session(
            trace=trace,
            token_materializations=tokens,
            inputs=QualificationInputs(
                license_accepted=prior["checks"]["Q8_LICENSE"] is True,
                outcome_blind=prior["checks"]["Q9_OUTCOME_BLIND"] is True,
                censor_reason=prior.get("censor_reason"),
                tool_fixture_sha256_by_call_id=fixture_hashes,
            ),
        )
        bound = {
            **{key: value for key, value in report.items() if key != "qualification_sha256"},
            "protocol_sha256": protocol_sha256,
            "qualification_contract_sha256": qualification_contract_sha256,
            "rematerialization_identity": {
                "model_name": model_name,
                "model_revision": model_revision,
                "tokenizer_revision": tokenizer_revision,
                "chat_template_sha256": chat_template_sha256,
                "tokenizer_root_sha256": canonical_sha256(
                    sorted(
                        [
                            [path.name, file_sha256(path)]
                            for path in tokenizer_root.iterdir()
                            if path.is_file()
                        ]
                    )
                ),
            },
            "source_evidence_sha256": {
                "normalized_trace": file_sha256(normalized_path),
                "tool_fixtures": file_sha256(fixtures_path),
                "prior_token_materialization": source.get(
                    "token_materialization_file_sha256"
                ),
                "prior_qualification": file_sha256(prior_path),
            },
        }
        qualification = {**bound, "qualification_sha256": canonical_sha256(bound)}
        session_root = output_root / "sessions" / session_id
        session_root.mkdir(parents=True)
        token_path = session_root / "token-materialization.json"
        qualification_path = session_root / "qualification.json"
        token_payload = [
            {
                "request_id": row.request_id,
                "rendered_prompt_sha256": row.rendered_prompt_sha256,
                "token_ids": list(row.token_ids),
                "token_ids_sha256": row.token_ids_sha256,
                "model_revision": row.model_revision,
                "tokenizer_revision": row.tokenizer_revision,
                "chat_template_sha256": row.chat_template_sha256,
            }
            for row in tokens
        ]
        token_path.write_text(
            json.dumps(token_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        qualification_path.write_text(
            json.dumps(qualification, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        for path in (token_path, qualification_path):
            files.append(
                {
                    "path": path.relative_to(output_root).as_posix(),
                    "sha256": file_sha256(path),
                    "bytes": path.stat().st_size,
                }
            )
        session_rows.append(
            {
                "program_id": source.get("program_id"),
                "session_id": session_id,
                "source_normalized_trace_file_sha256": file_sha256(normalized_path),
                "source_tool_fixtures_file_sha256": file_sha256(fixtures_path),
                "prior_token_materialization_file_sha256": source.get(
                    "token_materialization_file_sha256"
                ),
                "token_materialization_file_sha256": file_sha256(token_path),
                "qualification_file_sha256": file_sha256(qualification_path),
                "qualification_sha256": qualification["qualification_sha256"],
                "qualification_status": qualification["status"],
                "failed_rules": qualification["failed_rules"],
                "maximum_prompt_tokens_observed": max(
                    len(row.token_ids) for row in tokens
                ),
            }
        )
    summary_payload = {
        "schema_version": "phase5.swe_1p5b_rematerialization.v1",
        "status": "PASS" if all(row["qualification_status"] == "QUALIFIED" for row in session_rows) else "FAIL_CLOSED_QUALIFICATION_EXCLUSIONS",
        "candidate_inventory_content_sha256": candidate_inventory.get(
            "candidate_inventory_content_sha256"
        ),
        "model_name": model_name,
        "model_revision": model_revision,
        "tokenizer_revision": tokenizer_revision,
        "chat_template_sha256": chat_template_sha256,
        "session_count": len(session_rows),
        "qualified_count": sum(row["qualification_status"] == "QUALIFIED" for row in session_rows),
        "excluded_count": sum(row["qualification_status"] != "QUALIFIED" for row in session_rows),
        "sessions": session_rows,
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
    }
    summary = {**summary_payload, "summary_sha256": canonical_sha256(summary_payload)}
    summary_path = output_root / "collection-summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    files.append(
        {
            "path": summary_path.name,
            "sha256": file_sha256(summary_path),
            "bytes": summary_path.stat().st_size,
        }
    )
    manifest = {
        "schema_version": "phase5.swe_1p5b_rematerialization_manifest.v1",
        "files": sorted(files, key=lambda row: str(row["path"])),
    }
    manifest_path = output_root / "sha256-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary
