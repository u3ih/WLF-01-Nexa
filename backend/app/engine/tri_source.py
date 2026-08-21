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
)
from .labels import make_finding

LOAD_WINDOW_DAYS = 3


@dataclass
class TransferRow:
    txn_id: str
    when: date
    amount_cents: int
    matched_card_ref: str | None
    matched_on: date | None
    match_basis: str            # "load_ref" | "amount_and_date" | "none"
    gap_cents: int = 0

    @property
    def is_matched(self) -> bool:
        return self.matched_card_ref is not None


@dataclass
class TriSourceResult:
    transfers: list[TransferRow] = field(default_factory=list)
    unmatched_loads: list[dict[str, Any]] = field(default_factory=list)
    duplicate_payins: list[list[Txn]] = field(default_factory=list)
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
            "wallet": self.wallet,
            "wallet_orphan_refs": self.wallet_orphan_refs,
            "account_missing_wallet_events": self.account_missing_wallet_events,
        }


def _match_transfers(ds: Dataset) -> tuple[list[TransferRow], list[CardTxn]]:
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
            hit = next(
                (
                    c for c in loads
                    if c.card_txn_id not in used
                    and abs(c.amount_cents) == amount
                    and abs((c.day - t.day).days) <= LOAD_WINDOW_DAYS
                ),
                None,
            )
            basis = "amount_and_date" if hit else "none"
        if hit:
            used.add(hit.card_txn_id)
        rows.append(TransferRow(
            txn_id=t.txn_id,
            when=t.day,
            amount_cents=amount,
            matched_card_ref=hit.card_txn_id if hit else None,
            matched_on=hit.day if hit else None,
            match_basis=basis,
            gap_cents=0 if hit else amount,
        ))

    orphan_loads = [c for c in loads if c.card_txn_id not in used]
    return rows, orphan_loads


def _duplicate_payins(ds: Dataset) -> list[list[Txn]]:
    groups: dict[tuple[str, int, date], list[Txn]] = defaultdict(list)
    for t in ds.account:
        if t.type is not TxnType.PAYIN:
            continue
        groups[(t.counterparty, t.amount_cents, t.day)].append(t)
    return [sorted(v, key=lambda t: t.txn_id)
            for _, v in sorted(groups.items()) if len(v) > 1]


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
    )

    wallet = ds.wallet
    if wallet:
        computed = wallet.computed_balance_cents
        reported = wallet.reported_balance_cents
        result.wallet = {
            "wallet_id": wallet.wallet_id,
            "opening_cents": wallet.opening_balance_cents,
            "credits_cents": sum(e.amount_cents for e in wallet.events
                                 if e.kind == "credit"),
            "debits_cents": sum(e.amount_cents for e in wallet.events
                                if e.kind == "debit"),
            "computed_cents": computed,
            "reported_cents": reported,
            "gap_cents": computed - reported,
            "reported_at": wallet.reported_at.isoformat(),
            "event_count": len(wallet.events),
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
                "occurred_on": row.when.isoformat(),
                "searched_window_days": LOAD_WINDOW_DAYS,
                "card_statement_checked": True,
            },
            sources=[
                Source(SourceKind.STATEMENT, row.txn_id, "TRANSFER TO CARD"),
                Source(SourceKind.CARD, "card_statement.csv",
                       "no load found in the window"),
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

    wallet = result.wallet
    if wallet and wallet.get("gap_cents"):
        gap = wallet["gap_cents"]
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
