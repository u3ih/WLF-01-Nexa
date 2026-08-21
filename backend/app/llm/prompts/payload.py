"""Turning a tool result into something safe to put in a prompt.

Two jobs: hide raw cents so the model cannot quote "14369 cents" for $143.69,
and keep an oversized result inside a budget by dropping whole rows rather
than slicing the JSON in half.
"""

from __future__ import annotations

import json
from typing import Any

from ...engine.models import fmt_money

PAYLOAD_BUDGET = 12000


def humanize(value: Any) -> Any:
    """Replace every *_cents integer with a formatted money string.

    The model then has no raw cents to quote, so it cannot answer
    "14,369 cents" when the figure is $143.69.
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key.endswith("_cents") and isinstance(item, int):
                out[key[: -len("_cents")]] = fmt_money(item)
            else:
                out[key] = humanize(item)
        return out
    if isinstance(value, list):
        return [humanize(item) for item in value]
    return value


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def fit(value: Any, budget: int = PAYLOAD_BUDGET) -> str:
    """Shrink an oversized tool result by dropping *rows*, not characters.

    Cutting the string mid-object used to hand the model invalid JSON whose
    tail was simply gone — and the tail is where the short, load-bearing lists
    sit. Long lists are shortened instead, longest first, each one saying how
    many entries it dropped, so nothing silently disappears.
    """
    payload = dumps(value)
    if len(payload) <= budget or not isinstance(value, dict):
        return payload if len(payload) <= budget else payload[:budget] + "…"

    trimmed = dict(value)
    original = {k: len(v) for k, v in value.items() if isinstance(v, list)}
    while len(payload) > budget:
        lists = [(len(v), k) for k, v in trimmed.items()
                 if isinstance(v, list) and len(v) > 1]
        if not lists:
            return payload[:budget] + "…"
        size, key = max(lists)
        trimmed[key] = trimmed[key][: size // 2]
        trimmed[f"{key}_omitted"] = original[key] - len(trimmed[key])
        payload = dumps(trimmed)
    return payload
