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
    own date, because a bucket whose rows span a month has no single rate. A row
    the table cannot cover is counted in `missing` and left out of the sum, and
    `complete` then says the restated figure is partial — a converted total that
    quietly dropped a row would be worse than no conversion at all.
    """
    totals: dict[str, int] = {key: 0 for key in BUCKET_KEYS}
    used: dict[str, Any] = {}
    missing = 0
    for row in _all_rows(ds):
        if not _counts(row, period, code):
            continue
        for bucket, cents in row_contributions(row):
            done = fx.convert(cents, row.day, code, currency)
            if done is None:
                missing += 1
                continue
            totals[bucket] += done.cents
            # The rate actually applied, kept so a restated figure can name its
            # basis instead of asking the reader to trust it.
            used[done.quote.quoted_on.isoformat()] = done.quote.as_dict()
    return {
        **{key: totals[key] for key in BUCKET_KEYS},
        "complete": missing == 0 and bool(used),
        "missing_rows": missing,
        "rates_used": [used[day] for day in sorted(used)],
    }


def _excluded(ds: Dataset, period: Period, currency: str = "USD",
              fx: FxTable | None = None) -> dict[str, Any]:
    """What a single-currency, settled-only report left out.

    "$0.00 in fees" reads as "you paid no fees". If €13.85 of fees were merely
    not in the reporting currency, or a $18.93 charge is still pending, the
    report owes the user that sentence rather than a zero that looks like an
    answer.

    When published rates cover the period, each foreign currency also carries
    its equivalent in the reporting currency, so the caveat can say how much the
    excluded rows were actually worth instead of only naming them.
    """
    table = fx if fx is not None else fx_module.EMPTY
    others = []
    for code in currencies_present(ds):
        if code == currency:
            continue
        # Every bucket, not only spend and fees: a report whose *tiền vào* line
        # said $0.00 next to an unmentioned EUR payin would mislead in exactly
        # the same way, and nothing about this export guarantees it never will.
        buckets = _core(ds, period, code)
        rows = len([1 for r in _all_rows(ds) if _counts(r, period, code)])
        if rows or any(buckets[key] for key in BUCKET_KEYS):
            converted = _converted(ds, period, code, currency, table)
            others.append({
                "currency": code, "txn_count": rows,
                **{key: buckets[key] for key in BUCKET_KEYS},
                # Absent, not zero, when no rate covers the period: zero would
                # read as "worth nothing" rather than "not known".
                "converted": converted if converted["complete"]
                or converted["rates_used"] else None,
            })

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
    current = _core(ds, period)
    previous = _core(ds, prev)
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
        "excluded": _excluded(ds, period, fx=fx),
        "categories": _period_categories(ds, period),
        "subscriptions": subs_forecast or {},
        "sources": ds.source_files,
    }


def monthly_series(ds: Dataset, months: int = 12) -> list[dict[str, Any]]:
    """Spend and fees per month, oldest first — feeds the UI trend chart."""
    anchor = ds.statement_date.replace(day=1)
    out = []
    for offset in range(months - 1, -1, -1):
        period = period_bounds("month", anchor - relativedelta(months=offset))
        out.append({
            "key": period.key,
            "spend_cents": spend_cents(ds, period.start, period.end),
            "fees_cents": fee_cents(ds, period.start, period.end),
        })
    return out


def all_periods(ds: Dataset, subs_forecast: dict[str, Any] | None = None,
                fx: FxTable | None = None) -> dict[str, Any]:
    return {
        kind: build(ds, kind, None, subs_forecast, fx) for kind in PERIODS
    }
