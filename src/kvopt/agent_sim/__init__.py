"""Phase 2F agent-scenario KV-cache APC simulation (``simulation-only``).

This package is a CPU-only, event-driven research harness for the project's
vLLM GPU APC eviction problem. It is **not** a runtime policy, **not** a latency
model, and **not** evidence about real vLLM serving. It reuses the frozen
Phase 1B Continuum components without modifying them.

Layout:

* ``content``      — chained-hash content identity (prefix trie);
* ``pool``         — physical block pool with a vLLM-style free queue;
* ``trace``        — the ``phase2f.trace.v1`` schema and validation;
* ``workload_gen`` — deterministic agent scenario families S1–S7;
* ``retention_bridge`` — wiring for the frozen Continuum runtime;
* ``policies``     — native / candidate v0 / oracle victim-selection policies;
* ``simulator``    — the deterministic event-driven engine;
* ``experiments``  — arms, paired statistics, counterfactual analysis;
* ``report``       — JSON / markdown / chart rendering;
* ``cli``          — one-command campaign runner.
"""
