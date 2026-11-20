"""Record and validate Phase 5 BFCL v4 Web Search acquisitions."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .phase5_acquisition import BFCL_SCHEMA
from .phase5_replay import canonical_sha256

EXPECTED_CASE_COUNTS = {"SNIPPET": 100, "NO_SNIPPET": 100}


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    return value


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{label} must be an array")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _sha256_text(value: str, label: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def _time(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{label} must be finite and non-negative")
    return result


def validate_sampling_frame(
    frame: Mapping[str, object] | Sequence[object], *, source_revision: str
) -> dict[str, object]:
    """Fail closed unless the frozen BFCL frame is exactly 100+100 cases."""

    revision = _text(source_revision, "source_revision")
    if revision == "PINNED_BY_M1":
        raise ValueError("BFCL source revision remains unresolved")
    frame_sha256: str | None = None
    if isinstance(frame, Mapping):
        if frame.get("schema_version") != "phase5.bfcl_sampling_frame.v1":
            raise ValueError("unsupported BFCL sampling-frame schema")
        if frame.get("status") != "FROZEN_ACQUISITION_FRAME_NOT_FORMAL_COHORT":
            raise ValueError("BFCL sampling frame is not frozen for acquisition")
        source = _mapping(frame.get("source"), "sampling-frame source")
        if source.get("revision") != revision:
            raise ValueError("BFCL source revision differs from frozen frame")
        configuration = _mapping(frame.get("configuration"), "configuration")
        if configuration.get("formal_case_count") != 200:
            raise ValueError("BFCL formal case count must be 200")
        if configuration.get("live_search_allowed") is not False:
            raise ValueError("formal BFCL replay must prohibit live search")
        expected_frame_sha = _sha256_text(
            str(frame.get("frame_sha256", "")), "frame_sha256"
        )
        hash_payload = dict(frame)
        hash_payload.pop("frame_sha256", None)
        frame_sha256 = canonical_sha256(hash_payload)
        if frame_sha256 != expected_frame_sha:
            raise ValueError("BFCL sampling-frame SHA-256 mismatch")
        rows: Sequence[object] = _array(frame.get("cases"), "cases")
    else:
        rows = frame
    identities: list[str] = []
    classes: list[str] = []
    normalized: list[dict[str, str]] = []
    for value in rows:
        row = _mapping(value, "sampling-frame row")
        case_id = _text(row.get("case_id"), "case_id")
        case_class = _text(
            row.get("search_mode", row.get("case_class")), "search_mode"
        )
        if case_class not in EXPECTED_CASE_COUNTS:
            raise ValueError(f"unsupported BFCL case class: {case_class}")
        case_sha256 = _sha256_text(
            str(row.get("content_sha256", row.get("case_sha256", ""))),
            "content_sha256",
        )
        if row.get("phase5_case_index") is not None:
            expected_index = len(identities) + 1
            if row.get("phase5_case_index") != expected_index:
                raise ValueError("BFCL phase5_case_index is not contiguous")
            if row.get("show_snippet") is not (case_class == "SNIPPET"):
                raise ValueError("BFCL search mode and show_snippet disagree")
        identities.append(case_id)
        classes.append(case_class)
        normalized.append(
            {"case_id": case_id, "case_class": case_class, "case_sha256": case_sha256}
        )
    if len(identities) != 200:
        raise ValueError("BFCL sampling frame must contain exactly 200 cases")
    if len(set(identities)) != len(identities):
        raise ValueError("BFCL sampling frame contains duplicate case IDs")
    counts = Counter(classes)
    if dict(counts) != EXPECTED_CASE_COUNTS:
        raise ValueError("BFCL sampling frame must contain 100 cases per class")
    normalized.sort(key=lambda row: row["case_id"])
    return {
        "schema_version": "phase5.bfcl_sampling_frame_validation.v1",
        "status": "PASS",
        "source_revision": revision,
        "case_count": len(normalized),
        "case_counts": EXPECTED_CASE_COUNTS,
        "case_ids_unique": True,
        "sampling_frame_sha256": canonical_sha256(normalized),
        "frozen_frame_sha256": frame_sha256,
        "formal_cohort_selected": False,
    }


@dataclass(frozen=True, slots=True)
class SearchObservation:
    """One complete, immutable live-search response."""

    provider: str
    query: str
    arguments: Mapping[str, object]
    response_bytes: bytes
    started_at_seconds: float
    ended_at_seconds: float
    clock_domain: str
    collected_at_utc: str
    source_urls: tuple[str, ...] = ()
    http_status: int | None = None
    error: str | None = None

    def fixture(self, *, tool_call_id: str) -> dict[str, object]:
        if self.ended_at_seconds < self.started_at_seconds:
            raise ValueError("search completion precedes search start")
        if not self.response_bytes and self.error is None:
            raise ValueError("successful search response cannot be empty")
        if self.error is not None and self.response_bytes:
            raise ValueError("failed search cannot also carry response bytes")
        payload = {
            "schema_version": "phase5.bfcl_frozen_search_fixture.v1",
            "tool_call_id": _text(tool_call_id, "tool_call_id"),
            "provider": _text(self.provider, "provider"),
            "query": _text(self.query, "query"),
            "arguments": dict(self.arguments),
            "response_base64": base64.b64encode(self.response_bytes).decode("ascii"),
            "response_sha256": hashlib.sha256(self.response_bytes).hexdigest(),
            "response_byte_count": len(self.response_bytes),
            "source_urls": list(self.source_urls),
            "http_status": self.http_status,
            "started_at_seconds": _time(self.started_at_seconds, "search start"),
            "ended_at_seconds": _time(self.ended_at_seconds, "search completion"),
            "clock_domain": _text(self.clock_domain, "clock_domain"),
            "collected_at_utc": _text(self.collected_at_utc, "collected_at_utc"),
            "state": "FAILED" if self.error is not None else "COMPLETED",
            "error": self.error,
        }
        payload["fixture_sha256"] = canonical_sha256(payload)
        return payload


def build_bfcl_acquisition_record(
    *,
    case: Mapping[str, object],
    source_revision: str,
    source_uri: str,
    license_expression: str,
    model_identity: str,
    model_revision: str,
    tokenizer_revision: str,
    chat_template_sha256: str,
    turns: Sequence[object],
    terminal_state: str,
) -> dict[str, object]:
    """Build one standardized BFCL record from observed model/tool events."""

    revision = _text(source_revision, "source_revision")
    if revision == "PINNED_BY_M1":
        raise ValueError("BFCL source revision remains unresolved")
    case_id = _text(case.get("case_id"), "case_id")
    case_class = _text(case.get("case_class"), "case_class")
    if case_class not in EXPECTED_CASE_COUNTS:
        raise ValueError("unsupported BFCL case class")
    _sha256_text(str(case.get("case_sha256", "")), "case_sha256")
    _sha256_text(chat_template_sha256, "chat_template_sha256")
    normalized_turns = [dict(_mapping(row, "turn")) for row in turns]
    if not normalized_turns:
        raise ValueError("BFCL acquisition must contain at least one model turn")
    return {
        "schema_version": BFCL_SCHEMA,
        "trace_id": f"phase5:bfcl:{case_id}",
        "program_id": case_id,
        "session_id": f"phase5:bfcl:{case_id}:session:1",
        "task_id": case_id,
        "source": {
            "kind": "BFCL_V4_WEB_SEARCH",
            "dataset": "BFCL_V4_WEB_SEARCH",
            "revision": revision,
            "uri": _text(source_uri, "source_uri"),
            "license": _text(license_expression, "license_expression"),
        },
        "case_class": case_class,
        "case_sha256": case["case_sha256"],
        "model_identity": _text(model_identity, "model_identity"),
        "model_revision": _text(model_revision, "model_revision"),
        "tokenizer_revision": _text(tokenizer_revision, "tokenizer_revision"),
        "chat_template_sha256": chat_template_sha256,
        "terminal_state": _text(terminal_state, "terminal_state"),
        "turns": normalized_turns,
        "limitations": [],
        "acquisition_origin": "PHASE5_NEW_ACQUISITION",
        "formal_cohort_selected": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sampling-frame", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    frame = json.loads(arguments.sampling_frame.read_text(encoding="utf-8"))
    if not isinstance(frame, (dict, list)):
        raise TypeError("sampling frame must be an object or array")
    report = validate_sampling_frame(frame, source_revision=arguments.source_revision)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote: {arguments.output.resolve()}")
    print(f"sha256: {hashlib.sha256(arguments.output.read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
