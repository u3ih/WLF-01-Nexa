"""Two gates around the model.

Before: requests to act on money, cancel a plan, lock a card or email a third
party never reach a tool — there is no such tool, and the request is answered
with what we *can* do instead.

After: any absolute reassurance, any "the bank is investigating" implication and
any unmasked card number is stripped from the reply.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from enum import Enum
from typing import Any

from ..engine.mask import has_unmasked_pan, scrub_text


class BlockedIntent(str, Enum):
    CANCEL_SUBSCRIPTION = "cancel_subscription"
    DISPUTE = "dispute"
    MONEY_MOVE = "money_move"
    CARD_LOCK = "card_lock"
    THIRD_PARTY_EMAIL = "third_party_email"
    REASSURANCE = "reassurance"


class Severity(str, Enum):
    HARD = "hard"     # refuse and offer the permitted alternative
    SOFT = "soft"     # refuse the framing, then still show the evidence


def _p(*patterns: str) -> list[re.Pattern[str]]:
    return [re.compile(p, re.I) for p in patterns]


# "Show me how" is a legitimate request; "do it for me" is not.
GUIDANCE_HINTS = _p(
    r"\b(how do i|how can i|how to|steps?|guide|instructions?)\b",
    r"(làm sao|làm thế nào|cách|hướng dẫn|các bước)",
)

INTENT_PATTERNS: dict[BlockedIntent, list[re.Pattern[str]]] = {
    BlockedIntent.THIRD_PARTY_EMAIL: _p(
        r"\b(email|write|send|contact|complain)\b.{0,30}"
        r"\b(netflix|spotify|chegg|amazon|paypal|merchant|bank|support|them|"
        r"seller|wealify support)\b",
        r"\b(send|email)\b.{0,20}\b(complaint|dispute letter)\b",
        r"(gửi|viết|soạn và gửi)\s*(email|thư|mail).{0,30}"
        r"(cho|tới|đến)\s*(netflix|spotify|chegg|amazon|paypal|cửa hàng|"
        r"ngân hàng|họ|bên|hỗ trợ)",
    ),
    BlockedIntent.CANCEL_SUBSCRIPTION: _p(
        r"\b(cancel|unsubscribe|stop|kill|end)\b.{0,30}"
        r"\b(subscription|plan|membership|netflix|spotify|chegg|it|them)\b",
        r"\b(cancel|unsubscribe)\b.{0,20}\b(for me|on my behalf)\b",
        r"(tự\s*)?(huỷ|hủy|ngưng|dừng|cắt)\b.{0,30}(gói|dịch vụ|đăng ký|thuê bao|"
        r"netflix|spotify|chegg|nó|giúp|hộ|đi)",
    ),
    BlockedIntent.DISPUTE: _p(
        r"\b(file|open|raise|start|submit)\b.{0,25}"
        r"\b(dispute|chargeback|claim|complaint)\b",
        r"\b(chargeback|dispute)\b.{0,20}\b(for me|it|this)\b",
        r"(mở|gửi|nộp|làm)\b.{0,25}(khiếu nại|tranh chấp|chargeback)",
        r"(đòi|lấy)\s*lại\s*(tiền|khoản).{0,15}(giúp|hộ|cho (tôi|mình))",
    ),
    BlockedIntent.MONEY_MOVE: _p(
        r"\b(transfer|send|move|withdraw|refund|pay)\b.{0,25}"
        r"(\$|money|funds|\d+(\.\d{2})?)\b.{0,25}\b(for me|to|now|please)\b",
        r"\b(transfer|withdraw|refund)\b.{0,15}\b(my )?(money|funds|balance)\b",
        r"(chuyển|rút|hoàn|nạp)\s*(\d[\d.,]*\s*(đô|usd|\$|k)?|tiền|khoản)?"
        r".{0,25}(giúp|hộ|cho (tôi|mình))",
        r"(chuyển|rút|hoàn)\s*(tiền|khoản)\b.{0,15}(ngay|đi)\b",
    ),
    BlockedIntent.CARD_LOCK: _p(
        r"\b(lock|freeze|block|unlock|unfreeze|activate|deactivate)\b.{0,20}"
        r"\b(card|thẻ)\b",
        r"(khoá|khóa|mở|vô hiệu|kích hoạt)\s*(thẻ|card)",
    ),
    BlockedIntent.REASSURANCE: _p(
        r"\b(is|are)\b.{0,15}\b(my )?(account|card|money)\b.{0,15}\b(safe|secure|ok|fine)\b",
        r"\b(am i|are we)\b.{0,15}\b(safe|ok|fine|secure)\b",
        r"\b(has|have)\b.{0,15}\b(i|my account)\b.{0,15}\b(been hacked|been compromised)\b",
        r"(tài khoản|thẻ|tiền)\s*(của\s*)?(tôi|mình|em)?.{0,15}"
        r"(có\s*)?(an toàn|ổn|bình thường)\s*(không|chứ|ko)",
        r"(có bị (hack|hắc|đánh cắp|lộ)|bị hack)\s*(không|ko)?",
        r"(chắc chắn|khẳng định).{0,20}(an toàn|không có gì)",
    ),
}

INTENT_SEVERITY = {
    BlockedIntent.CANCEL_SUBSCRIPTION: Severity.HARD,
    BlockedIntent.DISPUTE: Severity.HARD,
    BlockedIntent.MONEY_MOVE: Severity.HARD,
    BlockedIntent.CARD_LOCK: Severity.HARD,
    BlockedIntent.THIRD_PARTY_EMAIL: Severity.HARD,
    BlockedIntent.REASSURANCE: Severity.SOFT,
}

# Phrases the assistant is never allowed to emit.
BANNED_OUTPUT = _p(
    r"(tài khoản|thẻ)\s*(của\s*)?(bạn|anh|chị)?\s*(là\s*)?(hoàn toàn\s*)?an toàn",
    r"không có (gì|dấu hiệu|khoản nào)\s*(bất thường|đáng ngờ|lạ)",
    r"mọi thứ (đều\s*)?(ổn|bình thường)",
    r"chắc chắn (là\s*)?(gian lận|không gian lận)",
    r"\byour (account|card) is (safe|secure)\b",
    r"\b(everything|all)\s+(is|looks)\s+(fine|safe|ok)\b",
    r"\bnothing (is\s+)?(suspicious|wrong|unusual)\b",
    r"\bno (signs? of )?(fraud|suspicious activity)\b",
    r"\bdefinitely (fraud|not fraud)\b",
)

# Never imply the bank has taken action on a transaction.
BANNED_IMPLICATION = _p(
    r"(ngân hàng|wealify)\s*(đang|đã)\s*(điều tra|giữ|phong toả|phong tỏa|khoá)",
    r"(giao dịch|khoản) này (đang )?bị (giữ|treo|phong toả|điều tra)",
    r"\b(the )?bank is (investigating|holding|reviewing)\b",
    r"\b(this )?(transaction|charge) is (on hold|frozen|under investigation)\b",
)


@dataclass
class IntentVerdict:
    blocked: bool
    intent: BlockedIntent | None = None
    severity: Severity | None = None
    guidance_request: bool = False
    matched: str = ""

    @property
    def refusal_key(self) -> str | None:
        return f"refusal.{self.intent.value}" if self.intent else None


def classify_intent(text: str) -> IntentVerdict:
    guidance = any(p.search(text) for p in GUIDANCE_HINTS)
    for intent, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                return IntentVerdict(
                    blocked=True, intent=intent,
                    severity=INTENT_SEVERITY[intent],
                    guidance_request=guidance, matched=match.group(0)[:80],
                )
    return IntentVerdict(blocked=False)


@lru_cache
def _approved_phrases() -> tuple[str, ...]:
    """Our own refusal wording, which legitimately discusses safety in order to
    decline to judge it ("I cannot conclude your account is safe or not").

    These spans are blanked before pattern matching so the filter never fires
    on the very sentences it is meant to enforce.
    """
    from ..engine.render import catalog

    phrases: list[str] = []
    for lang in ("vi", "en"):
        for key, value in catalog(lang).items():
            if key.startswith("refusal.") and isinstance(value, str):
                phrases.append(value.split("{")[0].strip())
    return tuple(p for p in phrases if len(p) > 20)


def _without_approved(text: str) -> str:
    stripped = text
    for phrase in _approved_phrases():
        if phrase in stripped:
            stripped = stripped.replace(phrase, " ")
    return stripped


@dataclass
class OutputVerdict:
    text: str
    violations: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.violations


def check_output(text: str) -> OutputVerdict:
    checked = _without_approved(text)
    violations: list[str] = []
    for pattern in BANNED_OUTPUT:
        if pattern.search(checked):
            violations.append(f"absolute_reassurance:{pattern.pattern[:40]}")
    for pattern in BANNED_IMPLICATION:
        if pattern.search(checked):
            violations.append(f"bank_action_implied:{pattern.pattern[:40]}")
    if has_unmasked_pan(text):
        violations.append("unmasked_card_number")
    return OutputVerdict(text=scrub_text(text), violations=violations)


def describe(verdict: IntentVerdict) -> dict[str, Any]:
    return {
        "blocked": verdict.blocked,
        "intent": verdict.intent.value if verdict.intent else None,
        "severity": verdict.severity.value if verdict.severity else None,
        "guidance_request": verdict.guidance_request,
        "matched_phrase": verdict.matched,
    }
