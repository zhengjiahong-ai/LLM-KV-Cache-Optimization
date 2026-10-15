from __future__ import annotations

import pytest

from kvopt.continuum import (
    InputSource,
    ProgramIdentity,
    RequestIdentity,
    ToolCallParser,
    derive_next_tool_type,
)


def _single_action_output() -> str:
    return (
        "I will inspect the repository first.\n"
        "```bash\n"
        "git log --oneline -5\n"
        "```\n"
    )


def test_parser_extracts_first_word_of_single_bash_block() -> None:
    assert ToolCallParser().parse(_single_action_output()) == "git"


def test_parser_extracts_first_word_of_multiline_action() -> None:
    text = "```bash\ncd /tmp && ls -la\n```"
    assert ToolCallParser().parse(text) == "cd"


def test_parser_returns_none_for_multiple_bash_blocks() -> None:
    text = "```bash\nls\n```\n```bash\ncd ..\n```"
    assert ToolCallParser().parse(text) is None


def test_parser_returns_none_when_no_bash_block() -> None:
    assert ToolCallParser().parse("plain answer, no tool call") is None


def test_parser_returns_none_for_empty_text() -> None:
    assert ToolCallParser().parse("") is None


def test_parser_returns_none_for_empty_action_body() -> None:
    assert ToolCallParser().parse("```bash\n\n```") is None


def test_parser_ignores_non_bash_code_blocks() -> None:
    assert ToolCallParser().parse("```python\nprint(1)\n```") is None


def test_parser_requires_str_input() -> None:
    with pytest.raises(TypeError):
        ToolCallParser().parse(b"not text")  # type: ignore[arg-type]


def test_derive_returns_observed_tool_type() -> None:
    def decode(token_ids):
        assert token_ids == [1, 2, 3]
        return _single_action_output()

    tool_type, provenance = derive_next_tool_type([1, 2, 3], decode)
    assert tool_type == "git"
    assert provenance.source is InputSource.OBSERVED


def test_derive_reports_unavailable_for_empty_output() -> None:
    tool_type, provenance = derive_next_tool_type([], lambda ids: "")
    assert tool_type is None
    assert provenance.source is InputSource.UNAVAILABLE
    assert provenance.reason == "request produced no output tokens"


def test_derive_propagates_decode_failures() -> None:
    def failing_decode(token_ids):
        raise RuntimeError("tokenizer failure")

    with pytest.raises(RuntimeError, match="tokenizer failure"):
        derive_next_tool_type([1], failing_decode)


def test_derive_reports_unavailable_when_decode_returns_non_str() -> None:
    tool_type, provenance = derive_next_tool_type([1], lambda ids: 123)
    assert tool_type is None
    assert provenance.source is InputSource.UNAVAILABLE
    assert provenance.reason == "decode must return str"


def test_derive_reports_unavailable_without_tool_call() -> None:
    tool_type, provenance = derive_next_tool_type(
        [1], lambda ids: "no tool call here"
    )
    assert tool_type is None
    assert provenance.source is InputSource.UNAVAILABLE
    assert provenance.reason == "no tool call parsed from request output"


def test_derive_requires_sequence_and_callable() -> None:
    with pytest.raises(TypeError):
        derive_next_tool_type("not a sequence", lambda ids: "")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        derive_next_tool_type([1], "not callable")  # type: ignore[arg-type]


def test_parser_feeds_turn_finished_next_tool_type_contract() -> None:
    from kvopt.continuum import TurnFinished

    def decode(token_ids):
        return _single_action_output()

    tool_type, _provenance = derive_next_tool_type([1, 2, 3], decode)
    assert tool_type is not None
    event = TurnFinished(
        program_id=ProgramIdentity("program-1"),
        request_id=RequestIdentity("request-1"),
        finish_timestamp=1.0,
        is_terminal=False,
        next_tool_type=tool_type,
    )
    assert event.next_tool_type == "git"
