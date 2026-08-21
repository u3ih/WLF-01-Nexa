"""A long answer must arrive whole.

A findings reply in Vietnamese runs to several sections and tables. When the
endpoint stops at the output cap it returns what it had so far with no error, so
the reply simply ends mid-sentence — the observed bug was an answer that stopped
at a section heading with an empty bullet under it. These tests pin the two
halves of the fix: the stop reason survives normalisation, and a truncated
narration is continued rather than returned as-is.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.llm.client import (AIClient, LLMStatus, OllamaBackend, OpenAIBackend,
                            _join_continuation)


@pytest.fixture(autouse=True)
def _model_is_up(monkeypatch):
    monkeypatch.setattr(
        AIClient, "status",
        lambda self, refresh=False: LLMStatus(
            "native_tools", "test-model", True, "ready", 0.0, "openai"),
    )
    monkeypatch.setattr(settings, "ai_narrate_tokens", 4000)
    monkeypatch.setattr(settings, "ai_continue_rounds", 2)
    yield


def _replies(monkeypatch, *turns):
    """Queue one reply per `_chat` call and record what was sent."""
    seen: list[dict] = []

    def fake_chat(self, messages, tools=None, num_predict=1200):
        seen.append({"messages": messages, "num_predict": num_predict})
        content, finish = turns[min(len(seen) - 1, len(turns) - 1)]
        return {"message": {"content": content, "tool_calls": [],
                            "finish_reason": finish}}

    monkeypatch.setattr(AIClient, "_chat", fake_chat)
    return seen


LABELS = {"recurring_confirmed": "Đã xác nhận định kỳ",
          "needs_your_confirmation": "Cần bạn tự xác nhận",
          "insufficient_data": "Không đủ dữ liệu"}


def _narrate(client: AIClient) -> str | None:
    return client.narrate("bao nhiêu?", "vi", LABELS, "get_findings",
                          {"period": {"key": "2026-08"}})


# ------------------------------------------------------------- the stop reason

def test_the_openai_stop_reason_survives_normalisation():
    reshaped = OpenAIBackend._normalise({
        "choices": [{"finish_reason": "length",
                     "message": {"content": "3. Số dư ví"}}],
    })
    assert reshaped["message"]["finish_reason"] == "length"


def test_ollamas_done_reason_is_read_as_the_stop_reason():
    reshaped = OllamaBackend._normalise({
        "message": {"content": "3. Số dư ví"}, "done_reason": "length",
    })
    assert reshaped["message"]["finish_reason"] == "length"
    assert reshaped["message"]["content"] == "3. Số dư ví"


# ----------------------------------------------------------- the continuation

def test_a_truncated_answer_is_continued_instead_of_returned_half(monkeypatch):
    seen = _replies(monkeypatch,
                    ("2. Tiền rời tài khoản.", "length"),
                    ("3. Số dư ví: $1,335.00.", "stop"))

    answer = _narrate(AIClient())

    assert answer == "2. Tiền rời tài khoản.\n\n3. Số dư ví: $1,335.00."
    assert len(seen) == 2
    # The second request shows the model its own partial answer, so it resumes
    # rather than starting over.
    assert seen[1]["messages"][-2]["role"] == "assistant"
    assert seen[1]["messages"][-2]["content"] == "2. Tiền rời tài khoản."


def test_an_answer_that_finished_is_asked_for_nothing_more(monkeypatch):
    seen = _replies(monkeypatch, ("Đủ rồi.", "stop"))
    assert _narrate(AIClient()) == "Đủ rồi."
    assert len(seen) == 1


def test_the_continuation_rounds_are_capped(monkeypatch):
    monkeypatch.setattr(settings, "ai_continue_rounds", 2)
    seen = _replies(monkeypatch, ("phần.", "length"))
    answer = _narrate(AIClient())
    # One narration plus at most two continuations, even though the endpoint
    # keeps reporting that it stopped at the cap.
    assert len(seen) == 3
    assert answer == "phần.\n\nphần.\n\nphần."


def test_continuation_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(settings, "ai_continue_rounds", 0)
    seen = _replies(monkeypatch, ("cắt giữa câu", "length"))
    assert _narrate(AIClient()) == "cắt giữa câu"
    assert len(seen) == 1


def test_the_configured_cap_is_what_the_narrator_asks_for(monkeypatch):
    monkeypatch.setattr(settings, "ai_narrate_tokens", 2500)
    seen = _replies(monkeypatch, ("xong.", "stop"))
    _narrate(AIClient())
    assert seen[0]["num_predict"] == 2500


def test_an_empty_continuation_ends_the_loop(monkeypatch):
    seen = _replies(monkeypatch, ("một nửa", "length"), ("", "length"))
    assert _narrate(AIClient()) == "một nửa"
    assert len(seen) == 2


def test_a_transport_failure_still_returns_none(monkeypatch):
    def boom(self, messages, tools=None, num_predict=1200):
        raise RuntimeError("endpoint down")

    monkeypatch.setattr(AIClient, "_chat", boom)
    assert _narrate(AIClient()) is None


# ------------------------------------------------------------------- the seam

@pytest.mark.parametrize("head, tail, expected", [
    # A finished sentence: the continuation is a new block.
    ("Mục 2 xong.", "3. Số dư ví", "Mục 2 xong.\n\n3. Số dư ví"),
    # A finished table row: same — the next row starts on its own line.
    ("| WLF15-WL-0063 | $220.59 |", "| WLF15-WL-0106 | $460.37 |",
     "| WLF15-WL-0063 | $220.59 |\n\n| WLF15-WL-0106 | $460.37 |"),
    # Cut mid-sentence: no line break may be pushed into it.
    ("Tiền rời ví nhưng", " chưa lên thẻ.", "Tiền rời ví nhưng chưa lên thẻ."),
    # Cut mid-word: the halves are one word again.
    ("Volca", "no EU", "Volcano EU"),
])
def test_the_seam_follows_where_the_cap_fell(head, tail, expected):
    assert _join_continuation(head, tail) == expected
