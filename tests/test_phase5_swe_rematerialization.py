from __future__ import annotations

import hashlib

from kvopt.workload.phase5_swe_rematerialization import rematerialize_trace


class _Tokenizer:
    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        assert tokenize is False
        assert add_generation_prompt is True
        assert messages == [{"role": "user", "content": "hello"}]
        return "rendered"

    def __call__(self, rendered, *, add_special_tokens):
        assert rendered == "rendered"
        assert add_special_tokens is False
        return {"input_ids": [1, 2, 3]}


def test_rematerialize_trace_uses_frozen_normalized_messages() -> None:
    rows = rematerialize_trace(
        normalized_trace={
            "turns": [
                {
                    "request_id": "request-1",
                    "messages": [
                        {
                            "role": "user",
                            "content": {"content": "hello"},
                        }
                    ],
                }
            ]
        },
        tokenizer=_Tokenizer(),
        model_revision="model-revision",
        tokenizer_revision="tokenizer-revision",
        chat_template_sha256="c" * 64,
    )
    assert rows[0].token_ids == (1, 2, 3)
    assert rows[0].rendered_prompt_sha256 == hashlib.sha256(b"rendered").hexdigest()
