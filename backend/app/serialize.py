"""API boundary formatting.

Internally money is integer cents so totals stay exact. On the way out we
publish a number plus a localized display string, and the raw cents field is
dropped.

Money is formatted in the currency the block it sits in names. A report holds
figures in more than one currency — the euro rows folded into a total are
published beside it in euro — and formatting all of them as dollars printed
€57.54 as "$57.54", then converted that to đồng at the dollar rate. Two wrong
numbers from one assumption. A dict that carries `currency` sets it for its own
amounts and for the dicts nested inside it, which is how a conversion result
states the reporting currency while the row it belongs to states the original.
"""

from __future__ import annotations

from typing import Any

from .engine.models import fmt_display, fmt_money

SUFFIX = "_cents"
DEFAULT_CURRENCY = "USD"


def to_dollars(value: Any, lang: str = "vi",
               currency: str = DEFAULT_CURRENCY) -> Any:
    if isinstance(value, dict):
        named = value.get("currency")
        if isinstance(named, str) and named:
            currency = named
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key.endswith(SUFFIX) and isinstance(item, int):
                base = key[: -len(SUFFIX)]
                out.setdefault(base, fmt_display(item, lang, currency))
                if currency == DEFAULT_CURRENCY:
                    out[f"{base}_usd"] = round(item / 100, 2)
                    out[f"{base}_usd_text"] = fmt_money(item, currency)
                else:
                    # Not `_usd`: this figure is €57.54, and a field named for
                    # dollars holding euros misleads exactly as much as the
                    # wrong symbol did.
                    out[f"{base}_amount"] = round(item / 100, 2)
                    out[f"{base}_text"] = fmt_money(item, currency)
            else:
                out[key] = to_dollars(item, lang, currency)
        return out
    if isinstance(value, list):
        return [to_dollars(item, lang, currency) for item in value]
    return value
