"""Cash-flow classification: split the statement into payin / payout /
transfer-to-card / fee / spend (WLF-01 task 1)."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from typing import Any

from .loader import Dataset
from .merchants import resolve
from .models import CardTxn, CardTxnType, Txn, TxnType

# Fallback rules for statements that arrive without a type column.
TYPE_PATTERNS: list[tuple[re.Pattern[str], TxnType]] = [
    (re.compile(r"\bFEE\b|SERVICE CHARGE", re.I), TxnType.FEE),
    (re.compile(r"TRANSFER TO CARD|CARD FUNDING|CARD LOAD", re.I),
     TxnType.TRANSFER_TO_CARD),
    (re.compile(r"REFUND|REVERSAL", re.I), TxnType.REFUND),
    (re.compile(r"OUTGOING WIRE|WIRE OUT|WITHDRAWAL|ATM", re.I), TxnType.PAYOUT),
    (re.compile(r"ACH CREDIT|DEPOSIT|PAYOUT RECEIVED|INCOMING", re.I), TxnType.PAYIN),
]


def infer_type(description: str, amount_cents: int) -> TxnType:
    """Best-effort type inference; used only when the source has no type column."""
    for pattern, type_ in TYPE_PATTERNS:
        if pattern.search(description):
            if type_ is TxnType.PAYIN and amount_cents < 0:
                continue
            return type_
    return TxnType.PAYIN if amount_cents > 0 else TxnType.PURCHASE


def _bucket(rows: list[Any]) -> dict[str, Any]:
    total = sum(r.amount_cents for r in rows)
    return {
        "count": len(rows),
        "total_cents": total,
        "inflow_cents": sum(r.amount_cents for r in rows if r.amount_cents > 0),
        "outflow_cents": sum(-r.amount_cents for r in rows if r.amount_cents < 0),
    }


def account_buckets(txns: list[Txn]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[Txn]] = defaultdict(list)
    for t in txns:
        grouped[t.type.value].append(t)
    return {k: _bucket(v) for k, v in sorted(grouped.items())}


def card_buckets(txns: list[CardTxn]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[CardTxn]] = defaultdict(list)
    for t in txns:
        grouped[t.type.value].append(t)
    return {k: _bucket(v) for k, v in sorted(grouped.items())}


def category_breakdown(ds: Dataset) -> list[dict[str, Any]]:
    """Spend grouped by merchant category; unresolved merchants stay 'unknown'."""
    totals: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"total_cents": 0, "count": 0}
    )
    for t in ds.account:
        if t.type is not TxnType.PURCHASE:
            continue
        found = resolve(t.description)
        key = found.category if found else "unknown"
        totals[key]["total_cents"] += -t.amount_cents
        totals[key]["count"] += 1
    for c in ds.card:
        if c.type is not CardTxnType.PURCHASE:
            continue
        found = resolve(c.merchant_raw)
        key = found.category if found else "unknown"
        totals[key]["total_cents"] += -c.amount_cents
        totals[key]["count"] += 1
    return sorted(
        ({"category": k, **v} for k, v in totals.items()),
        key=lambda r: -r["total_cents"],
    )


def spend_cents(ds: Dataset, start: date | None = None, end: date | None = None) -> int:
    """Actual spending: account purchases + card purchases. Transfers between
    the user's own account and card are movement, not spend, so they are out."""
    def _in(day: date) -> bool:
        return (start is None or day >= start) and (end is None or day <= end)

    total = sum(-t.amount_cents for t in ds.account
                if t.type is TxnType.PURCHASE and _in(t.day))
    total += sum(-c.amount_cents for c in ds.card
                 if c.type is CardTxnType.PURCHASE and _in(c.day))
    return total


def fee_cents(ds: Dataset, start: date | None = None, end: date | None = None) -> int:
    def _in(day: date) -> bool:
        return (start is None or day >= start) and (end is None or day <= end)

    total = sum(-t.amount_cents for t in ds.account
                if t.type is TxnType.FEE and _in(t.day))
    total += sum(-c.amount_cents for c in ds.card
                 if c.type is CardTxnType.FEE and _in(c.day))
    return total


def classify(ds: Dataset) -> dict[str, Any]:
    """The cash-flow table shown to the user."""
    return {
        "period": {
            "start": ds.meta.get("period_start"),
            "end": ds.meta.get("statement_date"),
        },
        "account": account_buckets(ds.account),
        "card": card_buckets(ds.card),
        "categories": category_breakdown(ds),
        "totals": {
            "spend_cents": spend_cents(ds),
            "fees_cents": fee_cents(ds),
            "payin_cents": sum(t.amount_cents for t in ds.account
                               if t.type is TxnType.PAYIN),
            "payout_cents": sum(-t.amount_cents for t in ds.account
                                if t.type is TxnType.PAYOUT),
            "transfer_to_card_cents": sum(-t.amount_cents for t in ds.account
                                          if t.type is TxnType.TRANSFER_TO_CARD),
        },
        "sources": ds.source_files,
    }
