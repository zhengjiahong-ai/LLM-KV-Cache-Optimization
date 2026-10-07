# Phase 2A M4 — Missingness Semantics

Status: **FROZEN** (per M1 ruling, 2026-10-07, item 7)
Owner: M4 (spec + tests). Profiling-side enforcement touched with M6 coordination.

This document freezes how a missing value is represented, propagated, and
reported across the offline analysis path. It exists because a missing loss and
a zero loss are *not the same thing*, and previously the codebase could not
always tell them apart.

---

## 1. The rule

```text
Missing = UNOBSERVED / UNAVAILABLE
Missing != 0
```

Three coercions are explicitly **NOT APPROVED**:

```text
None -> 0
None -> proxy
None -> another loss view
```

Rationale: a coerced zero is a *claim about the world* (this candidate can be
released at no cost). An unobserved value is a statement about *the measurement*.
Substituting one for the other silently changes the hindsight best, the regret
denominator, and any loss-rank comparison built on top.

---

## 2. Representation

### 2.1 A loss row always carries a finite float

`CandidateLossRow.loss` is `float` **by construction**. The boundary enforces it:

```python
# src/kvopt/profiling/analysis.py
def __post_init__(self) -> None:
    if isinstance(self.loss, bool) or not isinstance(self.loss, (int, float)):
        raise ArtifactValidationError(...)
    if not math.isfinite(float(self.loss)):
        raise ArtifactValidationError(...)
```

Missingness is expressed by the **absence of a row**, never by a sentinel value
inside one. `None`, `NaN`, `inf` and `-inf` are all rejected at construction, so
a non-finite loss cannot travel downstream into a ranking.

⚠️ **Before this change** the field had no runtime validation, so
`CandidateLossRow(loss=None)` was constructible and later crashed the signal
analysis with `TypeError: '<' not supported between instances of 'NoneType' and
'float'`. See §5 defect (a).

### 2.2 Unknown provenance stays explicit

Evidence rows (`CandidateLossEvidenceRow`) legitimately carry
`loss: float | None` **plus** `availability` and `unavailable_reason`. That is
where missingness is *declared*, with a reason. The pipeline
(`_gate_loss_views`) already refuses to build a `CandidateLossRow` from a row
whose `loss is None`, so missingness is dropped at the boundary rather than
propagated as a fake number.

---

## 3. Decision-level exclusion

### 3.1 Completeness requirement

```text
A decision enters the evaluated set ONLY when EVERY candidate
has usable evidence for the loss view.
```

Ranking a subset against a full hindsight best would understate the best and
break §1. So the unit of exclusion is the **whole decision**, never a candidate.

### 3.2 Stable reason codes

Frozen strings, quoted by the report and downstream tooling:

| Code | Meaning |
| --- | --- |
| `too_few_candidates` | Fewer than two usable candidates remain; no ranking is definable |
| `candidate_evidence_missing` | At least one candidate lacks usable evidence for this view |
| `decision_snapshot_missing` | No replayable `DecisionSnapshot` for this decision |
| `executed_selection_missing` | The decision has no observed selected release |
| `no_evidence_for_loss_view` | The view supplies no usable evidence for this decision at all |

### 3.3 Scope filtering is **not** missingness

Excluding a run because it belongs to a held-out family is a **scope decision**,
not missing evidence. It is reported in its own field
(`decisions_filtered_out`) and never mixed into the exclusion reasons.

---

## 4. Required reporting

M1 requires that exclusion be auditable, not just tolerated:

```text
skipped decision count     -> MissingnessSummary.decisions_excluded
missing candidate count    -> MissingnessSummary.missing_candidate_total
missing reason / capability-> MissingnessSummary.unavailable_reasons
```

The invariant that must always hold:

```text
decisions_seen == decisions_evaluated
                + decisions_excluded
                + decisions_filtered_out
```

`MissingnessSummary` is attached to every `RuleEvaluation` and emitted in the
JSON report under `missingness`, including a per-decision `excluded_decisions`
list. The text report gains a `MISSINGNESS (reported, never coerced)` section.

---

## 5. Defects this spec closes

All three were verified in the repository, not inferred.

