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
    # Tested on the status, not with `r not in ok`: these are value-equal
    # dataclasses, so membership compares fields rather than identity and two
    # genuinely distinct rows that happen to match would cancel each other out.
    unsettled = [r for r in rows
                 if not getattr(r, "status", TxnStatus.SUCCESS).is_settled]
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

    Both identifiers are checked. `ref` is the pointer back at a statement row,
    but the Wealify export sets it on no wallet line at all — there a mirrored
    row would be recognisable only by sharing the card row's own id, and
    matching on `ref` alone would wave every duplicate straight into the totals.
    """
    if not ds.wallet:
        return []
    known = ({t.txn_id for t in ds.account} | {c.card_txn_id for c in ds.card})
    known.discard("")
    return [e for e in ds.wallet.events
            if e.ref not in known and e.event_id not in known]


def in_window(row: Any, start: date | None, end: date | None,
              currency: str) -> bool:
    """In this window, in this currency, and it actually moved money.

    Every bucket below is single-currency and settled-only. Mixing currencies
    would produce a total that is not an amount, and counting a declined charge
    would report money that never moved.
    """
    day = row.day
    return ((start is None or day >= start) and (end is None or day <= end)
            and getattr(row, "currency", "USD") == currency
            and row.status.is_settled)


def spend_cents(ds: Dataset, start: date | None = None, end: date | None = None,
                currency: str = "USD") -> int:
    """Actual spending: account purchases + card purchases. Transfers between
    the user's own account and card are movement, not spend, so they are out.

    One currency at a time, settled rows only — a declined purchase is not
    spending, and USD plus EUR is not a number.
    """
    def _in(row: Any) -> bool:
        return in_window(row, start, end, currency)

    total = sum(-t.amount_cents for t in ds.account
                if t.type is TxnType.PURCHASE and _in(t))
    total += sum(-c.amount_cents for c in ds.card
                 if c.type is CardTxnType.PURCHASE and _in(c))
    # A wallet-funded purchase hits the wallet and no other ledger.
    total += sum(e.amount_cents for e in wallet_only_events(ds)
                 if e.kind == "debit" and e.note == "purchase" and _in(e))
    return total


def fee_cents(ds: Dataset, start: date | None = None, end: date | None = None,
              currency: str = "USD") -> int:
    """Every issuer charge in this window, however the export records it.

    Fees arrive three ways and all three count. Some rows *are* a fee: the
    account's `FEE` lines, the card's, and the wallet's FX-fee lines. Others
    carry one alongside the amount, in a `fee` column — a $750 withdrawal that
    settles at $747.75 is a $2.25 fee, and reading only the typed rows lost it.

    Ignoring the column is how `fee_cents` could return $0 for a period the
    anomaly pass had already flagged a duplicate fee in: a fee a finding can
    see has to be a fee the total counts.
    """
    def _in(row: Any) -> bool:
        return in_window(row, start, end, currency)

    total = sum(-t.amount_cents for t in ds.account
                if t.type is TxnType.FEE and _in(t))
    total += sum(-c.amount_cents for c in ds.card
                 if c.type is CardTxnType.FEE and _in(c))
    total += sum(e.amount_cents for e in wallet_only_events(ds)
                 if e.kind == "debit" and e.note == "fee" and _in(e))
    # Fees stated in their own column, on a row that is not itself a fee. Taken
    # as a magnitude: the export writes them negative, but a fee that reduced
    # what you received is still a fee you paid.
    total += sum(abs(c.fee_cents) for c in ds.card
                 if c.fee_cents and _in(c))
    total += sum(abs(e.fee_cents) for e in wallet_only_events(ds)
                 if e.fee_cents and _in(e))
    return total


# ------------------------------------------------------------ cash-flow buckets

# Which wallet line feeds which bucket. In an export with no receiving-account
# ledger the wallet is the *only* record of these flows, so a bucket read off
# `ds.account` alone reports $0 for money that demonstrably moved.
WALLET_NOTE_BUCKET = {
    "payin": "payin",
    "payout": "payout",
    "card_to_wallet": "transfer_to_wallet",
}

ACCOUNT_FLOW_TYPE = {
    "payin": TxnType.PAYIN,
    "payout": TxnType.PAYOUT,
    "transfer_to_wallet": TxnType.TRANSFER_TO_WALLET,
}


def row_contributions(row: Any) -> list[tuple[str, int]]:
    """`(bucket key, positive magnitude)` for one row — every bucket it feeds.

    The per-bucket totals above are sums over ledgers; this is the same
    classification seen from one row, which is what a per-row job needs: an FX
    conversion has to use the rate published for *that row's* date, so a bucket
    whose rows span a month cannot be converted as a single figure.

    A row can feed two buckets. A withdrawal of $750 with a $2.25 fee column is
    a payout *and* a fee, and attributing it to only one loses real money.
    """
    out: list[tuple[str, int]] = []
    kind = getattr(row, "type", None)
    note = getattr(row, "note", "")
    if kind is TxnType.PURCHASE or kind is CardTxnType.PURCHASE:
        out.append(("spend_cents", abs(row.amount_cents)))
    elif kind is TxnType.FEE or kind is CardTxnType.FEE:
        out.append(("fees_cents", abs(row.amount_cents)))
    elif kind is TxnType.PAYIN:
        out.append(("payin_cents", abs(row.amount_cents)))
    elif kind is TxnType.PAYOUT or kind is CardTxnType.WITHDRAW:
        out.append(("payout_cents", abs(row.amount_cents)))
    elif kind is TxnType.TRANSFER_TO_CARD or kind is CardTxnType.LOAD:
        out.append(("transfer_to_card_cents", abs(row.amount_cents)))
    elif kind is TxnType.TRANSFER_TO_WALLET:
        out.append(("transfer_to_wallet_cents", abs(row.amount_cents)))
    elif kind is None and note:
        # A wallet line. `note` is what the loader worked out the line did.
        bucket = {"payin": "payin_cents", "payout": "payout_cents",
                  "fee": "fees_cents", "purchase": "spend_cents",
                  "transfer_to_card": "transfer_to_card_cents",
                  "card_to_wallet": "transfer_to_wallet_cents"}.get(note)
        if bucket:
            out.append((bucket, abs(row.amount_cents)))
    fee_column = getattr(row, "fee_cents", None)
    if fee_column:
        out.append(("fees_cents", abs(fee_column)))
    return out


def flow_cents(ds: Dataset, bucket: str, start: date | None = None,
               end: date | None = None, currency: str = "USD") -> int:
    """One cash-flow bucket as a positive magnitude, from every ledger present.

    `payin` and `payout` are money crossing the platform's edge; a transfer
    between the user's own wallet, account and cards is movement, not flow, and
    is reported by `transfer_to_card_cents` / the `transfer_to_wallet` bucket
    instead. Cash pulled off a card leaves the platform exactly like a wallet
    withdrawal does, so it is a payout wherever the export files it.
    """
    if bucket not in ACCOUNT_FLOW_TYPE:
        raise ValueError(f"unknown cash-flow bucket: {bucket}")

    def _in(row: Any) -> bool:
        return in_window(row, start, end, currency)

    total = sum(abs(t.amount_cents) for t in ds.account
                if t.type is ACCOUNT_FLOW_TYPE[bucket] and _in(t))
    total += sum(e.amount_cents for e in wallet_only_events(ds)
                 if WALLET_NOTE_BUCKET.get(e.note) == bucket and _in(e))
    if bucket == "payout":
        total += sum(abs(c.amount_cents) for c in ds.card
                     if c.type is CardTxnType.WITHDRAW and _in(c))
    return total


def transfer_to_card_cents(ds: Dataset, start: date | None = None,
                           end: date | None = None,
                           currency: str = "USD") -> tuple[int, int]:
    """`(landed on a card, left the wallet for a card)` — both, never averaged.

    Two ledgers record the same movement and they do not agree: this export's
    wallet says $15,686.02 went to cards while the cards received $13,034.00.
    The gap is real, not rounding — `tri_source` raises a `transfer_not_on_card`
    finding for each leg that never arrived — so collapsing the two into one
    number would state a figure that is true of neither ledger and bury the
    discrepancy the user most needs to see.

    The headline figure is the card side, because "chuyển sang thẻ" is money
    that reached a card. When the export ships no card ledger at all, the
    wallet side stands in rather than reporting a false zero.
    """
    def _in(row: Any) -> bool:
        return in_window(row, start, end, currency)

    arrived = sum(abs(c.amount_cents) for c in ds.card
                  if c.type is CardTxnType.LOAD and _in(c))
    sent = sum(e.amount_cents for e in wallet_only_events(ds)
               if e.note == "transfer_to_card" and _in(e))
    sent += sum(abs(t.amount_cents) for t in ds.account
                if t.type is TxnType.TRANSFER_TO_CARD and _in(t))
    has_card_ledger = any(c.type is CardTxnType.LOAD for c in ds.card)
    return (arrived if has_card_ledger else sent), sent


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
    """The five buckets, over the whole dataset, in one currency.

    Shares `flow_cents` and `transfer_to_card_cents` with the period report so
    the two cannot drift: they did, and the report spent months telling users
    that no money had entered or left an account that moved $87,192.95.
    """
    to_card, sent_to_card = transfer_to_card_cents(ds, currency=currency)
    return {
        "currency": currency,
        "spend_cents": spend_cents(ds, currency=currency),
        "fees_cents": fee_cents(ds, currency=currency),
        "payin_cents": flow_cents(ds, "payin", currency=currency),
        "payout_cents": flow_cents(ds, "payout", currency=currency),
        "transfer_to_card_cents": to_card,
        # What the wallet says it sent, next to what the cards say arrived. Zero
        # gap is the normal case; a non-zero one has a finding to explain it.
        "transfer_to_card_sent_cents": sent_to_card,
        "transfer_to_card_gap_cents": sent_to_card - to_card,
        "transfer_to_wallet_cents": flow_cents(ds, "transfer_to_wallet",
                                               currency=currency),
    }
