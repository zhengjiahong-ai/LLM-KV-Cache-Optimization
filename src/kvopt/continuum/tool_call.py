"""Server-side tool-call parsing for the Continuum baseline.

This mirrors the source ``vllm-continuum`` ``ToolCallParser``: the tool
identity of a finished non-terminal turn is derived from the model output
itself (a single bash code block), so the baseline does not depend on
orchestrator-supplied tool identity. Orchestrator-provided tool events
remain the preferred external input; this parser is the fallback that
keeps the original mechanism self-contained inside the serving process.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence

from .types import InputProvenance, InputSource

_TOOL_CALL_PATTERN = re.compile(r"```bash\s*\n(.*?)\n```", re.DOTALL)


class ToolCallParser:
    """Extract the invoked tool name from one finished request output."""

    def parse(self, text: str) -> str | None:
        """Return the first word of the single bash action, or None.

        Follows the source implementation: only an output containing exactly
        one bash code block yields a tool identity; the first word of that
        action is the tool name (e.g. "ls", "cd", "git").
        """
        if not isinstance(text, str):
            raise TypeError("text must be str")
        actions = _TOOL_CALL_PATTERN.findall(text)
        if len(actions) != 1:
            return None
        bash_action = actions[0].strip()
        words = bash_action.split()
        if not words:
            return None
        return words[0]


def derive_next_tool_type(
    output_token_ids: Sequence[int],
    decode: Callable[[Sequence[int]], str],
) -> tuple[str | None, InputProvenance]:
    """Derive the next tool identity from one finished request's output.

    ``decode`` receives the output token IDs and must return the decoded
    output text; decoding failures propagate to the caller instead of
    being swallowed. Returns the parsed tool name classified as OBSERVED,
    or None with an UNAVAILABLE provenance explaining why no identity
    could be derived (no output, non-text decode result, or no parsable
    tool call).
    """
    if isinstance(output_token_ids, (str, bytes)) or not isinstance(
        output_token_ids, Sequence
    ):
        raise TypeError("output_token_ids must be a sequence of token IDs")
    if not callable(decode):
        raise TypeError("decode must be callable")
    if len(output_token_ids) == 0:
        return None, InputProvenance(
            InputSource.UNAVAILABLE, "request produced no output tokens"
        )
    output_text = decode(output_token_ids)
    if not isinstance(output_text, str):
        return None, InputProvenance(
            InputSource.UNAVAILABLE, "decode must return str"
        )
    tool_type = ToolCallParser().parse(output_text)
    if tool_type is None:
        return None, InputProvenance(
            InputSource.UNAVAILABLE, "no tool call parsed from request output"
        )
    return tool_type, InputProvenance(
        InputSource.OBSERVED, "parsed from request output"
    )


__all__ = ["ToolCallParser", "derive_next_tool_type"]