| # | Defect | Location | Status |
| --- | --- | --- | --- |
| (a) | Missing loss crashed the signal analysis instead of being handled | `src/kvopt/profiling/signals.py` (`_normalized_ranks` over an unfiltered list) | **Closed at the source** — the `CandidateLossRow` boundary now makes a non-finite loss unconstructible, so the crash is unreachable |
| (b) | Feature missingness was silently skipped with no coverage record | `src/kvopt/profiling/signals.py` (`continue` on any `None`) | **Closed in this PR by a spec only.** The change is a schema addition to M6's signal tables, so it is tracked as a **separate M6 issue** (`local/M6_ISSUE_feature_missingness_coverage.md`) to be completed **before the H1 campaign materializes**. Semantics are frozen in §6 |
| (c) | Every exclusion cause collapsed into one `skipped_decisions` counter; a fully-unavailable decision was invisible | `src/kvopt/costaware/offline_eval.py` | **Closed** — per-reason codes, missing-candidate counts, capability strings (§3, §4) |

On (c), the specific invisibility: the loop iterated only decisions that had at
least one usable loss, so a decision whose evidence was *entirely* unavailable
produced no record at all and `skipped_decisions` stayed `0`. Excluded
decisions are now enumerated from the full evidence index.

---

## 6. Feature missingness

A missing **feature** is handled at a different granularity than a missing loss:

```text
missing loss    -> exclude the whole decision
missing feature -> skip that feature x decision only, and record coverage
```

Rationale: a feature gap costs one cell of the signal table; a loss gap
invalidates the whole decision's ranking.

⚠️ **Tracked separately (defect (b))**: the signal analysis currently skips such
cells without recording how many were skipped. The required addition is a coverage
record per `(feature, loss_view)`:

```text
evaluated_decision_count
skipped_decision_count
skipped_reason   (e.g. feature_unobserved)
```

This is a schema addition to M6's signal tables. Per the M1 ruling it is **not**
part of this change set; it is issued as a standalone M6 task
(`local/M6_ISSUE_feature_missingness_coverage.md`) and must land **before the H1
campaign materializes**, so no later analysis has to reinterpret a silent skip.
The frozen semantics in this document are the contract that task implements.

---

## 7. Runtime missingness (distinct from offline)

The offline rules above do **not** license a runtime behaviour. If a policy input
is genuinely unavailable at runtime, the correct action is:

```text
fall back to the frozen baseline ordering
```

and **never** fabricate a feature or loss value. A fabricated value would enter
the victim-selection decision, which is exactly the failure the offline rules
exist to prevent. This mirrors the existing offline `fallback_key` discipline in
`src/kvopt/costaware/rules.py`.

---

## 8. Test coverage

| Behaviour | Test |
| --- | --- |
| A missing loss cannot be constructed | `test_phase2a_m6_analysis.py::test_candidate_loss_row_rejects_a_missing_loss` |
| `NaN` / `inf` / `-inf` rejected | `...::test_candidate_loss_row_rejects_non_finite_loss` |
| A finite loss is still accepted | `...::test_candidate_loss_row_accepts_a_finite_loss` |
| Lost candidate records its own code + count + reason | `test_costaware_offline_eval.py::test_missing_candidate_evidence_records_its_own_reason_and_count` |
| Fully-unavailable decision is reported, not invisible | `...::test_fully_unavailable_decision_is_reported_not_invisible` |
| Holdout filtering ≠ missingness | `...::test_holdout_filter_is_reported_separately_from_missingness` |
| Missing snapshot has a distinct code | `...::test_missing_snapshot_records_its_own_reason_code` |
| Too-few-candidates has a distinct code | `...::test_trimmed_candidate_set_is_reported_as_too_few_candidates` |
| Accounting invariant holds | `...::test_missingness_summary_accounts_for_every_seen_decision` |
| Existing never-coerce behaviour preserved | `...::test_unavailable_evidence_does_not_silently_coerce_to_zero`, `...::test_partially_available_decision_is_skipped_not_approximated` |

---

## 9. Traceability

| Statement | Source |
| --- | --- |
| `CandidateLossRow.loss` must stay a finite float | M1 ruling, item 7 |
| `None -> 0` / `-> proxy` / `-> another view` not approved | M1 ruling, item 7 |
| Record skipped decisions, missing candidates, reasons | M1 ruling, item 7 |
| Decision-level exclusion keeps ranking complete | existing evaluator docstring + M1 ruling |
| Runtime fallback = frozen baseline ordering | M1 ruling, item 7 |
| Feature missing = skip cell + record coverage | M1 ruling, item 7 |
| Never silently infer unavailable capabilities | `docs/phase2a-profiling-data-contract.md` §1 |
| Existing fail-closed behaviour | `src/kvopt/costaware/offline_eval.py`, `src/kvopt/profiling/loss_views.py` |
