"""Unit checks for the fail-closed Phase 3 null-mechanism probe.

The full probe needs the frozen archive and is run manually (see the analysis
document §12.0). These tests pin the two numerical rules the PR #105 review
called out: the reuse proxy is increasing in deadline, and Step 2 is decided by
``new_blocks >= need`` rather than ``suffix_blocks >= need``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROBE = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "probes"
    / "phase3_null_mechanism"
    / "probe.py"
)


def _load_probe():
    spec = importlib.util.spec_from_file_location("phase3_null_probe", PROBE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def probe():
    return _load_probe()


def test_reuse_proxy_increases_with_deadline(probe) -> None:
    earlier = probe.reuse_proxy(deadline=100.0, timestamp=150.0, tau=30.0)
    later = probe.reuse_proxy(deadline=200.0, timestamp=150.0, tau=30.0)
    assert earlier < 0.5 < later
    assert earlier < later


def test_step2_predicate_uses_new_blocks_not_suffix_blocks(probe) -> None:
    # S < need, but N >= need: the real Step-2 predicate is true.
    audits = [{"suffix_blocks": 10, "new_blocks": 500}]
    assert probe.step2_sufficient(need=97, audits=audits) is True

    # S >= need, but N < need: the real predicate is false.
    audits = [{"suffix_blocks": 200, "new_blocks": 50}]
    assert probe.step2_sufficient(need=97, audits=audits) is False


def test_a3_score_is_independent_recomputation(probe) -> None:
    audit = {
        "key": ["django__django-12050", "hash"],
        "deadline": 399.2891961669993,
        "prefill_reload_seconds": 0.9618859629554208,
        "suffix_blocks": 97,
        "chain_length": 1006,
        "d_min": 910,
        "new_blocks": 999,
        "reuse_proxy": 0.5,
        "score": 0.046373229824391564,
    }
    q, score, order = probe.recompute_a3(audit, need=97, timestamp=399.2891961669993)
    assert q == 0.5
    assert score == pytest.approx(0.046373229824391564)
    assert order[0] == score


def test_a1_expected_uses_lambda_and_new_blocks(probe) -> None:
    score_row = {
        "key": ["sympy__sympy-13551", "hash"],
        "deadline": 309.6993532910019,
        "new_blocks": 882,
        "reuse_proxy": 0.0480473599382167,
        "expected_recompute": 23.519182689757073,
        "per_unit": 0.026665740011062443,
    }
    q, expected, order = probe.recompute_a1(
        score_row, need=97, timestamp=399.2891961669993, tau=30.0, lam=0.5
    )
    assert q == pytest.approx(0.0480473599382167)
    assert expected == pytest.approx(23.519182689757073)
    assert order[0] == expected
