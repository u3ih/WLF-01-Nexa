"""A greeting must not be answered with the whole statement.

Routing is meaning-first: the model decides whether a message needs statement
data, and answering with no tool is a valid outcome. The phrase list here is
only the offline fallback, so it is tested as a fallback — narrow on purpose,
and never the thing that decides when a model is up.
"""

from __future__ import annotations

import os

import pytest

from app.llm import chat
from app.llm.client import CHAT_ONLY, client, keyword_route
from app.llm.smalltalk import SmallTalk, classify

@pytest.fixture
def enable_llm():
    """The suite runs offline by default; the model path opts back in."""
    from app.config import settings

    settings.offline_mode = False
    client.status(refresh=True)
    yield client.status(refresh=True).available
    settings.offline_mode = True
    client.status(refresh=True)


needs_model = pytest.mark.skipif(
    os.environ.get("NEXA_TEST_LLM") != "1",
    reason="set NEXA_TEST_LLM=1 (and run the model) to exercise the model path",
)


# -- offline fallback ------------------------------------------------------

@pytest.mark.parametrize("question,expected", [
    ("hello bạn", SmallTalk.GREETING),
    ("hi", SmallTalk.GREETING),
    ("Xin chào!", SmallTalk.GREETING),
    ("good morning", SmallTalk.GREETING),
    ("cảm ơn bạn", SmallTalk.THANKS),
    ("thanks", SmallTalk.THANKS),
    ("bye", SmallTalk.FAREWELL),
    ("bạn là ai?", SmallTalk.IDENTITY),
    ("what can you do", SmallTalk.IDENTITY),
])
def test_bare_openers_recognised_without_a_model(question: str,
                                                 expected: SmallTalk) -> None:
    assert classify(question) is expected


@pytest.mark.parametrize("question", [
    "tổng tôi có bao nhiêu tiền",
    "chào bạn, tôi tiêu bao nhiêu tháng này",       # opener + real question
    "hi, which subscriptions do I have?",
    "có khoản nào bị trừ hai lần không",
    "",
])
def test_real_questions_are_never_small_talk(question: str) -> None:
    assert classify(question) is None
    assert keyword_route(question).name != CHAT_ONLY


# -- model path ------------------------------------------------------------

@needs_model
@pytest.mark.parametrize("question,lang", [
    ("hello bạn", "vi"),
    ("chào bạn nhé", "vi"),          # phrasing the fallback list does not carry
    ("ê chào buổi sáng nha", "vi"),
    ("cậu tên gì thế", "vi"),
    ("thanks a lot mate", "en"),
    ("hey there, how's it going?", "en"),
])
def test_model_answers_chit_chat_without_a_tool(question: str, lang: str,
                                                enable_llm) -> None:
    if not enable_llm:
        pytest.skip("no model reachable")
    reply = chat.answer(question, lang)
    assert reply["tool"] is None, reply["answer"][:120]
    assert reply["tools_used"] == []
    assert reply["smalltalk"] is True
    # Nothing was read, so no figure or reference may appear.
    for token in ("₫", "$", "ACC-", "CRD-"):
        assert token not in reply["answer"].upper()


@needs_model
@pytest.mark.parametrize("question,lang", [
    ("tổng tôi có bao nhiêu tiền", "vi"),
    ("chào bạn, tháng này tôi tiêu bao nhiêu?", "vi"),
    ("hi! which subscriptions do I have?", "en"),
])
def test_model_still_routes_real_questions_to_a_tool(question: str, lang: str,
                                                     enable_llm) -> None:
    if not enable_llm:
        pytest.skip("no model reachable")
    reply = chat.answer(question, lang)
    assert reply["tool"] is not None
    assert reply.get("smalltalk") is not True


@needs_model
def test_chit_chat_replies_differ_by_message(enable_llm) -> None:
    """Not a fixed line per bucket — the reply answers what was said."""
    if not enable_llm:
        pytest.skip("no model reachable")
    first = chat.answer("chào bạn nhé", "vi")["answer"]
    second = chat.answer("cậu làm được những gì?", "vi")["answer"]
    assert first != second


# -- offline end to end ----------------------------------------------------

def test_greeting_needs_no_tool_when_the_model_is_down(monkeypatch) -> None:
    monkeypatch.setattr(client, "chat_smalltalk", lambda *a, **k: None)
    monkeypatch.setattr(type(client), "status",
                        lambda self, refresh=False: _down())
    reply = chat.answer("hello bạn", "vi")
    assert reply["tool"] is None
    assert reply["smalltalk"] is True
    assert reply["source"] == "llm_unavailable"
    assert "$" not in reply["answer"]


def _down():
    from app.llm.client import LLMStatus
    return LLMStatus("offline", "test", False, "model down for this test", 0.0)
