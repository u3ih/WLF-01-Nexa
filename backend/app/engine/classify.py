"""Cash-flow classification: split the statement into payin / payout /
transfer-to-card / fee / spend (WLF-01 task 1)."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from typing import Any

from .loader import Dataset
from .merchants import resolve
from .models import CardTxn, CardTxnType, Txn, TxnStatus, TxnType

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


def settled(rows: list[Any]) -> list[Any]:
    """Rows that actually moved money.

    A declined top-up and a cancelled withdrawal appear on the statement but
    changed no balance. Counting them would overstate every total, so they are
    excluded from sums and surfaced under `unsettled` instead of vanishing.
    """
    return [r for r in rows if getattr(r, "status", TxnStatus.SUCCESS).is_settled]


def _bucket(rows: list[Any]) -> dict[str, Any]:
    """Money figures cover settled rows only; `count` covers every row.

    Amounts are split per currency because this account holds more than one and
    a single cross-currency total would be a meaningless number.
    """
    ok = settled(rows)
    by_currency: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total_cents": 0, "inflow_cents": 0, "outflow_cents": 0, "count": 0}
    )
    for r in ok:
        entry = by_currency[getattr(r, "currency", "USD")]
        entry["count"] += 1
        entry["total_cents"] += r.amount_cents
        if r.amount_cents > 0:
            entry["inflow_cents"] += r.amount_cents
        else:
            entry["outflow_cents"] += -r.amount_cents
    unsettled = [r for r in rows if r not in ok]
    primary = max(by_currency, key=lambda c: by_currency[c]["count"],
                  default="USD")
    base = by_currency.get(primary, {"total_cents": 0, "inflow_cents": 0,
                                     "outflow_cents": 0})
    return {
        "count": len(rows),
        "settled_count": len(ok),
        # Kept at the top level for the primary currency so existing readers of
        # `total_cents` keep working; `currencies` is the whole truth.
        "currency": primary,
        "total_cents": base["total_cents"],
        "inflow_cents": base["inflow_cents"],
        "outflow_cents": base["outflow_cents"],
        "currencies": {k: dict(v) for k, v in sorted(by_currency.items())},
        "unsettled": [
            {
                "ref": getattr(r, "txn_id", None) or getattr(r, "card_txn_id", ""),
                "status": r.status.value,
                "amount_cents": r.amount_cents,
                "currency": getattr(r, "currency", "USD"),
            }
            for r in unsettled
        ],
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


def wallet_only_events(ds: Dataset) -> list[Any]:
    """Wallet events that are not a shadow of a statement or card line.

    Some ledgers mirror every account line into the wallet; others record
    wallet-funded spending that appears nowhere else. Only the latter may be
    added to a total, or the mirrored rows would be counted twice.
    """
    if not ds.wallet:
        return []
    known = ({t.txn_id for t in ds.account} | {c.card_txn_id for c in ds.card})
    return [e for e in ds.wallet.events if e.ref not in known]


def spend_cents(ds: Dataset, start: date | None = None, end: date | None = None,
                currency: str = "USD") -> int:
    """Actual spending: account purchases + card purchases. Transfers between
    the user's own account and card are movement, not spend, so they are out.

    One currency at a time, settled rows only — a declined purchase is not
    spending, and USD plus EUR is not a number.
    """
    def _in(row: Any) -> bool:
        day = row.day
        return ((start is None or day >= start) and (end is None or day <= end)
                and row.currency == currency and row.status.is_settled)

    total = sum(-t.amount_cents for t in ds.account
                if t.type is TxnType.PURCHASE and _in(t))
    total += sum(-c.amount_cents for c in ds.card
                 if c.type is CardTxnType.PURCHASE and _in(c))
    # A wallet-funded purchase hits the wallet and no other ledger.
    total += sum(e.amount_cents for e in wallet_only_events(ds)
                 if e.kind == "debit" and e.note == "purchase"
                 and e.currency == currency and e.is_settled
                 and (start is None or e.day >= start)
                 and (end is None or e.day <= end))
    return total


def fee_cents(ds: Dataset, start: date | None = None, end: date | None = None,
              currency: str = "USD") -> int:
    def _in(row: Any) -> bool:
        day = row.day
        return ((start is None or day >= start) and (end is None or day <= end)
                and row.currency == currency and row.status.is_settled)

    total = sum(-t.amount_cents for t in ds.account
                if t.type is TxnType.FEE and _in(t))
    total += sum(-c.amount_cents for c in ds.card
                 if c.type is CardTxnType.FEE and _in(c))
    total += sum(e.amount_cents for e in wallet_only_events(ds)
                 if e.kind == "debit" and e.note == "fee"
                 and e.currency == currency and e.is_settled
                 and (start is None or e.day >= start)
                 and (end is None or e.day <= end))
    return total


def currencies_present(ds: Dataset) -> list[str]:
    """Every currency the dataset actually contains, primary first."""
    seen: dict[str, int] = defaultdict(int)
    for t in ds.account:
        seen[t.currency] += 1
    for c in ds.card:
        seen[c.currency] += 1
    if ds.wallet:
        for e in ds.wallet.events:
            seen[e.currency] += 1
    return sorted(seen, key=lambda c: (-seen[c], c)) or ["USD"]


def classify(ds: Dataset) -> dict[str, Any]:
    """The cash-flow table shown to the user."""
    present = currencies_present(ds)
    base = present[0]
    return {
        "period": {
            "start": ds.meta.get("period_start"),
            "end": ds.meta.get("statement_date"),
        },
        "account": account_buckets(ds.account),
        "card": card_buckets(ds.card),
        "categories": category_breakdown(ds),
        "totals": _totals(ds, base),
        "totals_by_currency": {c: _totals(ds, c) for c in present},
        "currencies": present,
        "base_currency": base,
        "sources": ds.source_files,
    }


def _totals(ds: Dataset, currency: str) -> dict[str, Any]:
    def _account(type_: TxnType, sign: int) -> int:
        return sum(sign * t.amount_cents for t in ds.account
                   if t.type is type_ and t.currency == currency
                   and t.status.is_settled)

    return {
        "currency": currency,
        "spend_cents": spend_cents(ds, currency=currency),
        "fees_cents": fee_cents(ds, currency=currency),
        "payin_cents": _account(TxnType.PAYIN, 1),
        "payout_cents": _account(TxnType.PAYOUT, -1),
        "transfer_to_card_cents": _account(TxnType.TRANSFER_TO_CARD, -1),
        "transfer_to_wallet_cents": _account(TxnType.TRANSFER_TO_WALLET, -1),
    }
