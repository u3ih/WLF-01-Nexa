"""Month / quarter / year spending reports plus period-over-period comparison
(WLF-01 task 6)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

from dateutil.relativedelta import relativedelta

from .. import fx as fx_module
from ..fx import FxTable
from .classify import (
    currencies_present,
    fee_cents,
    flow_cents,
    row_contributions,
    spend_cents,
    transfer_to_card_cents,
    wallet_only_events,
)
from .loader import Dataset
from .merchants import resolve
from .models import CardTxnType, TxnType

PERIODS = ("month", "quarter", "year")

# The money buckets, as opposed to the counts and the derived comparisons. Any
# of them can be zero in the reporting currency while another currency carries
# a figure, so every one of them needs the same caveat treatment.
BUCKET_KEYS = ("spend_cents", "fees_cents", "payin_cents", "payout_cents",
               "transfer_to_card_cents", "transfer_to_wallet_cents")

# The figures a converted currency can be added into. The wallet side of the
# to-card movement joins them because it is a sum, not a derivation; the gap
# between the two ledgers is recomputed from the combined pair afterwards
# rather than added up, or it would be counted twice.
SUM_KEYS = BUCKET_KEYS + ("transfer_to_card_sent_cents",)


@dataclass
class Period:
    kind: str
    start: date
    end: date
    key: str
    label: str


def period_bounds(kind: str, anchor: date) -> Period:
    if kind == "month":
        start = anchor.replace(day=1)
        end = start + relativedelta(months=1, days=-1)
        return Period(kind, start, end, f"{start:%Y-%m}", f"{start:%Y-%m}")
    if kind == "quarter":
        q = (anchor.month - 1) // 3 + 1
        start = date(anchor.year, 3 * (q - 1) + 1, 1)
        end = start + relativedelta(months=3, days=-1)
        return Period(kind, start, end, f"{anchor.year}-Q{q}", f"{anchor.year} Q{q}")
    if kind == "year":
        start = date(anchor.year, 1, 1)
        end = date(anchor.year, 12, 31)
        return Period(kind, start, end, str(anchor.year), str(anchor.year))
    raise ValueError(f"unknown period: {kind}")


def previous_period(period: Period) -> Period:
    if period.kind == "month":
        return period_bounds("month", period.start - relativedelta(months=1))
    if period.kind == "quarter":
        return period_bounds("quarter", period.start - relativedelta(months=3))
    return period_bounds("year", period.start - relativedelta(years=1))


def parse_period_key(kind: str, key: str | None, fallback: date) -> Period:
    """Accept '2026-07', '2026-Q3', '2026' or None."""
    if not key:
        return period_bounds(kind, fallback)
    try:
        if kind == "month":
            year, month = key.split("-")[:2]
            return period_bounds("month", date(int(year), int(month), 1))
        if kind == "quarter":
            year, q = key.upper().split("-Q")
            return period_bounds("quarter", date(int(year), 3 * (int(q) - 1) + 1, 1))
        return period_bounds("year", date(int(key[:4]), 1, 1))
    except (ValueError, IndexError):
        return period_bounds(kind, fallback)


def _in(day: date, period: Period) -> bool:
    return period.start <= day <= period.end


def _counts(row: Any, period: Period, currency: str) -> bool:
    """In this period, in this currency, and it actually moved money.

    Every figure in a report is single-currency and settled-only. Mixing
    currencies would produce a total that is not an amount, and counting a
    declined charge would report spending that never happened.
    """
    return (_in(row.day, period) and row.currency == currency
            and row.status.is_settled)


def _purchase_rows(ds: Dataset, period: Period,
                   currency: str = "USD") -> list[dict[str, Any]]:
    rows = [
        {
            "ref": t.txn_id, "source": "statement", "date": t.day.isoformat(),
            "descriptor": t.description, "merchant": t.merchant,
            "amount_cents": -t.amount_cents, "currency": t.currency,
        }
        for t in ds.account
        if t.type is TxnType.PURCHASE and _counts(t, period, currency)
    ]
    rows += [
        {
            "ref": c.card_txn_id, "source": "card", "date": c.day.isoformat(),
            "descriptor": c.merchant_raw, "merchant": c.merchant,
            "amount_cents": -c.amount_cents, "currency": c.currency,
            "card_code": c.card_code or None,
        }
        for c in ds.card
        if c.type is CardTxnType.PURCHASE and _counts(c, period, currency)
    ]
    return sorted(rows, key=lambda r: -r["amount_cents"])


def _fee_rows(ds: Dataset, period: Period,
              currency: str = "USD") -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "total_cents": 0}
    )
    for t in ds.account:
        if t.type is TxnType.FEE and _counts(t, period, currency):
            g = grouped[t.description]
            g["count"] += 1
            g["total_cents"] += -t.amount_cents
    for c in ds.card:
        if c.type is CardTxnType.FEE and _counts(c, period, currency):
            g = grouped[c.merchant_raw]
            g["count"] += 1
            g["total_cents"] += -c.amount_cents
    # A fee charged straight to the wallet is on no other ledger.
    for e in wallet_only_events(ds):
        if e.note == "fee" and _counts(e, period, currency):
            g = grouped[e.descriptor or e.note]
            g["count"] += 1
            g["total_cents"] += e.amount_cents
    # Fees stated in a column beside the amount rather than on a row of their
    # own. Listed here too, or the itemised fees would not add up to
    # `fees_cents` and the difference would look like an arithmetic error.
    for row in list(ds.card) + wallet_only_events(ds):
        if row.fee_cents and _counts(row, period, currency):
            label = (getattr(row, "merchant_raw", "")
                     or getattr(row, "descriptor", "") or "fee")
            g = grouped[f"{label} — fee"]
            g["count"] += 1
            g["total_cents"] += abs(row.fee_cents)
    return sorted(
        ({"descriptor": k, **v} for k, v in grouped.items()),
        key=lambda r: -r["total_cents"],
    )


def _period_categories(ds: Dataset, period: Period,
                       currency: str = "USD") -> list[dict[str, Any]]:
    totals: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"total_cents": 0, "count": 0}
    )
    for row in _purchase_rows(ds, period, currency):
        found = resolve(row["descriptor"])
        key = found.category if found else "unknown"
        totals[key]["total_cents"] += row["amount_cents"]
        totals[key]["count"] += 1
    return sorted(
        ({"category": k, **v} for k, v in totals.items()),
        key=lambda r: -r["total_cents"],
    )


def _core(ds: Dataset, period: Period, currency: str = "USD") -> dict[str, Any]:
    """The five buckets for one period, in one currency.

    Every figure comes from the same helpers `classify._totals` uses. They were
    once computed here from `ds.account` alone, which the Wealify export does
    not have — so four of the five buckets read $0 in every period while the
    wallet and card ledgers carried exactly those flows.
    """
    to_card, sent_to_card = transfer_to_card_cents(ds, period.start, period.end,
                                                   currency)
    return {
        "currency": currency,
        "spend_cents": spend_cents(ds, period.start, period.end, currency),
        "fees_cents": fee_cents(ds, period.start, period.end, currency),
        "payin_cents": flow_cents(ds, "payin", period.start, period.end,
                                  currency),
        "payout_cents": flow_cents(ds, "payout", period.start, period.end,
                                   currency),
        "transfer_to_card_cents": to_card,
        "transfer_to_card_sent_cents": sent_to_card,
        "transfer_to_card_gap_cents": sent_to_card - to_card,
        "transfer_to_wallet_cents": flow_cents(ds, "transfer_to_wallet",
                                               period.start, period.end,
                                               currency),
        # Counted on the same basis as the money above, and over the same three
        # ledgers, so the two agree. Counting only the account and card rows
        # while summing wallet money as well made 17 purchases look like 20
        # transactions with nothing to show for the other three. The rows the
        # currency and settlement filters removed are not dropped — `excluded`
        # below says how many and what they were worth.
        "txn_count": len([1 for r in _all_rows(ds)
                          if _counts(r, period, currency)]),
        "all_txn_count": len([1 for r in _all_rows(ds) if _in(r.day, period)]),
    }


def _all_rows(ds: Dataset) -> list[Any]:
    """Every row that can carry money, across all three ledgers, counted once."""
    return list(ds.account) + list(ds.card) + wallet_only_events(ds)


def _converted(ds: Dataset, period: Period, code: str, currency: str,
               fx: FxTable) -> dict[str, Any]:
    """Restate one currency's buckets in the reporting currency, row by row.

    Per row, not per total: each row is converted at the rate published for its
    own date, because a bucket whose rows span a month has no single rate. The
    rate is looked up once per row, so a row is priced whole or not at all —
    `missing_rows` therefore counts rows rather than bucket contributions, which
    is what the caveat beside it claims to be counting. `complete` says whether
    the restated figure covers every row: a converted total that quietly
    dropped one would be worse than no conversion at all.
    """
    totals: dict[str, int] = {key: 0 for key in BUCKET_KEYS}
    used: dict[str, Any] = {}
    arrived = sent = 0
    priced = missing = 0
    for row in _all_rows(ds):
        if not _counts(row, period, code):
            continue
        contributions = row_contributions(row)
        if not contributions:
            continue
        quote = fx.rate_on(row.day, code, currency)
        if quote is None:
            missing += 1
            continue
        priced += 1
        # The rate actually applied, kept so a restated figure can name its
        # basis instead of asking the reader to trust it.
        used[quote.quoted_on.isoformat()] = quote.as_dict()
        for bucket, cents in contributions:
            if bucket != "transfer_to_card_cents":
                totals[bucket] += quote.apply(cents)
                continue
            # Two ledgers record this movement and they disagree, so the native
            # figure keeps them apart. The converted one has to as well, or a
            # card load and the wallet debit that funded it are added together
            # into a transfer that only happened once.
            if getattr(row, "type", None) is CardTxnType.LOAD:
                arrived += quote.apply(cents)
            else:
                sent += quote.apply(cents)
    has_card_ledger = any(c.type is CardTxnType.LOAD for c in ds.card)
    totals["transfer_to_card_cents"] = arrived if has_card_ledger else sent
    return {
        **totals,
        # These figures are denominated in the reporting currency, not in the
        # one being converted from. Said here because the API boundary formats
        # money by the currency the block names, and a restated euro total
        # labelled EUR would print €66.40 for a $66.40 figure.
        "currency": currency,
        "transfer_to_card_sent_cents": sent,
        "transfer_to_card_gap_cents": sent - totals["transfer_to_card_cents"],
        "complete": missing == 0 and bool(used),
        "priced_rows": priced,
        "missing_rows": missing,
        "rates_used": [used[day] for day in sorted(used)],
    }


def _foreign(ds: Dataset, period: Period, currency: str,
             fx: FxTable) -> list[dict[str, Any]]:
    """Every currency in the period that is not the reporting one.

    One pass, read by both the totals and the caveat, because the two used to
    decide separately what a currency was worth and could disagree about it.
    `folded_in` is that decision: a currency priced in full joins the headline
    figures, and one the table cannot price in full stays outside them and is
    named instead.
    """
    out: list[dict[str, Any]] = []
    for code in currencies_present(ds):
        if code == currency:
            continue
        # Every bucket, not only spend and fees: a report whose *tiền vào* line
        # said $0.00 next to an unmentioned EUR payin would mislead in exactly
        # the same way, and nothing about this export guarantees it never will.
        buckets = _core(ds, period, code)
        rows = len([1 for r in _all_rows(ds) if _counts(r, period, code)])
        if not rows and not any(buckets[key] for key in BUCKET_KEYS):
            continue
        converted = _converted(ds, period, code, currency, fx)
        out.append({
            "currency": code, "txn_count": rows,
            **{key: buckets[key] for key in SUM_KEYS},
            # Absent, not zero, when no rate covers the period: zero would
            # read as "worth nothing" rather than "not known".
            "converted": converted if converted["rates_used"] else None,
            # Only a complete conversion is folded in. A partial one would make
            # the headline silently drop the rows it could not price, which is
            # exactly the failure the caveat exists to prevent.
            "folded_in": converted["complete"],
        })
    return out


def _combined(ds: Dataset, period: Period, currency: str,
              foreign: list[dict[str, Any]]) -> dict[str, Any]:
    """The period's figures in the reporting currency, conversions included.

    The report used to publish reporting-currency rows only, with the rest named
    underneath: "Chi tiêu: $986.81 — chưa gồm €57.54 (≈$66.40)". Both figures
    were right and the reader still had to add them up to learn what August
    cost. Now that rates are stored and dated per row, the headline covers the
    whole period and the parts stay beside it: `native` is what the statement
    shows line by line, `converted_in` is what the rates added, and
    `converted_from` names every rate used, so a restated total can still be
    checked against the ledger it came from.

    A currency the table cannot price in full is not folded in at a guess. It
    stays out of these figures and in `excluded`, and `conversion_complete` says
    so rather than leaving the reader to infer it.
    """
    native = _core(ds, period, currency)
    added = {key: 0 for key in SUM_KEYS}
    folded_rows = 0
    folded: list[dict[str, Any]] = []
    for row in foreign:
        if not row["folded_in"]:
            continue
        conversion = row["converted"]
        for key in SUM_KEYS:
            added[key] += conversion[key]
        folded_rows += row["txn_count"]
        folded.append({
            "currency": row["currency"],
            "txn_count": row["txn_count"],
            # Each half names the currency its cents are in. Two figures of the
            # same charge sit side by side here — €57.54 and $66.40 — and the
            # API boundary has no other way to tell which symbol belongs to
            # which.
            "native": {"currency": row["currency"],
                       **{key: row[key] for key in SUM_KEYS}},
            "converted": {"currency": currency,
                          **{key: conversion[key] for key in SUM_KEYS}},
            "rates_used": conversion["rates_used"],
        })
    out = {
        "currency": currency,
        **{key: native[key] + added[key] for key in SUM_KEYS},
        "native": {"currency": currency,
                   **{key: native[key] for key in SUM_KEYS}},
        "converted_in": {"currency": currency, **added},
        "converted_from": folded,
        # False when a currency in this period could not be priced in full, so
        # a reader can tell a whole-period figure from one that covers only the
        # rows a rate reached.
        "conversion_complete": all(row["folded_in"] for row in foreign),
        # Counted on the same basis as the money: the rows whose amounts were
        # folded in are rows this count has to include, or the average charge
        # implied by the two figures is of a period neither describes.
        "txn_count": native["txn_count"] + folded_rows,
        "all_txn_count": native["all_txn_count"],
    }
    # Derived from the combined pair, never summed: adding two gaps would count
    # the difference between the ledgers once per currency.
    out["transfer_to_card_gap_cents"] = (out["transfer_to_card_sent_cents"]
                                        - out["transfer_to_card_cents"])
    return out


def _excluded(ds: Dataset, period: Period, currency: str = "USD",
              foreign: list[dict[str, Any]] | None = None,
              fx: FxTable | None = None) -> dict[str, Any]:
    """What this report still left out after converting what it could.

    "$0.00 in fees" reads as "you paid no fees". If €13.85 of fees had no
    published rate to be restated with, or a $18.93 charge is still pending, the
    report owes the user that sentence rather than a zero that looks like an
    answer.

    A currency that *was* converted is still listed, carrying `folded_in`, so
    the audit trail survives the fold — but the wording built from this block
    stops calling it excluded, because it no longer is.
    """
    others = foreign if foreign is not None else _foreign(
        ds, period, currency, fx if fx is not None else fx_module.EMPTY)

    # Pending, processing, cancelled and declined together: all four are rows
    # the period contains but no total may count. Kept under one key rather
    # than "in flight", because a cancelled row is not in flight — it is over.
    unsettled = [
        {"ref": getattr(r, "card_txn_id", None) or getattr(r, "txn_id", "")
         or getattr(r, "event_id", ""),
         "status": r.status.value,
         "in_flight": r.status.is_in_flight,
         "amount_cents": abs(r.amount_cents),
         "currency": r.currency,
         "descriptor": (getattr(r, "merchant_raw", "")
                        or getattr(r, "description", "")
                        or getattr(r, "descriptor", ""))}
        for r in _all_rows(ds)
        if _in(r.day, period) and not r.status.is_settled
    ]
    return {
        "reporting_currency": currency,
        "other_currencies": others,
        "unsettled": sorted(unsettled, key=lambda r: -r["amount_cents"]),
    }


def _delta(current: int, previous: int) -> dict[str, Any]:
    diff = current - previous
    return {
        "previous_cents": previous,
        "delta_cents": diff,
        "percent": round(100 * diff / previous, 1) if previous else None,
    }


def build(ds: Dataset, kind: str = "month", key: str | None = None,
          subs_forecast: dict[str, Any] | None = None,
          fx: FxTable | None = None) -> dict[str, Any]:
    if kind not in PERIODS:
        raise ValueError(f"period must be one of {PERIODS}")
    period = parse_period_key(kind, key, ds.statement_date)
    prev = previous_period(period)
    table = fx if fx is not None else fx_module.EMPTY
    foreign = _foreign(ds, period, "USD", table)
    current = _combined(ds, period, "USD", foreign)
    # Both periods go through the same rule, so a month-on-month change is not
    # an artefact of one side having been converted and the other not. Each side
    # still publishes its own `conversion_complete`, which is what tells a
    # reader when the two rest on different coverage.
    previous = _combined(ds, prev, "USD", _foreign(ds, prev, "USD", table))
    purchases = _purchase_rows(ds, period)

    return {
        "period": {
            "kind": period.kind, "key": period.key, "label": period.label,
            "start": period.start.isoformat(), "end": period.end.isoformat(),
        },
        "totals": current,
        "net_flow_cents": current["payin_cents"]
        - current["spend_cents"] - current["fees_cents"] - current["payout_cents"],
        "comparison": {
            "period_key": prev.key,
            "spend": _delta(current["spend_cents"], previous["spend_cents"]),
            "fees": _delta(current["fees_cents"], previous["fees_cents"]),
        },
        "top_purchases": purchases[:3],
        "purchase_count": len(purchases),
        "fees": _fee_rows(ds, period),
        "excluded": _excluded(ds, period, "USD", foreign),
        "categories": _period_categories(ds, period),
        "subscriptions": subs_forecast or {},
        "sources": ds.source_files,
    }


def monthly_series(ds: Dataset, months: int = 12,
                   fx: FxTable | None = None) -> list[dict[str, Any]]:
    """Spend and fees per month, oldest first — feeds the UI trend chart.

    Built from the same combined figures the report headline uses. A chart on a
    reporting-currency-only basis beside a total that includes conversions is
    two answers to one question, and the month with the euro rows in it is the
    month the two would disagree about.
    """
    table = fx if fx is not None else fx_module.EMPTY
    anchor = ds.statement_date.replace(day=1)
    out = []
    for offset in range(months - 1, -1, -1):
        period = period_bounds("month", anchor - relativedelta(months=offset))
        totals = _combined(ds, period, "USD",
                           _foreign(ds, period, "USD", table))
        out.append({
            "key": period.key,
            "spend_cents": totals["spend_cents"],
            "fees_cents": totals["fees_cents"],
        })
    return out


def all_periods(ds: Dataset, subs_forecast: dict[str, Any] | None = None,
                fx: FxTable | None = None) -> dict[str, Any]:
    return {
        kind: build(ds, kind, None, subs_forecast, fx) for kind in PERIODS
    }
