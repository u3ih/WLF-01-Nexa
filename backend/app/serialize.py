"""API boundary formatting.

Internally money is integer cents so totals stay exact. On the way out we
publish dollars: every `x_cents` becomes `x_usd` (a number) plus a localized
display string, and the raw cents field is dropped.
"""

from __future__ import annotations

from typing import Any

from .engine.models import fmt_display, fmt_money

SUFFIX = "_cents"


def to_dollars(value: Any, lang: str = "vi") -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key.endswith(SUFFIX) and isinstance(item, int):
                base = key[: -len(SUFFIX)]
                out[f"{base}_usd"] = round(item / 100, 2)
                out.setdefault(base, fmt_display(item, lang))
                out[f"{base}_usd_text"] = fmt_money(item)
            else:
                out[key] = to_dollars(item, lang)
        return out
    if isinstance(value, list):
        return [to_dollars(item, lang) for item in value]
    return value
