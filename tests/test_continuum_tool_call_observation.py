from __future__ import annotations

import pytest

from kvopt.continuum import InputSource
from kvopt.runtime.vllm.tool_call_observation import next_tool_type_from_request


class _FakeTokenizer:
    def __init__(
        self, text: str | None = None, failure: Exception | None = None
    ) -> None:
        self._text = text
        self._failure = failure
        self.decode_calls: list[list[int]] = []

    def decode(self, token_ids, *, skip_special_tokens: bool = True) -> str:
        assert skip_special_tokens is True
        if self._failure is not None:
            raise self._failure
        self.decode_calls.append(list(token_ids))
        assert self._text is not None
        return self._text


class _FakeRequest:
    def __init__(self, output_token_ids) -> None:
        self.output_token_ids = output_token_ids


_BASH_OUTPUT = "Let me check.\n```bash\ngit status\n```"


def test_adapter_returns_observed_tool_type() -> None:
    request = _FakeRequest([10, 11, 12])
    tokenizer = _FakeTokenizer(_BASH_OUTPUT)
    tool_type, provenance = next_tool_type_from_request(request, tokenizer)
    assert tool_type == "git"
    assert provenance.source is InputSource.OBSERVED
    assert tokenizer.decode_calls == [[10, 11, 12]]


def test_adapter_reports_unavailable_without_output_tokens() -> None:
    request = _FakeRequest([])
    tool_type, provenance = next_tool_type_from_request(
        request, _FakeTokenizer(_BASH_OUTPUT)
    )
    assert tool_type is None
    assert provenance.source is InputSource.UNAVAILABLE
    assert provenance.reason == "request exposes no output tokens"


def test_adapter_reports_unavailable_when_request_lacks_attribute() -> None:
    class _Bare:
        pass

    tool_type, provenance = next_tool_type_from_request(
        _Bare(), _FakeTokenizer(_BASH_OUTPUT)
    )
    assert tool_type is None
    assert provenance.source is InputSource.UNAVAILABLE


def test_adapter_propagates_tokenizer_failures() -> None:
    request = _FakeRequest([1])
    tokenizer = _FakeTokenizer(failure=RuntimeError("detokenize failed"))
    with pytest.raises(RuntimeError, match="detokenize failed"):
        next_tool_type_from_request(request, tokenizer)


def test_adapter_reports_unavailable_without_tool_call() -> None:
    request = _FakeRequest([1])
    tool_type, provenance = next_tool_type_from_request(
        request, _FakeTokenizer("plain text answer")
    )
    assert tool_type is None
    assert provenance.source is InputSource.UNAVAILABLE
    assert provenance.reason == "no tool call parsed from request output"


def test_adapter_requires_tokenizer_with_decode() -> None:
    request = _FakeRequest([1])
    with pytest.raises(TypeError):
        next_tool_type_from_request(request, object())
    with pytest.raises(TypeError):
        next_tool_type_from_request(request, None)


def test_adapter_requires_sequence_output_tokens() -> None:
    request = _FakeRequest("not a sequence")
    with pytest.raises(TypeError):
        next_tool_type_from_request(request, _FakeTokenizer(_BASH_OUTPUT))
