"""Fail-closed production evidence source for Phase 5E Native Conformance."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from kvopt.profiling.phase5_candidate_exposure import evaluate_run_candidate_exposure


class Phase5ENativeEvidenceError(RuntimeError):
    """The live runtime did not expose the required Native evidence."""


def _payload(row: Mapping[str, object], label: str) -> Mapping[str, object]:
    value = row.get("payload")
    if not isinstance(value, Mapping):
        raise Phase5ENativeEvidenceError(f"{label} payload is not observable")
    return value


class RuntimeEventEvidenceSource:
    """Read immutable A3 decision events from the same live EngineCore.

    The reader must return the complete event prefix each time. This class does
    not synthesize decisions from BlockPool allocation or Native C/LRU output.
    """

    def __init__(
        self,
        *,
        run_id: str,
        event_reader: Callable[[], Sequence[Mapping[str, object]]],
        runtime_installation_report: Mapping[str, object] | None = None,
        runtime_integration: object | None = None,
    ) -> None:
        if not run_id:
            raise ValueError("run_id must be non-empty")
        if not callable(event_reader):
            raise TypeError("event_reader must be callable")
        self._run_id = run_id
        self._event_reader = event_reader
        self._last_size = 0
        self._runtime_installation_report = (
            None if runtime_installation_report is None else dict(runtime_installation_report)
        )
        self._runtime_integration = runtime_integration

    def runtime_installation_report(self) -> Mapping[str, object]:
        if self._runtime_installation_report is None:
            raise Phase5ENativeEvidenceError("runtime installation report is not observable")
        return dict(self._runtime_installation_report)

    def runtime_integration(self) -> object:
        if self._runtime_integration is None:
            raise Phase5ENativeEvidenceError("live A3 runtime integration is unavailable")
        return self._runtime_integration

    def _snapshot(self) -> tuple[Mapping[str, object], ...]:
        rows = tuple(self._event_reader())
        if len(rows) < self._last_size:
            raise Phase5ENativeEvidenceError("Native event stream was truncated")
        indices: list[int] = []
        for row in rows:
            value = row.get("event_index")
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise Phase5ENativeEvidenceError("Native event stream lacks stable event_index")
            indices.append(value)
        if indices != sorted(indices) or len(indices) != len(set(indices)):
            raise Phase5ENativeEvidenceError("Native event indices are duplicated or non-monotonic")
        self._last_size = len(rows)
        return rows

    def pressure_outcome(
        self, boundary_id: str, allocated_block_ids: tuple[int, ...]
    ) -> Mapping[str, object]:
        rows = self._snapshot()
        rows_by_index = {int(row["event_index"]): row for row in rows}
        bindings: dict[str, tuple[int, Mapping[str, object]]] = {}
        outcomes: dict[str, tuple[int, Mapping[str, object]]] = {}
        plans: dict[str, tuple[int, Mapping[str, object]]] = {}
        actual_pressure_bindings: list[tuple[int, Mapping[str, object]]] = []
        for row in rows:
            row_index = int(row["event_index"])
            event_type = row.get("event_type")
            if event_type == "PHASE5E_G9_ACTUAL_PRESSURE_BINDING":
                payload = _payload(row, "actual Pressure binding")
                if payload.get("boundary_id") == boundary_id:
                    if payload.get("validation_status") != "PASS":
                        raise Phase5ENativeEvidenceError(
                            "actual G9 Pressure binding did not pass validation"
                        )
                    actual_pressure_bindings.append((row_index, payload))
                continue
            if event_type == "FORCED_RELEASE_DECISION_BINDING":
                payload = _payload(row, "decision binding")
                observed_boundary = payload.get(
                    "frozen_decision_boundary_id", payload.get("boundary_id")
                )
                if observed_boundary == boundary_id:
                    decision_id = payload.get("decision_id")
                    if not isinstance(decision_id, str) or not decision_id:
                        raise Phase5ENativeEvidenceError("Pressure binding lacks decision_id")
                    if decision_id in bindings:
                        raise Phase5ENativeEvidenceError("Pressure decision binding is not unique")
                    bindings[decision_id] = (row_index, payload)
            elif event_type == "NATIVE_ENTRY_RELEASE_SELECTION_PLAN":
                payload = _payload(row, "selection plan")
                decision_id = payload.get("decision_id")
                if isinstance(decision_id, str):
                    if decision_id in plans:
                        raise Phase5ENativeEvidenceError("Pressure selection plan is not unique")
                    plans[decision_id] = (row_index, payload)
            elif event_type == "NATIVE_ENTRY_RELEASE_PHYSICAL_OUTCOME":
                payload = _payload(row, "physical outcome")
                decision_id = payload.get("decision_id")
                if isinstance(decision_id, str):
                    if decision_id in outcomes:
                        raise Phase5ENativeEvidenceError("Pressure physical outcome is not unique")
                    outcomes[decision_id] = (row_index, payload)
        if not bindings:
            raise Phase5ENativeEvidenceError(
                "no A3 Forced Decision is bound to the Pressure boundary"
            )
        if len(actual_pressure_bindings) != 1:
            raise Phase5ENativeEvidenceError(
                "Pressure boundary lacks one actual G9 Pressure binding"
            )
        actual_pressure_index = actual_pressure_bindings[0][0]
        decision_ids = tuple(bindings)
        if any(
            decision_id not in plans or decision_id not in outcomes for decision_id in decision_ids
        ):
            raise Phase5ENativeEvidenceError(
                "Pressure decision lacks Selection Plan or Physical Outcome"
            )
        evicted: list[int] = []
        referenced_forced_indices: set[int] = set()
        for decision_id in decision_ids:
            binding_index, binding = bindings[decision_id]
            forced_index = binding.get("forced_release_event_index")
            if isinstance(forced_index, bool) or not isinstance(forced_index, int):
                raise Phase5ENativeEvidenceError(
                    "Pressure binding has invalid forced_release_event_index"
                )
            if forced_index in referenced_forced_indices:
                raise Phase5ENativeEvidenceError(
                    "Pressure bindings reference the same Forced Decision event"
                )
            referenced_forced_indices.add(forced_index)
            forced_row = rows_by_index.get(forced_index)
            if forced_row is None or forced_row.get("event_type") != "FORCED_RELEASE_DECISION":
                raise Phase5ENativeEvidenceError(
                    "forced_release_event_index does not reference a Forced Decision"
                )
            forced_payload = _payload(forced_row, "forced release decision")
            forced_boundary = forced_payload.get(
                "frozen_decision_boundary_id", forced_payload.get("boundary_id")
            )
            if forced_payload.get("decision_id") != decision_id:
                raise Phase5ENativeEvidenceError(
                    "Forced Decision identity differs from its binding"
                )
            if forced_boundary != boundary_id:
                raise Phase5ENativeEvidenceError(
                    "Forced Decision boundary differs from its binding"
                )

            plan_index, plan = plans[decision_id]
            outcome_index, outcome = outcomes[decision_id]
            for label, payload in (("Selection Plan", plan), ("Physical Outcome", outcome)):
                observed_boundary = payload.get(
                    "frozen_decision_boundary_id", payload.get("boundary_id")
                )
                if observed_boundary != boundary_id:
                    raise Phase5ENativeEvidenceError(
                        f"{label} boundary differs from its Forced Decision"
                    )
            if not (
                actual_pressure_index
                < forced_index
                < binding_index
                < plan_index
                < outcome_index
            ):
                raise Phase5ENativeEvidenceError(
                    "Decision, binding, Selection Plan and Physical Outcome order is invalid"
                )
            for field in (
                "matched_physical_block_ids",
                "unmatched_physical_block_ids",
                "hashless_physical_block_ids",
            ):
                values = outcome.get(field, [])
                if not isinstance(values, list) or any(
                    isinstance(value, bool) or not isinstance(value, int) for value in values
                ):
                    raise Phase5ENativeEvidenceError(
                        "Physical Outcome block identities are invalid"
                    )
                evicted.extend(values)
        if not evicted:
            raise Phase5ENativeEvidenceError("Pressure lacks observed physical victim blocks")
        if not set(evicted).issubset(set(allocated_block_ids)):
            raise Phase5ENativeEvidenceError("Physical victims are outside the Pressure allocation")
        return {
            "forced_release_decision_ids": list(decision_ids),
            "native_evicted_block_ids": list(dict.fromkeys(evicted)),
        }

    def candidate_exposure_report(self) -> Mapping[str, object]:
        report = evaluate_run_candidate_exposure(
            run_id=self._run_id,
            arm="A3_SUFFIX",
            events=self._snapshot(),
        )
        return {
            **report,
            "downstream_recompute_attribution": "NOT_ESTABLISHED",
            "algorithmic_benefit_claim": "NOT_ESTABLISHED",
        }

    def a3_retention_input_manifest(self) -> Mapping[str, object]:
        """Read the decision-bound Manifest from the reviewed live integration."""

        integration = self.runtime_integration()
        read = getattr(integration, "a3_retention_input_manifest", None)
        if not callable(read):
            raise Phase5ENativeEvidenceError("live A3 retention input manifest is not observable")
        value = read()
        if not isinstance(value, Mapping):
            raise Phase5ENativeEvidenceError("live A3 retention input manifest is not an object")
        return dict(value)

    def raw_evidence(self) -> Sequence[Mapping[str, object]]:
        return self._snapshot()


def _resolve_runtime_event_source(engine: object) -> object:
    proxy = getattr(engine, "engine_core", None)
    delegate = getattr(proxy, "_delegate", None)
    core = getattr(delegate, "engine_core", None)
    candidates = (proxy, delegate, core)
    sources: list[object] = []
    for candidate in candidates:
        source = getattr(candidate, "kvopt_phase5_event_source", None)
        snapshot = getattr(source, "snapshot", None)
        installation_report = getattr(source, "installation_report", None)
        if callable(snapshot) and callable(installation_report):
            report = installation_report()
            if not isinstance(report, Mapping) or report.get("status") != "PASS":
                raise Phase5ENativeEvidenceError(
                    "same-EngineCore runtime hook installation is not verified"
                )
            if report.get("mode") != "CONTROLLED_A3" or (
                report.get("same_engine_core") is not True
            ):
                raise Phase5ENativeEvidenceError(
                    "same-EngineCore runtime hook is not controlled A3"
                )
            sources.append(source)
    if len(sources) != 1:
        raise Phase5ENativeEvidenceError(
            "exactly one same-EngineCore kvopt_phase5_event_source is required"
        )
    return sources[0]


def resolve_runtime_event_reader(engine: object) -> Callable[[], Sequence[Mapping[str, object]]]:
    """Resolve an explicitly installed same-EngineCore evidence reader."""

    snapshot = _resolve_runtime_event_source(engine).snapshot
    return snapshot


def resolve_runtime_installation_report(engine: object) -> Mapping[str, object]:
    """Copy the verified installation report from the same EngineCore source."""

    report = _resolve_runtime_event_source(engine).installation_report()
    return dict(report)


def resolve_runtime_integration(engine: object) -> object:
    """Resolve the integration bound to the verified same-core source."""

    return _resolve_runtime_event_source(engine).runtime_integration()
