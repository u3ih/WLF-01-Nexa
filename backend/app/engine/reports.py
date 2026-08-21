"""Month / quarter / year spending reports plus period-over-period comparison
(WLF-01 task 6)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

from dateutil.relativedelta import relativedelta

from .classify import category_breakdown, fee_cents, spend_cents
from .loader import Dataset
from .merchants import resolve
from .models import CardTxnType, TxnType

PERIODS = ("month", "quarter", "year")


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


def _purchase_rows(ds: Dataset, period: Period) -> list[dict[str, Any]]:
    rows = [
        {
            "ref": t.txn_id, "source": "statement", "date": t.day.isoformat(),
            "descriptor": t.description, "merchant": t.merchant,
            "amount_cents": -t.amount_cents,
        }
        for t in ds.account if t.type is TxnType.PURCHASE and _in(t.day, period)
    ]
    rows += [
        {
            "ref": c.card_txn_id, "source": "card", "date": c.day.isoformat(),
            "descriptor": c.merchant_raw, "merchant": c.merchant,
            "amount_cents": -c.amount_cents,
        }
        for c in ds.card if c.type is CardTxnType.PURCHASE and _in(c.day, period)
    ]
    return sorted(rows, key=lambda r: -r["amount_cents"])


def _fee_rows(ds: Dataset, period: Period) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "total_cents": 0}
    )
    for t in ds.account:
        if t.type is TxnType.FEE and _in(t.day, period):
            g = grouped[t.description]
            g["count"] += 1
            g["total_cents"] += -t.amount_cents
    for c in ds.card:
        if c.type is CardTxnType.FEE and _in(c.day, period):
            g = grouped[c.merchant_raw]
            g["count"] += 1
            g["total_cents"] += -c.amount_cents
    return sorted(
        ({"descriptor": k, **v} for k, v in grouped.items()),
        key=lambda r: -r["total_cents"],
    )


def _period_categories(ds: Dataset, period: Period) -> list[dict[str, Any]]:
    totals: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"total_cents": 0, "count": 0}
    )
    for row in _purchase_rows(ds, period):
        found = resolve(row["descriptor"])
        key = found.category if found else "unknown"
        totals[key]["total_cents"] += row["amount_cents"]
        totals[key]["count"] += 1
    return sorted(
        ({"category": k, **v} for k, v in totals.items()),
        key=lambda r: -r["total_cents"],
    )


def _core(ds: Dataset, period: Period) -> dict[str, Any]:
    return {
        "spend_cents": spend_cents(ds, period.start, period.end),
        "fees_cents": fee_cents(ds, period.start, period.end),
        "payin_cents": sum(t.amount_cents for t in ds.account
                           if t.type is TxnType.PAYIN and _in(t.day, period)),
        "payout_cents": sum(-t.amount_cents for t in ds.account
                            if t.type is TxnType.PAYOUT and _in(t.day, period)),
        "transfer_to_card_cents": sum(
            -t.amount_cents for t in ds.account
            if t.type is TxnType.TRANSFER_TO_CARD and _in(t.day, period)
        ),
        "txn_count": len([1 for t in ds.account if _in(t.day, period)])
        + len([1 for c in ds.card if _in(c.day, period)]),
    }


def _delta(current: int, previous: int) -> dict[str, Any]:
    diff = current - previous
    return {
        "previous_cents": previous,
        "delta_cents": diff,
        "percent": round(100 * diff / previous, 1) if previous else None,
    }


def build(ds: Dataset, kind: str = "month", key: str | None = None,
          subs_forecast: dict[str, Any] | None = None) -> dict[str, Any]:
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


def all_periods(ds: Dataset, subs_forecast: dict[str, Any] | None = None
                ) -> dict[str, Any]:
    return {
        kind: build(ds, kind, None, subs_forecast) for kind in PERIODS
    }
