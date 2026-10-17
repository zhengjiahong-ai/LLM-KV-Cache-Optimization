"""Keep the joint-design probes honest.

Each probe under ``scripts/probes/`` is a small, self-checking script that backs a
number or claim in ``docs/phase2-cost-aware-joint-design.md``. Running them from
the test suite means the document and the code cannot drift apart silently.

The H1 probes need run artifacts that are not committed, so they are not part of
the suite; see ``scripts/probes/README.md`` for how to run them manually.
"""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

PROBE_DIR = Path(__file__).resolve().parents[1] / "scripts" / "probes"

SELF_CONTAINED = (
    "probe_example_entry_release.py",
    "probe_example_block_eviction.py",
    "probe_metric_semantics.py",
    "probe_zero_marginal.py",
    "probe_replay_capability.py",
)


@pytest.mark.parametrize("filename", SELF_CONTAINED)
def test_probe_asserts_hold(filename: str) -> None:
    path = PROBE_DIR / filename
    assert path.is_file(), f"missing probe: {path}"

    namespace = runpy.run_path(str(path), run_name="probe_under_test")
    assert "main" in namespace, f"{filename} must expose main()"

    assert namespace["main"]() == 0
