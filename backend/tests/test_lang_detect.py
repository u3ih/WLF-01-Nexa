"""A Vietnamese question must not be answered in English.

The UI toggle used to decide the reply language on its own, so a Vietnamese
"chào bạn" typed while the UI sat on English came back in English. These tests
pin the two halves of the fix: the detector reads the message, and the toggle
only decides when the message says nothing either way.
"""

from __future__ import annotations

import pytest

from app.llm.chat import answer, resolve_lang
from app.llm.detect import detect_lang, requested_lang
from app.llm.smalltalk import SmallTalk, classify


@pytest.mark.parametrize("question", [
    "chào bạn",
    "tôi tiêu bao nhiêu tháng này",
    "kiểm tra giao dịch trùng lặp giúp mình",
    "có khoản nào cần xác nhận không",
    "toi muon xem cac goi dang ky",          # no diacritics typed
    "gói Đỏ này là gì",                      # đ carries the signal alone
])
def test_vietnamese_question_answers_in_vietnamese(question):
    assert detect_lang(question, "en") == "vi"


@pytest.mark.parametrize("question", [
    "hello",
    "what did I spend this month",
    "show me the duplicate charges",
    "which transactions need my confirmation",
    "is my café subscription still active",   # an accent is not Vietnamese
])
def test_english_question_answers_in_english(question):
    assert detect_lang(question, "vi") == "en"


@pytest.mark.parametrize("question", ["", "   ", "CRD-0173", "42", "🙂", "???"])
def test_unreadable_question_keeps_the_ui_language(question):
    assert detect_lang(question, "en") == "en"
    assert detect_lang(question, "vi") == "vi"


def test_unknown_ui_language_falls_back_to_the_default():
    assert detect_lang("CRD-0173", "fr") == "vi"


def test_reply_carries_the_detected_language_not_the_toggle():
    reply = answer("chào bạn", lang="en")
    assert reply["lang"] == "vi"
    assert reply["ui_lang"] == "en"
    # The labels travel with the answer, so they must switch with it.
    assert reply["labels"]["needs_your_confirmation"] == "Cần bạn tự xác nhận"


def test_english_question_on_a_vietnamese_ui_answers_in_english():
    reply = answer("hello", lang="vi")
    assert reply["lang"] == "en"
    assert reply["ui_lang"] == "vi"


# -- an explicit request outranks the language it is written in ------------

@pytest.mark.parametrize("question,expected", [
    ("bạn trả lời bằng tiếng Anh được không", "en"),
    ("từ giờ hãy trả lời bằng tiếng anh", "en"),
    ("nói tiếng Anh đi", "en"),
    ("dùng tiếng Anh nhé", "en"),
    ("tieng anh", "en"),
    ("answer in English please", "en"),
    ("switch to english", "en"),
    ("trả lời bằng tiếng Việt", "vi"),
    ("please answer in Vietnamese", "vi"),
    ("speak Vietnamese from now on", "vi"),
    # Both named: the one asked for first is the instruction.
    ("trả lời bằng tiếng Anh, đừng dùng tiếng Việt", "en"),
])
def test_a_language_request_is_read_from_the_wording(question, expected):
    assert requested_lang(question) == expected


@pytest.mark.parametrize("question", [
    "chào bạn",
    "tôi tiêu bao nhiêu tháng này",
    "hoá đơn này ghi tên bằng tiếng Anh và tiếng Việt",   # describes, asks not
    "what did I spend this month",
])
def test_an_ordinary_question_is_not_a_language_request(question):
    assert requested_lang(question) is None


def test_a_request_beats_the_language_it_was_typed_in():
    # Vietnamese sentence, English asked for: the instruction wins.
    reply = answer("bạn trả lời bằng tiếng Anh được không", lang="vi")
    assert reply["lang"] == "en"
    assert reply["reply_lang"] == "en"


def test_the_request_outlives_the_turn_it_was_made_in():
    # What the client hands back next turn, on a Vietnamese question.
    lang, held = resolve_lang("tháng này tôi tiêu bao nhiêu", "vi", held="en")
    assert (lang, held) == ("en", "en")
    reply = answer("tháng này tôi tiêu bao nhiêu", lang="vi", reply_lang="en")
    assert reply["lang"] == "en"
    assert reply["reply_lang"] == "en"


def test_a_new_request_replaces_the_one_being_held():
    lang, held = resolve_lang("trả lời bằng tiếng Việt", "en", held="en")
    assert (lang, held) == ("vi", "vi")


def test_nothing_is_held_until_something_is_asked_for():
    assert resolve_lang("chào bạn", "en") == ("vi", None)


def test_a_bare_language_request_is_answered_as_conversation():
    assert classify("từ giờ hãy trả lời bằng tiếng anh") is SmallTalk.LANGUAGE
    assert classify("answer in English please") is SmallTalk.LANGUAGE
    # Carrying a real question, it must still reach a tool.
    assert classify("trả lời tiếng Anh, tháng này tôi tiêu bao nhiêu") is None
