"""Three-source reconciliation: receiving account <-> wallet balance <-> card
statement (WLF-01 task 3).

Where the sources disagree we state the size of the gap and stop there — the
cause is not something this data can prove.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from .loader import Dataset
from .models import (
    CardTxn,
    CardTxnType,
    Finding,
    FindingKind,
    Source,
    SourceKind,
    Txn,
    TxnType,
    WalletEvent,
)
from .labels import make_finding

LOAD_WINDOW_DAYS = 3
# How far apart two identical credits can be and still be one event booked
# twice. A window rather than a calendar day: this export stamps in UTC, so a
# pair three hours apart can land either side of midnight, and day-bucketing
# would let exactly that pair through.
DUPLICATE_CREDIT_WINDOW_HOURS = 24


@dataclass
class TransferRow:
    txn_id: str
    when: date
    amount_cents: int
    matched_card_ref: str | None
    matched_on: date | None
    match_basis: str            # "load_ref" | "card_code" | "amount_and_date" | "none"
    gap_cents: int = 0
    # Which balance the money left. The receiving account and the wallet both
    # fund cards, and a gap on either leg is the same WLF-01 task-3 alert.
    origin: SourceKind = SourceKind.STATEMENT
    currency: str = "USD"
    card_code: str = ""
    descriptor: str = ""

    @property
    def is_matched(self) -> bool:
        return self.matched_card_ref is not None


@dataclass
class TriSourceResult:
    transfers: list[TransferRow] = field(default_factory=list)
    unmatched_loads: list[dict[str, Any]] = field(default_factory=list)
    duplicate_payins: list[list[Txn]] = field(default_factory=list)
    duplicate_wallet_credits: list[list[WalletEvent]] = field(default_factory=list)
    wallet: dict[str, Any] = field(default_factory=dict)
    wallet_orphan_refs: list[str] = field(default_factory=list)
    account_missing_wallet_events: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "transfers": [
                {
                    "txn_id": t.txn_id,
                    "date": t.when.isoformat(),
                    "amount_cents": t.amount_cents,
                    "card_ref": t.matched_card_ref,
                    "card_date": t.matched_on.isoformat() if t.matched_on else None,
                    "basis": t.match_basis,
                    "origin": t.origin.value,
                    "currency": t.currency,
                    "card_code": t.card_code,
                    "descriptor": t.descriptor,
                    "status": "matched" if t.is_matched else "not_on_card",
                }
                for t in self.transfers
            ],
            "unmatched_card_loads": self.unmatched_loads,
            "duplicate_payins": [
                {
                    "date": group[0].day.isoformat(),
                    "counterparty": group[0].counterparty,
                    "amount_cents": abs(group[0].amount_cents),
                    "txn_ids": [t.txn_id for t in group],
                }
                for group in self.duplicate_payins
            ],
            "duplicate_wallet_credits": [
                {
                    "date": group[0].day.isoformat(),
                    "counterparty": group[0].counterparty,
                    "currency": group[0].currency,
                    "amount_cents": group[0].amount_cents,
                    "event_ids": [e.event_id for e in group],
                    "descriptors": [e.descriptor or e.note for e in group],
                }
                for group in self.duplicate_wallet_credits
            ],
            "wallet": self.wallet,
            "wallet_orphan_refs": self.wallet_orphan_refs,
            "account_missing_wallet_events": self.account_missing_wallet_events,
        }


def _find_load(loads: list[CardTxn], used: set[str], amount: int, day: date,
               currency: str, card_code: str) -> tuple[CardTxn | None, str]:
    """Find the card load that the outgoing leg should have produced.

    Bases are tried strongest first, and the basis is returned alongside the
    match so a weaker one can be shown to the user rather than presented as
    proof:

    * `card_code` — the outgoing line names the card and the load is on that
      card for the same amount, in the same currency, inside the window.
    * `card_code_fx` — same, but the two ledgers label the amount in different
      currencies. The load did happen; whether the conversion is right cannot
      be checked, because this export states no rate.
    * `amount_and_date` — no card named, matched on amount and date alone.
    * `unsettled` — the only candidate is a pending or failed load, so the
      money left one balance and has not arrived on the other. Still a gap.
    """
    def _candidates(pred) -> CardTxn | None:
        return next((c for c in loads
                     if c.card_txn_id not in used
                     and abs(c.amount_cents) == amount
                     and abs((c.day - day).days) <= LOAD_WINDOW_DAYS
                     and pred(c)), None)

    settled = lambda c: c.status.is_settled   # noqa: E731

    if card_code:
        hit = _candidates(lambda c: settled(c) and c.card_code == card_code
                          and c.currency == currency)
        if hit:
            return hit, "card_code"
        hit = _candidates(lambda c: settled(c) and c.card_code == card_code)
        if hit:
            return hit, "card_code_fx"
    hit = _candidates(lambda c: settled(c) and c.currency == currency)
    if hit:
        return hit, "amount_and_date"
    # Nothing settled fits. An unsettled load with the right shape explains
    # where the money went without showing that it arrived.
    hit = _candidates(lambda c: not settled(c)
                      and (not card_code or c.card_code == card_code))
    if hit:
        return hit, "unsettled"
    return None, "none"


def _match_transfers(ds: Dataset) -> tuple[list[TransferRow], list[CardTxn]]:
    """Match every "money leaving for a card" line to the load it produced.

    Two origins fund cards: the receiving account (`transfer_to_card`) and the
    Wealify wallet (a debit naming a card code). Both share one pool of card
    loads so a single load cannot satisfy two outgoing legs.
    """
    loads = [c for c in ds.card if c.type is CardTxnType.LOAD]
    by_ref = {c.load_ref: c for c in loads if c.load_ref}
    used: set[str] = set()
    rows: list[TransferRow] = []

    for t in ds.account:
        if t.type is not TxnType.TRANSFER_TO_CARD:
            continue
        amount = abs(t.amount_cents)
        hit = by_ref.get(t.txn_id)
        basis = "load_ref"
        if hit is None or hit.card_txn_id in used:
            hit, basis = _find_load(loads, used, amount, t.day, t.currency, "")
        if hit:
            used.add(hit.card_txn_id)
        arrived = hit is not None and basis != "unsettled"
        rows.append(TransferRow(
            txn_id=t.txn_id,
            when=t.day,
            amount_cents=amount,
            matched_card_ref=hit.card_txn_id if arrived else None,
            matched_on=hit.day if arrived else None,
            match_basis=basis,
            gap_cents=0 if arrived else amount,
            origin=SourceKind.STATEMENT,
            currency=t.currency,
            descriptor=t.description,
        ))

    for e in _wallet_card_debits(ds):
        amount = e.amount_cents
        hit, basis = _find_load(loads, used, amount, e.day, e.currency,
                                e.target_card_code)
        if hit:
            used.add(hit.card_txn_id)
        arrived = hit is not None and basis != "unsettled"
        rows.append(TransferRow(
            txn_id=e.event_id,
            when=e.day,
            amount_cents=amount,
            matched_card_ref=hit.card_txn_id if arrived else None,
            matched_on=hit.day if arrived else None,
            match_basis=basis,
            gap_cents=0 if arrived else amount,
            origin=SourceKind.WALLET,
            currency=e.currency,
            card_code=e.target_card_code,
            descriptor=e.descriptor or e.note,
        ))

    orphan_loads = [c for c in loads
                    if c.card_txn_id not in used and c.status.is_settled]
    return sorted(rows, key=lambda r: (r.when, r.txn_id)), orphan_loads


def _wallet_card_debits(ds: Dataset) -> list[WalletEvent]:
    """Settled wallet debits that name a card — the wallet -> card funding leg."""
    if not ds.wallet:
        return []
    return [e for e in ds.wallet.events
            if e.kind == "debit" and e.target_card_code and e.is_settled]


def _ref_of(row: Any) -> str:
    return (getattr(row, "txn_id", None) or getattr(row, "card_txn_id", None)
            or getattr(row, "event_id", ""))


def _pairs_within_window(rows: list[Any]) -> list[list[Any]]:
    """Group rows that are identical and close together in time.

    Rows arrive already keyed on "identical" (same amount, currency and, for a
    statement line, counterparty). This walks them in time order and starts a
    new group whenever the gap to the previous row exceeds the window.
    """
    ordered = sorted(rows, key=lambda r: (r.when, _ref_of(r)))
    groups: list[list[Any]] = []
    for row in ordered:
        if groups:
            gap = (row.when - groups[-1][-1].when).total_seconds() / 3600
            if gap <= DUPLICATE_CREDIT_WINDOW_HOURS:
                groups[-1].append(row)
                continue
        groups.append([row])
    return [g for g in groups if len(g) > 1]


def _duplicate_payins(ds: Dataset) -> list[list[Txn]]:
    groups: dict[tuple[str, int, str], list[Txn]] = defaultdict(list)
    for t in ds.account:
        if t.type is not TxnType.PAYIN or not t.is_settled:
            continue
        groups[(t.counterparty, t.amount_cents, t.currency)].append(t)
    out: list[list[Txn]] = []
    for _, rows in sorted(groups.items()):
        out.extend(_pairs_within_window(rows))
    return sorted(out, key=lambda g: (g[0].when, g[0].txn_id))


def _duplicate_wallet_credits(ds: Dataset) -> list[list[WalletEvent]]:
    """The same amount credited to the wallet twice within a day of itself.

    Grouped on amount + currency rather than on the descriptor: a duplicated
    book entry is often worded differently from the entry it duplicates, so
    requiring the text to match would miss it.

    A group whose every event mirrors an account line is skipped -- where the
    wallet ledger shadows the statement, `_duplicate_payins` already owns that
    pair and reporting it here would alert the user twice for one event.
    """
    if not ds.wallet:
        return []
    account_ids = {t.txn_id for t in ds.account}
    groups: dict[tuple[int, str], list[WalletEvent]] = defaultdict(list)
    for e in ds.wallet.events:
        if e.kind != "credit" or not e.is_settled:
            continue
        groups[(e.amount_cents, e.currency)].append(e)
    out: list[list[WalletEvent]] = []
    for _, rows in sorted(groups.items()):
        for group in _pairs_within_window(rows):
            if not all(e.ref in account_ids for e in group):
                out.append(group)
    return sorted(out, key=lambda g: (g[0].when, g[0].event_id))


def reconcile(ds: Dataset) -> TriSourceResult:
    transfers, orphan_loads = _match_transfers(ds)
    result = TriSourceResult(
        transfers=transfers,
        unmatched_loads=[
            {
                "card_ref": c.card_txn_id,
                "date": c.day.isoformat(),
                "amount_cents": abs(c.amount_cents),
            }
            for c in orphan_loads
        ],
        duplicate_payins=_duplicate_payins(ds),
        duplicate_wallet_credits=_duplicate_wallet_credits(ds),
    )

    wallet = ds.wallet
    if wallet:
        computed = wallet.computed_balance_cents
        reported = wallet.reported_balance_cents
        settled = [e for e in wallet.events if e.is_settled]
        result.wallet = {
            "wallet_id": wallet.wallet_id,
            "currency": wallet.currency,
            "opening_cents": wallet.opening_balance_cents,
            "credits_cents": sum(e.amount_cents for e in settled
                                 if e.kind == "credit"),
            "debits_cents": sum(e.amount_cents for e in settled
                                if e.kind == "debit"),
            "computed_cents": computed,
            "reported_cents": reported,
            # No reported closing balance -> no gap can be asserted. The engine
            # says so rather than reporting a fabricated 0.
            "gap_cents": (computed - reported) if reported is not None else None,
            "reported_at": (wallet.reported_at.isoformat()
                            if wallet.reported_at else None),
            "event_count": len(wallet.events),
            "in_flight_count": sum(1 for e in wallet.events
                                   if e.status.is_in_flight),
        }
        account_ids = {t.txn_id for t in ds.account}
        wallet_refs = {e.ref for e in wallet.events if e.ref}
        result.wallet_orphan_refs = sorted(wallet_refs - account_ids)
        result.account_missing_wallet_events = sorted(account_ids - wallet_refs)

    return result


def findings(ds: Dataset, result: TriSourceResult) -> list[Finding]:
    statement_date = ds.statement_date
    out: list[Finding] = []

    for row in result.transfers:
        if row.is_matched:
            continue
        out.append(make_finding(
            FindingKind.TRANSFER_NOT_ON_CARD,
            params={
                "amount_cents": row.amount_cents,
                "currency": row.currency,
                "occurred_on": row.when.isoformat(),
                "searched_window_days": LOAD_WINDOW_DAYS,
                "card_statement_checked": True,
                "origin": row.origin.value,
                "card_code": row.card_code or None,
                "basis": row.match_basis,
            },
            sources=[
                Source(row.origin, row.txn_id, row.descriptor or "TRANSFER TO CARD"),
                Source(SourceKind.CARD, "card_statement.csv",
                       "load found but not settled" if row.match_basis == "unsettled"
                       else "no load found in the window"),
            ],
            statement_date=statement_date,
            txn_ids=[row.txn_id],
            amount_cents=row.amount_cents,
            confidence=0.8,
            occurred_on=row.when,
            period_key=f"nocardload:{row.txn_id}",
        ))

    for group in result.duplicate_payins:
        first = group[0]
        out.append(make_finding(
            FindingKind.DUPLICATE_PAYIN,
            params={
                "counterparty": first.counterparty,
                "amount_cents": abs(first.amount_cents),
                "count": len(group),
                "occurred_on": first.day.isoformat(),
                "total_credited_cents": sum(abs(t.amount_cents) for t in group),
            },
            sources=[Source(SourceKind.STATEMENT, t.txn_id, t.description)
                     for t in group],
            statement_date=statement_date,
            txn_ids=[t.txn_id for t in group],
            amount_cents=abs(first.amount_cents),
            confidence=0.8,
            occurred_on=first.day,
            period_key=f"duppayin:{first.day.isoformat()}:{abs(first.amount_cents)}",
        ))

    for group in result.duplicate_wallet_credits:
        first = group[0]
        out.append(make_finding(
            FindingKind.DUPLICATE_PAYIN,
            params={
                "counterparty": first.counterparty or first.descriptor,
                "amount_cents": first.amount_cents,
                "currency": first.currency,
                "count": len(group),
                "occurred_on": first.day.isoformat(),
                "total_credited_cents": sum(e.amount_cents for e in group),
                "ledger": "wallet",
                "hours_apart": round(
                    (group[-1].when - first.when).total_seconds() / 3600, 1
                ),
                "first_time": first.when.isoformat(timespec="minutes"),
                "last_time": group[-1].when.isoformat(timespec="minutes"),
            },
            sources=[Source(SourceKind.WALLET, e.event_id,
                            e.descriptor or e.note) for e in group],
            statement_date=statement_date,
            txn_ids=[e.event_id for e in group],
            amount_cents=first.amount_cents,
            confidence=0.8,
            occurred_on=first.day,
            period_key=(f"dupwalletcredit:{first.day.isoformat()}"
                        f":{first.currency}:{first.amount_cents}"),
        ))

    wallet = result.wallet
    if wallet and wallet.get("gap_cents"):
        gap: int = wallet["gap_cents"]
        out.append(make_finding(
            FindingKind.WALLET_BALANCE_MISMATCH,
            params={
                "gap_cents": abs(gap),
                "computed_cents": wallet["computed_cents"],
                "reported_cents": wallet["reported_cents"],
                "direction": "reported_lower" if gap > 0 else "reported_higher",
                "reported_at": wallet["reported_at"],
                "event_count": wallet["event_count"],
                "cause": None,          # deliberately unknown
            },
            sources=[
                Source(SourceKind.WALLET, wallet["wallet_id"],
                       f"reported balance as of {wallet['reported_at']}"),
                Source(SourceKind.STATEMENT, "account_statement.csv",
                       f"{wallet['event_count']} ledger events"),
            ],
            statement_date=statement_date,
            txn_ids=[],
            amount_cents=abs(gap),
            confidence=0.5,
            occurred_on=date.fromisoformat(wallet["reported_at"]),
            period_key=f"wallet:{wallet['reported_at']}",
        ))

    return out
