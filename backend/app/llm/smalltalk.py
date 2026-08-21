"""Greetings, thanks and "who are you" — conversation, not a data question.

The keyword router has to fall back to *some* tool, and that fallback is
`get_overview`. A bare "hello" therefore used to return the full statement
summary. These patterns catch the conversational openers first, so the
assistant answers them the way a person would and waits to be asked something.
"""

from __future__ import annotations

import re
from enum import Enum

from .detect import requested_lang


class SmallTalk(str, Enum):
    GREETING = "greeting"
    THANKS = "thanks"
    FAREWELL = "farewell"
    IDENTITY = "identity"
    LANGUAGE = "language"


# Anchored and length-capped on purpose: "chào bạn, tôi tiêu bao nhiêu tháng
# này" is a data question with a polite opener, and must still route to a tool.
PATTERNS: list[tuple[SmallTalk, re.Pattern[str]]] = [
    (SmallTalk.IDENTITY, re.compile(
        r"^\s*(bạn|mày|em|cậu)?\s*(là ai|tên (là )?gì|làm được gì|giúp được gì|"
        r"có thể làm gì)\s*[?.!]*\s*$|"
        r"^\s*(who are you|what are you|what can you do|what do you do)"
        r"\s*[?.!]*\s*$", re.I)),
    (SmallTalk.THANKS, re.compile(
        r"^\s*(cảm ơn|cám ơn|thanks?|thank you|thx|ty|ok(ay)? (thanks?|cảm ơn))"
        r"[\s,!.]*(bạn|nhé|nha|nhiều|you)?\s*[?.!]*\s*$", re.I)),
    (SmallTalk.FAREWELL, re.compile(
        r"^\s*(tạm biệt|bye|goodbye|see you|chào tạm biệt|bai)"
        r"[\s,!.]*(bạn|nhé|nha)?\s*[?.!]*\s*$", re.I)),
    (SmallTalk.GREETING, re.compile(
        r"^\s*(hi|hello|hey|yo|chào|xin chào|alo|halo|hế lô|helo)"
        r"[\s,!.]*(bạn|em|cậu|mọi người|there|you)?[\s,!.]*"
        r"(buổi sáng|buổi chiều|buổi tối)?\s*[?.!]*\s*$", re.I)),
    (SmallTalk.GREETING, re.compile(
        r"^\s*(good\s*(morning|afternoon|evening)|khoẻ không|khỏe không|"
        r"how are you|dạo này (thế nào|sao rồi))[\s,!.]*(bạn|you)?\s*[?.!]*\s*$",
        re.I)),
]

MAX_CHARS = 40
# "Từ giờ hãy trả lời bằng tiếng Anh nhé" asks for nothing but a language, and
# it does not fit in 40 characters. It gets its own cap so a language request
# carrying a real question — "trả lời tiếng Anh, tháng này tôi tiêu bao nhiêu"
# — still routes to a tool rather than being answered as chit-chat.
LANG_MAX_CHARS = 70

# Words that mean the message is asking for statement data as well as a
# language, so it must not be treated as pure conversation.
DATA_WORDS = re.compile(
    r"(bao nhiêu|tiêu|chi|giao dịch|khoản|gói|đăng ký|phí|hoá đơn|hóa đơn|"
    r"sao kê|tổng|thẻ|tài khoản|email|thư|tháng|tuần|how much|spend|spent|"
    r"transaction|charge|subscription|fee|invoice|statement|total|card|"
    r"account|month|week|show|list)", re.I)


def classify(question: str) -> SmallTalk | None:
    """The small-talk kind, or None when this is a real question."""
    text = (question or "").strip()
    if not text:
        return None
    if (len(text) <= LANG_MAX_CHARS and requested_lang(text)
            and not DATA_WORDS.search(text)):
        return SmallTalk.LANGUAGE
    if len(text) > MAX_CHARS:
        return None
    for kind, pattern in PATTERNS:
        if pattern.match(text):
            return kind
    return None
