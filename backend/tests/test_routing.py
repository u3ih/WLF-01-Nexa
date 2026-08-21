"""Routing: the model decides, the keyword table is the offline floor.

The bug these tests pin: "chi tiêu ... trong tháng 7" matched the report
keyword, so the model was never asked, and "tháng 7" — a period no pattern
carried — was dropped. The report then covered the latest month and the answer
said July was missing from a dataset that holds it.

Two things therefore have to hold. The model is asked first, even when a keyword
matches; and whatever tier answers, a period the user named survives into the
tool arguments.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.llm import summarize
from app.llm.client import (CHAT_ONLY, LLMStatus, ToolCall, client,
                            extract_args, keyword_route, period_from_text,
                            valid_period_key)
from app.llm.tools import data_coverage, run_tool

YEAR = 2026

# The system prompt interpolates all three, so a stub that omits one fails
# inside the prompt rather than in the routing under test.
LABELS = {"recurring_confirmed": "recurring",
          "needs_your_confirmation": "needs confirmation",
          "insufficient_data": "insufficient data"}


# -- reading a period out of the wording ----------------------------------

@pytest.mark.parametrize("question,expected", [
    # The question from the bug report, verbatim.
    ("Đọc & phân loại sao kê tài khoản: tách rõ các dòng tiền (tiền vào, "
     "tiền ra, chuyển sang thẻ, phí, chi tiêu). trong tháng 7",
     ("month", "2026-07")),
    ("trong tháng 7", ("month", "2026-07")),
    ("chi tiêu tháng 2 thế nào", ("month", "2026-02")),
    ("tháng 7/2026", ("month", "2026-07")),
    ("T7", ("month", "2026-07")),
    ("tháng 12 năm 2025", ("month", "2025-12")),
    ("2026-07", ("month", "2026-07")),
    ("how much did I spend in July", ("month", "2026-07")),
    ("spending for march", ("month", "2026-03")),
    ("may 2026", ("month", "2026-05")),
    ("in may", ("month", "2026-05")),
    ("quý 2", ("quarter", "2026-Q2")),
    ("Q3 2026", ("quarter", "2026-Q3")),
    ("2026-Q1", ("quarter", "2026-Q1")),
    ("cả năm nay", ("year", "2026")),
    ("2025", ("year", "2025")),
    # No period named: the tool's own default answers, not a guess made here.
    ("tôi tiêu bao nhiêu tháng này", ("month", None)),
    ("this month", ("month", None)),
    ("có khoản nào bị trừ hai lần không", ("month", None)),
    # "may" is the English verb far more often than the month.
    ("may I ask what this charge is", ("month", None)),
    ("", ("month", None)),
])
def test_period_read_from_the_wording(question: str,
                                      expected: tuple[str, str | None]) -> None:
    assert period_from_text(question, YEAR) == expected


def test_a_named_month_reaches_the_tool_arguments() -> None:
    args = extract_args("chi tiêu trong tháng 7")
    assert args["key"] == f"{data_coverage()['latest_month'][:4]}-07"
    assert args["period"] == "month"


def test_a_listing_question_gets_the_period_as_a_date_range() -> None:
    """The report tool takes a key; the search tool takes two dates."""
    call = keyword_route("liệt kê giao dịch trong tháng 7")
    year = data_coverage()["latest_month"][:4]
    assert call.name == "search_transactions"
    assert call.args["date_from"] == f"{year}-07-01"
    assert call.args["date_to"] == f"{year}-07-31"


@pytest.mark.parametrize("key,ok", [
    ("2026-07", True), ("2026-Q3", True), ("2026", True),
    ("07", False), ("July", False), ("2026-13", False), ("", False),
])
def test_only_keys_the_engine_can_parse_survive(key: str, ok: bool) -> None:
    assert valid_period_key(key) is ok


# -- the model is asked first ---------------------------------------------

REPORT_QUESTION = "chi tiêu của tôi trong tháng 7 thế nào"


@pytest.fixture
def model_up(monkeypatch):
    """A reachable model with native tool calling, and no network."""
    def _up(self, refresh: bool = False) -> LLMStatus:
        return LLMStatus("native_tools", "test-model", True, "stubbed", 0.0,
                         "openai")

    monkeypatch.setattr(type(client), "status", _up)
    return monkeypatch


def _tool_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"message": {"tool_calls": [{"function": {"name": name,
                                                     "arguments": args}}]}}


def test_the_model_routes_even_when_a_keyword_matches(model_up) -> None:
    """The keyword table would have taken this one on its own."""
    assert keyword_route(REPORT_QUESTION).name == "get_report"

    seen: list[Any] = []

    def _chat(self, messages, tools=None, num_predict=1200):
        seen.append(messages)
        return _tool_call("get_report", {"period": "month", "key": "2026-07"})

    model_up.setattr(type(client), "_chat", _chat)
    call = client.route(REPORT_QUESTION, "vi", LABELS)
    assert seen, "the model was not asked"
    assert call.chosen_by == "native_tools"
    assert call.args["key"] == "2026-07"


def test_the_question_fills_a_period_the_model_left_out(model_up) -> None:
    model_up.setattr(type(client), "_chat",
                     lambda self, m, tools=None, num_predict=1200:
                     _tool_call("get_report", {"period": "month"}))
    call = client.route(REPORT_QUESTION, "vi", LABELS)
    assert call.args["key"] == f"{data_coverage()['latest_month'][:4]}-07"


def test_an_unparseable_key_from_the_model_is_replaced(model_up) -> None:
    """A key the engine cannot read would silently become the latest month."""
    model_up.setattr(type(client), "_chat",
                     lambda self, m, tools=None, num_predict=1200:
                     _tool_call("get_report", {"period": "month", "key": "July"}))
    call = client.route(REPORT_QUESTION, "vi", LABELS)
    assert call.args["key"] == f"{data_coverage()['latest_month'][:4]}-07"


def test_a_data_question_is_never_answered_as_chit_chat(model_up) -> None:
    """The model calling no tool does not turn a report question into small talk."""
    model_up.setattr(type(client), "_chat",
                     lambda self, m, tools=None, num_predict=1200:
                     {"message": {"content": "hello there"}})
    call = client.route(REPORT_QUESTION, "vi", LABELS)
    assert call.name == "get_report"
    assert call.args["key"] == f"{data_coverage()['latest_month'][:4]}-07"


def test_no_tool_and_no_keyword_opinion_is_chit_chat(model_up) -> None:
    model_up.setattr(type(client), "_chat",
                     lambda self, m, tools=None, num_predict=1200:
                     {"message": {"tool_calls": []}})
    assert client.route("chào bạn nhé", "vi", LABELS).name == CHAT_ONLY


def test_a_model_error_falls_back_to_the_keyword_table(model_up) -> None:
    def _boom(self, messages, tools=None, num_predict=1200):
        raise RuntimeError("endpoint down mid-request")

    model_up.setattr(type(client), "_chat", _boom)
    call = client.route(REPORT_QUESTION, "vi", LABELS)
    assert call == ToolCall("get_report",
                           {"period": "month",
                            "key": f"{data_coverage()['latest_month'][:4]}-07"},
                           "keyword")


def test_the_offline_tier_still_carries_the_period(monkeypatch) -> None:
    monkeypatch.setattr(type(client), "status",
                        lambda self, refresh=False:
                        LLMStatus("offline", "none", False, "offline", 0.0))
    call = client.route(REPORT_QUESTION, "vi", LABELS)
    assert call.chosen_by == "keyword"
    assert call.args["key"] == f"{data_coverage()['latest_month'][:4]}-07"


# -- a period the data does not hold --------------------------------------

def test_a_month_inside_the_data_reports_itself() -> None:
    cover = data_coverage()
    report = run_tool("get_report", {"period": "month",
                                     "key": cover["months"][-1]}, "vi")
    assert report["period"]["key"] == cover["months"][-1]
    assert report["coverage"]["has_data"] is True


@pytest.mark.parametrize("lang", ["vi", "en"])
def test_a_month_outside_the_data_says_so_instead_of_zero(lang: str) -> None:
    cover = data_coverage()
    year, month = cover["months"][0].split("-")
    before = (f"{int(year) - 1}-12" if month == "01"
              else f"{year}-{int(month) - 1:02d}")
    report = run_tool("get_report", {"period": "month", "key": before}, lang)

    assert report["coverage"]["has_data"] is False
    assert report["totals"]["spend_cents"] == 0
    # The caveat sits above the zeros, not after them.
    text = summarize.summarize("get_report", report, lang)
    head, caveat = text.splitlines()[0], text.splitlines()[1]
    assert before in head
    assert cover["first_day"] in caveat and cover["last_day"] in caveat


def test_coverage_months_span_the_export() -> None:
    cover = data_coverage()
    assert cover["months"][0] == cover["first_day"][:7]
    assert cover["months"][-1] == cover["last_day"][:7] == cover["latest_month"]
