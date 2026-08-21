"""Masking helpers. Applied at every boundary (API, logs, LLM prompts) so a
full card or account number never leaves the engine.

WLF-01 rule A: card -> last 4 only; account -> masked; CVV is never stored
anywhere (no model has a field for it).
"""

from __future__ import annotations

import re

DIGITS = re.compile(r"\d")
LONG_DIGIT_RUN = re.compile(r"(?<!\d)\d(?:[ -]?\d){11,18}(?!\d)")


def mask_card(card_number: str | None) -> str:
    if not card_number:
        return "•••• ????"
    digits = "".join(DIGITS.findall(card_number))
    if len(digits) < 4:
        return "•••• ????"
    return f"•••• {digits[-4:]}"


def last4(card_number: str | None) -> str:
    digits = "".join(DIGITS.findall(card_number or ""))
    return digits[-4:] if len(digits) >= 4 else "????"


def mask_account(account_number: str | None) -> str:
    if not account_number:
        return "•••••????"
    digits = "".join(DIGITS.findall(account_number))
    if len(digits) < 4:
        return "•••••????"
    return f"••••••{digits[-4:]}"


def scrub_text(text: str) -> str:
    """Last-resort net: replace any 12-19 digit run in free text with a mask.

    Catches an unmasked PAN that slipped into a description or an LLM answer.
    """
    def _repl(match: re.Match[str]) -> str:
        digits = "".join(DIGITS.findall(match.group(0)))
        return f"•••• {digits[-4:]}"

    return LONG_DIGIT_RUN.sub(_repl, text)


def has_unmasked_pan(text: str) -> bool:
    return bool(LONG_DIGIT_RUN.search(text))
