"""Read-only vLLM tool-call observation adapter.

The module deliberately imports no vLLM package. It reads the pinned
observation surface of one finished native request (``output_token_ids``)
through a supplied tokenizer and derives the Continuum next-tool identity
from the model output, mirroring the source ``ToolCallEstimator`` output
parsing path.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from kvopt.continuum.tool_call import derive_next_tool_type
from kvopt.continuum.types import InputProvenance, InputSource


class _TokenizerLike(Protocol):
    """Minimal decode boundary of a native tokenizer."""

    def decode(
        self, token_ids: Sequence[int], *, skip_special_tokens: bool = ...
    ) -> str:
        ...


def _read_output_token_ids(request: object) -> Sequence[int] | None:
    output_token_ids = getattr(request, "output_token_ids", None)
    if output_token_ids is None:
        return None
    if isinstance(output_token_ids, (str, bytes)) or not isinstance(
        output_token_ids, Sequence
    ):
        raise TypeError("request.output_token_ids must be a sequence of token IDs")
    return output_token_ids


def next_tool_type_from_request(
    request: object,
    tokenizer: _TokenizerLike,
) -> tuple[str | None, InputProvenance]:
    """Derive the next tool identity from one finished native request.

    Returns the OBSERVED tool name parsed from the decoded request output,
    or None with an UNAVAILABLE provenance when the request exposes no
    output tokens. Tokenizer failures propagate to the caller rather than
    being swallowed, so the integration driver decides how to report them.
    """
    if tokenizer is None or not callable(getattr(tokenizer, "decode", None)):
        raise TypeError("tokenizer must provide decode")
    output_token_ids = _read_output_token_ids(request)
    if output_token_ids is None or len(output_token_ids) == 0:
        return None, InputProvenance(
            InputSource.UNAVAILABLE,
            "request exposes no output tokens",
        )

    def decode(token_ids: Sequence[int]) -> str:
        return tokenizer.decode(token_ids, skip_special_tokens=True)

    return derive_next_tool_type(output_token_ids, decode)


__all__ = ["next_tool_type_from_request"]
