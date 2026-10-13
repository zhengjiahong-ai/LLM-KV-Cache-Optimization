import copy
import json
from pathlib import Path

import pytest

from kvopt.workload.phase2c_native_pilot import (
    expected_segment_lcp_tokens,
    validate_pilot_documents,
)

CONFIG_ROOT = Path("configs/phase2")


def _documents() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    names = (
        "phase2c-native-pilot-authorization.json",
        "phase2c-native-pilot-contract-v1.json",
        "phase2c-native-pilot-cases-v1.json",
    )
    return tuple(
        json.loads((CONFIG_ROOT / name).read_text(encoding="utf-8"))
        for name in names
    )


def test_frozen_pilot_documents_are_consistent_and_bounded() -> None:
    authorization, contract, cases = _documents()

    validate_pilot_documents(authorization, contract, cases)


def test_segment_lcp_stops_before_fork_and_supports_growth() -> None:
    left = {"segments": [["root", 128], ["left", 64]]}
    right = {"segments": [["root", 128], ["right", 64]]}
    grown = {"segments": [["root", 128], ["left", 64], ["turn", 32]]}

    assert expected_segment_lcp_tokens(left, right) == 128
    assert expected_segment_lcp_tokens(left, grown) == 192


def test_pilot_rejects_declared_lcp_that_content_does_not_support() -> None:
    authorization, contract, cases = _documents()
    changed = copy.deepcopy(cases)
    exact = next(row for row in changed["cases"] if row["case_id"] == "w-exact")
    exact["requests"][1]["eligible_prefix_tokens"] = 128

    with pytest.raises(ValueError, match="differs from segment LCP"):
        validate_pilot_documents(authorization, contract, changed)


def test_pilot_rejects_pressure_pair_with_changed_content() -> None:
    authorization, contract, cases = _documents()
    changed = copy.deepcopy(cases)
    pressure = next(
        row for row in changed["cases"] if row["case_id"] == "w-pressure-native"
    )
    for request in pressure["requests"]:
        request["segments"][0][0] = "changed-root"

    with pytest.raises(ValueError, match="keep content identity fixed"):
        validate_pilot_documents(authorization, contract, changed)
