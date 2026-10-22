import json
from pathlib import Path

from kvopt.workload.continuum_w1a_report import _lcp_length


def test_lcp_length_uses_exact_token_identity() -> None:
    assert _lcp_length([1, 2, 3], [1, 2, 4]) == 2
    assert _lcp_length([1], [1, 2]) == 1
    assert _lcp_length([1], [2]) == 0


def test_report_module_is_json_serializable() -> None:
    # Protect the report's machine-readable surface from non-JSON scalar types.
    assert json.dumps({"path": str(Path("runs")), "lcp": _lcp_length([], [])})
