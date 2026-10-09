# Phase 2A M6 H1 Pre-execution Package

This package is limited to H1 preparation. It does not authorize or contain
formal holdout outcomes.

Completed evidence:

- Issue #34 feature-missingness accounting is implemented and tested.
- The accepted S1--S5 Level-B seam audit is hash-bound.
- Five identical native full-hit baseline repeats were collected.
- The frozen rule gives `epsilon_latency = 0.008793766604503617 seconds`.
- Exactly 42 independent scenario specifications were generated with sampler
  seed `20261007`, seven per family, and sealed before any outcome execution.

The initial v1 pre-execution review was intentionally blocked. Seven v1 sealed scenarios use
the distribution's 24-token prefix value, which the pinned 16-token-block
runtime cannot execute. At that review point, the repository did not contain a
reviewed compiler that maps every abstract per-candidate eta/queue-delay,
shared-ownership, repeated-pressure, multi-release, concurrency, and lifecycle
field into the runtime without fallback.

Finally, the existing seam reports direct evidence for requests that actually
ran. It does not provide an authorized challenger policy switch. Challenger
runtime recomputation therefore cannot be inferred from baseline observations
or future-return plans. M1 must rule on the runtime compilation path and the
Level A/B evidence tier before formal H1 outcomes may be executed.

## 2026-10-09 conditional-review response

M1 approved a minimal alignment revision and a Level A proxy-first path. The
v2 distribution replaces 24-token support with 32 and merges the weight, then
rematerializes all 42 draws with the original sampler seed. The v1 files and
hashes remain unchanged.

The non-holdout compiler fidelity campaign passed at v4. Attempts v1--v3 are
preserved as excluded diagnostics because they did not cause the second
repeated-pressure decision. The accepted v4 verifies actual forced-release
decisions, baseline replay ordering, candidate completeness, and native request
evidence without enabling a challenger policy switch.

The Level A contract fixes the challenger to offline replay of
`H1_R1_reverse_deadline` with `planned_return_weighted_prefill_proxy`. Native
observations may validate the executed baseline, but cannot be turned into
counterfactual challenger recomputation or latency.

Formal execution remains locked. Issue #34 is implemented and tested on this
feature branch but is not recorded as merged to `main`; M1 must approve an
explicit experiment-baseline binding or the change must merge before the final
execution gate can open.
