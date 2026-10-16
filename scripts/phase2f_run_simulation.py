#!/usr/bin/env python
"""Run the complete Phase 2F agent APC eviction x retention simulation study.

CPU-only: no GPU, no model download, no real inference. Generates the
deterministic agent workload campaign, runs every experiment arm over every
scenario draw, computes paired statistics with bootstrap confidence intervals,
runs the free-order and TTL sensitivity probes, and writes machine-readable
JSON, a markdown report and PNG charts.

Usage::

    python scripts/phase2f_run_simulation.py --out results/phase2f
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from kvopt.agent_sim.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
