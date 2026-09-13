from __future__ import annotations

import pytest

from kvopt.continuum import (
    InputProvenance,
    InputSource,
    PrefillContextTokenCountRecord,
    PrefixIdentity,
    ProgramIdentity,
    RequestIdentity,
)

PROGRAM = ProgramIdentity("program-a")
REQUEST = RequestIdentity("request-a")
PREFIX = PrefixIdentity("prefix-a")


def _fact(
    *,
    program_id: ProgramIdentity = PROGRAM,
    request_id: RequestIdentity = REQUEST,
    prefix_id: PrefixIdentity = PREFIX,
    token_count: int = 128,
    provenance: InputProvenance | None = None,
) -> PrefillContextTokenCountRecord:
    return PrefillContextTokenCountRecord(
        program_id=program_id,
        request_id=request_id,
        prefix_id=prefix_id,
        token_count=token_count,
        provenance=(
            InputProvenance(InputSource.OBSERVED)
            if provenance is None
            else provenance
        ),
    )


def test_prefill_context_token_count_accepts_positive_int() -> None:
    record = _fact(token_count=128)

    assert record.token_count == 128


@pytest.mark.parametrize(
    "token_count",
    [0, -1, True, 128.0, "128"],
)
def test_prefill_context_token_count_rejects_non_positive_or_non_int(
    token_count: object,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _fact(token_count=token_count)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "provenance",
    [
        InputProvenance(InputSource.NATIVE),
        InputProvenance(InputSource.OBSERVED),
        InputProvenance(InputSource.EXTERNAL),
    ],
)
def test_prefill_context_token_count_accepts_supported_provenance(
    provenance: InputProvenance,
) -> None:
    record = _fact(provenance=provenance)

    assert record.provenance == provenance


@pytest.mark.parametrize(
    "provenance",
    [
        InputProvenance(InputSource.APPROXIMATED, "not accepted here"),
        InputProvenance(InputSource.UNAVAILABLE, "not accepted here"),
    ],
)
def test_prefill_context_token_count_rejects_unsupported_provenance(
    provenance: InputProvenance,
) -> None:
    with pytest.raises(ValueError):
        _fact(provenance=provenance)


def test_prefill_context_token_count_rejects_wrong_identity_types() -> None:
    with pytest.raises(TypeError):
        _fact(program_id=REQUEST)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        _fact(request_id=PROGRAM)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        _fact(prefix_id=PROGRAM)  # type: ignore[arg-type]
