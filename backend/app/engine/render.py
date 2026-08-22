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
from .models import (Finding, FindingKind, fmt_display, fmt_money, fx_note,
                     to_amount)

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


def fx_block(lang: str) -> dict[str, Any]:
    """The ₫ basis, as both machine fields and the sentence shown to a reader.

    Built in one place because the note and the fields it describes have to
    agree: an answer that prints a fetched rate under a sentence claiming a
    configured one is worse than either alone.
    """
    note = fx_note(lang)
    key = "fx.note" if note["published"] else "fx.note_configured"
    # Grouped the way the language groups thousands. Every other ₫ figure on
    # screen goes through `fmt_vnd`, which uses dots; a note that wrote the
    # rate as "26,039" beside amounts written "519.000" would read as a
    # different kind of number.
    rate = f"{note['vnd_rate']:,.0f}"
    return {**note,
            "note": t(lang, key,
                      rate=rate.replace(",", ".") if lang == "vi" else rate,
                      source=note["source"], quoted_on=note["quoted_on"] or "")}


def _rate_line(code: str, reporting: str, rates: list[dict[str, Any]],
               lang: str) -> str:
    """The publication a restated figure rests on, or "" when there is none.

    A converted amount a reader cannot audit is an amount to distrust, so the
    rate travels with it whether it was folded into a total or only named beside
    one. A month whose rows used several days' rates states the span rather than
    one of them, which would be true of only some of the rows.
    """
    if not rates:
        return ""
    first, last = rates[0], rates[-1]
    return t(
        lang, "fx.rate_basis", currency=code, reporting=reporting,
        source=first["source"].upper(),
        rate=first["rate"] if len(rates) == 1
        else f"{first['rate']}–{last['rate']}",
        quoted_on=first["quoted_on"] if len(rates) == 1
        else f"{first['quoted_on']} → {last['quoted_on']}",
    )


def bucket_note(bucket: str, report: dict[str, Any], lang: str) -> str:
    """What the figure on this line took in, and what it still leaves out.

    August reported "Phí: $0.00" and, six lines later, "phí €0.58". Both true —
    the first was USD-only — but a reader meets the zero long before the
    explanation and has already concluded there were no fees. So both halves are
    said where the number is: the currencies converted into it, and the ones no
    published rate could reach.
    """
    totals = report.get("totals") or {}
    excluded = report.get("excluded") or {}
    reporting = totals.get("currency") or excluded.get("reporting_currency",
                                                       "USD")
    parts: list[str] = []

    # Folded in. Named anyway: the figure is a sum of two currencies now, and a
    # reader checking it against the statement needs to know which rows of it
    # will not be there at that amount.
    included = [
        t(lang, "fx.native_converted",
          native=fmt_money(row["native"][bucket], row["currency"]),
          converted=fmt_money(row["converted"][bucket], reporting))
        for row in totals.get("converted_from", [])
        if row["native"].get(bucket)
    ]
    if included:
        parts.append(t(lang, "fx.bucket_included",
                       amounts=", ".join(included)))

    outside = []
    for row in excluded.get("other_currencies", []):
        if row.get("folded_in") or not row.get(bucket):
            continue
        native = fmt_money(row[bucket], row["currency"])
        converted = (row.get("converted") or {}).get(bucket)
        # The equivalent is offered, never substituted: the charge happened in
        # its own currency and that is the figure the statement will show.
        outside.append(
            t(lang, "fx.native_converted", native=native,
              converted=fmt_money(converted, reporting))
            if converted else native)
    if outside:
        parts.append(t(lang, "excluded.bucket_other",
                       amounts=", ".join(outside)))
    return "".join(parts)


def conversion_lines(totals: dict[str, Any], lang: str) -> list[str]:
    """Name what the headline figures converted, and on whose publication.

    The report used to print $986.81 and leave the reader to add ≈$66.40 of euro
    charges to it themselves. Those charges are inside the total now, so what
    this says is no longer "excluded" but "restated": how many rows, in which
    currency, worth what on both sides, at which rate.
    """
    reporting = totals.get("currency", "USD")
    lines: list[str] = []
    for row in totals.get("converted_from", []):
        code = row["currency"]
        lines.append(t(
            lang, "fx.folded_in", count=row["txn_count"], currency=code,
            reporting=reporting,
            spend=fmt_money(row["native"]["spend_cents"], code),
            fees=fmt_money(row["native"]["fees_cents"], code),
            converted_spend=fmt_money(row["converted"]["spend_cents"],
                                      reporting),
            converted_fees=fmt_money(row["converted"]["fees_cents"], reporting),
        ))
        basis = _rate_line(code, reporting, row["rates_used"], lang)
        if basis:
            lines.append(basis)
    return lines


def excluded_lines(excluded: dict[str, Any], lang: str) -> list[str]:
    """Say what this report still set aside after converting what it could.

    Without this the report shows "Phí: $0.00" for a month that carried €0.58
    of fees and a $750 withdrawal still in flight, and a zero with no caveat
    beside it does not read as "in this currency, so far" — it reads as
    "nothing happened". Every caller that prints the totals prints these too.

    A currency that was priced in full is no longer here: it is in the totals,
    and `conversion_lines` says so. Only the rows nothing could price, and the
    rows that have not settled, are still outside.
    """
    reporting = excluded.get("reporting_currency", "USD")
    outside = [row for row in excluded.get("other_currencies", [])
               if not row.get("folded_in")]
    lines: list[str] = []
    for row in outside:
        code = row["currency"]
        converted = row.get("converted")
        common = {
            "count": row["txn_count"], "currency": code, "reporting": reporting,
            "spend": fmt_money(row["spend_cents"], code),
            "fees": fmt_money(row["fees_cents"], code),
        }
        if converted:
            # Two wordings, because the reason the amounts sit outside the
            # totals differs: here a rate covers part of the period but not all
            # of it, so the equivalent is worth printing while the total stays
            # single-currency; without any rate, nothing says what the rows are
            # worth at all. Reusing one sentence would make the second claim
            # while the equivalent is printed right beside it.
            lines.append(t(
                lang, "excluded.other_currency_converted", **common,
                converted_spend=fmt_money(converted["spend_cents"], reporting),
                converted_fees=fmt_money(converted["fees_cents"], reporting),
            ))
        else:
            lines.append(t(lang, "excluded.other_currency", **common))
    for row in outside:
        converted = row.get("converted")
        if not converted:
            continue
        basis = _rate_line(row["currency"], reporting,
                           converted.get("rates_used", []), lang)
        if basis:
            lines.append(basis)
        if not converted.get("complete"):
            lines.append(t(lang, "excluded.rate_partial",
                           count=converted.get("missing_rows", 0)))
    unsettled = excluded.get("unsettled", [])
    if unsettled:
        # Summed per currency for the same reason every other total is: the
        # list can hold a EUR row and a USD row, and one number over both
        # would not be an amount.
        per_currency: dict[str, int] = {}
        for row in unsettled:
            per_currency[row["currency"]] = (
                per_currency.get(row["currency"], 0) + row["amount_cents"])
        total = ", ".join(fmt_money(cents, code)
                          for code, cents in sorted(per_currency.items()))
        lines.append(t(lang, "excluded.unsettled",
                       count=len(unsettled), total=total))
    return lines


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
