"""Greetings, thanks and "who are you" — conversation, not a data question.

The keyword router has to fall back to *some* tool, and that fallback is
`get_overview`. A bare "hello" therefore used to return the full statement
summary. These patterns catch the conversational openers first, so the
assistant answers them the way a person would and waits to be asked something.
"""

from __future__ import annotations

import re
from enum import Enum


class SmallTalk(str, Enum):
    GREETING = "greeting"
    THANKS = "thanks"
    FAREWELL = "farewell"
    IDENTITY = "identity"


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


def classify(question: str) -> SmallTalk | None:
    """The small-talk kind, or None when this is a real question."""
    text = (question or "").strip()
    if not text or len(text) > MAX_CHARS:
        return None
    for kind, pattern in PATTERNS:
        if pattern.match(text):
            return kind
    return None
