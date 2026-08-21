"""Render engine findings into Vietnamese or English.

The engine produces numbers; this module produces sentences. Both languages
read from the same `params`, so VI and EN can never disagree on a figure.
"""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import BACKEND_ROOT
from .labels import deadline_info
from .mask import scrub_text
from .models import Finding, FindingKind, fmt_display, fmt_money, to_amount

I18N_DIR = BACKEND_ROOT / "app" / "i18n"
LANGS = ("vi", "en")
DEFAULT_LANG = "vi"


@lru_cache
def catalog(lang: str) -> dict[str, str]:
    lang = lang if lang in LANGS else DEFAULT_LANG
    return json.loads((I18N_DIR / f"{lang}.json").read_text())


def t(lang: str, key: str, **params: Any) -> str:
    template = catalog(lang).get(key)
    if template is None:
        return key
    try:
        return template.format(**params)
    except (KeyError, IndexError):
        return template


def normalise_lang(lang: str | None) -> str:
    if not lang:
        return DEFAULT_LANG
    lang = lang.lower()[:2]
    return lang if lang in LANGS else DEFAULT_LANG


def disclaimer(lang: str) -> str:
    return catalog(lang)["disclaimer"]


def _money_params(params: dict[str, Any], lang: str = "vi") -> dict[str, Any]:
    """Add a formatted twin for every *_cents value: amount_cents -> amount.

    A finding that names its own currency is formatted in that currency. The ₫
    twin only makes sense for a dollar figure — printing it beside an amount
    that is already in đồng, or converting a euro charge as if it were USD,
    would state a number the statement never did.
    """
    out = dict(params)
    currency = params.get("currency") or "USD"
    for key, value in params.items():
        if key.endswith("_cents") and isinstance(value, int):
            out[key[: -len("_cents")]] = fmt_display(value, lang, currency)
    return out


def reasons_text(lang: str, reasons: list[str], brand: str | None) -> str:
    rendered = [
        t(lang, f"email_reason.{code}", brand=brand or t(lang, "common.unknown"))
        for code in reasons
    ]
    return "; ".join(r for r in rendered if r and not r.startswith("email_reason."))


def render_sources(lang: str, finding: Finding) -> list[dict[str, str]]:
    out = []
    for source in finding.sources:
        out.append({
            "kind": source.kind.value,
            "kind_text": t(lang, f"source.{source.kind.value}"),
            "ref": source.ref,
            "detail": scrub_text(source.detail or ""),
        })
    return out


def render_finding(finding: Finding, lang: str, today: date) -> dict[str, Any]:
    lang = normalise_lang(lang)
    kind = finding.kind.value
    params = _money_params(finding.params, lang)

    merchant = params.get("merchant") or params.get("descriptor") \
        or t(lang, "common.unknown")
    params["merchant"] = merchant

    if "cadence" in params:
        params["cadence"] = t(lang, f"cadence.{finding.params['cadence']}")
    if finding.kind is FindingKind.DOUBLE_FEE:
        extra = finding.params["total_cents"] - finding.params["amount_cents"]
        params["amount_extra"] = fmt_display(
            extra, lang, finding.params.get("currency") or "USD")
    if finding.kind is FindingKind.SUSPICIOUS_EMAIL:
        params["claimed_brand"] = (finding.params.get("claimed_brand")
                                   or t(lang, "common.unknown"))
        params["reasons"] = reasons_text(
            lang, finding.params.get("reasons", []),
            finding.params.get("claimed_brand"),
        )

    # A duplicated credit reads differently depending on which balance it
    # landed in, so the wallet wording is used when the wallet is the ledger.
    variant = ".wallet" if params.get("ledger") == "wallet" else ""
    detail = t(lang, f"finding.{kind}{variant}.detail", **params)
    if detail.startswith(f"finding.{kind}"):
        detail = t(lang, f"finding.{kind}.detail", **params)
    if finding.kind is FindingKind.PRICE_INCREASE:
        suffix = ("finding.price_increase.notice_found"
                  if finding.params.get("notice_email_found")
                  else "finding.price_increase.notice_missing")
        detail = f"{detail} {t(lang, suffix, **params)}"
    if finding.kind is FindingKind.UNKNOWN_MERCHANT \
            and finding.params.get("processor_hint"):
        detail = f"{detail} {t(lang, 'finding.unknown_merchant.processor_line', processor=finding.params['processor_hint'])}"

    deadline = deadline_info(finding, today)
    informational = finding.kind is FindingKind.RECURRING_SUBSCRIPTION
    if deadline["dispute_deadline"] and not informational:
        if deadline["expired"]:
            deadline_text = t(
                lang, "deadline.expired",
                deadline=deadline["dispute_deadline"],
                days_over=abs(deadline["days_left"]),
                statement_date=deadline["statement_date"],
            )
        else:
            deadline_text = t(
                lang, "deadline.active",
                deadline=deadline["dispute_deadline"],
                days_left=deadline["days_left"],
                statement_date=deadline["statement_date"],
            )
    else:
        deadline_text = ""

    return {
        "id": finding.fingerprint,
        "kind": kind,
        "label": finding.label.value,
        "label_text": t(lang, f"labels.{finding.label.value}"),
        "title": scrub_text(t(lang, f"finding.{kind}.title", **params)),
        "detail": scrub_text(detail),
        "next_step": scrub_text(t(lang, f"finding.{kind}.next_step", **params)),
        "amount_cents": finding.amount_cents,
        "amount": fmt_display(finding.amount_cents, lang),
        "amount_usd_text": fmt_money(finding.amount_cents),
        "amount_number": to_amount(finding.amount_cents),
        "confidence": finding.confidence,
        "occurred_on": finding.occurred_on.isoformat() if finding.occurred_on else None,
        "txn_ids": finding.txn_ids,
        "sources": render_sources(lang, finding),
        "dispute": {**deadline, "text": deadline_text},
        "params": finding.params,
    }


def render_findings(findings: list[Finding], lang: str,
                    today: date) -> list[dict[str, Any]]:
    return [render_finding(f, lang, today) for f in findings]


def label_counts(findings: list[Finding]) -> dict[str, int]:
    counts = {"recurring_confirmed": 0, "needs_your_confirmation": 0,
              "insufficient_data": 0}
    for f in findings:
        counts[f.label.value] += 1
    return counts
