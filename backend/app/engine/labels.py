"""The three-tier labelling rule (WLF-01 rule C).

Only these three verdicts exist in the whole system. There is deliberately no
"fraud"/"not fraud" value anywhere, and no code path that can emit one.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .models import DISPUTE_WINDOW_DAYS, Finding, FindingKind, Label, Source

# Which label each finding kind carries. Recurrence we can prove from the
# statement itself; anything that depends on the user's intent or on data we do
# not have must not be asserted.
KIND_LABEL: dict[FindingKind, Label] = {
    FindingKind.RECURRING_SUBSCRIPTION: Label.RECURRING_CONFIRMED,
    FindingKind.PRICE_INCREASE: Label.RECURRING_CONFIRMED,
    FindingKind.FORGOTTEN_SUBSCRIPTION: Label.NEEDS_YOUR_CONFIRMATION,
    FindingKind.DUPLICATE_CHARGE: Label.NEEDS_YOUR_CONFIRMATION,
    FindingKind.DOUBLE_FEE: Label.NEEDS_YOUR_CONFIRMATION,
    FindingKind.DUPLICATE_PAYIN: Label.NEEDS_YOUR_CONFIRMATION,
    FindingKind.TRANSFER_NOT_ON_CARD: Label.NEEDS_YOUR_CONFIRMATION,
    FindingKind.MISSING_EMAIL: Label.NEEDS_YOUR_CONFIRMATION,
    FindingKind.WALLET_BALANCE_MISMATCH: Label.INSUFFICIENT_DATA,
    FindingKind.UNKNOWN_MERCHANT: Label.INSUFFICIENT_DATA,
    FindingKind.SUSPICIOUS_EMAIL: Label.INSUFFICIENT_DATA,
}

# Findings that are informational rather than something to review.
INFORMATIONAL: frozenset[FindingKind] = frozenset({
    FindingKind.RECURRING_SUBSCRIPTION,
})


def label_for(kind: FindingKind) -> Label:
    return KIND_LABEL[kind]


def make_finding(
    kind: FindingKind,
    *,
    params: dict[str, Any],
    sources: list[Source],
    statement_date: date,
    txn_ids: list[str] | None = None,
    amount_cents: int = 0,
    confidence: float = 0.8,
    occurred_on: date | None = None,
    period_key: str = "",
) -> Finding:
    return Finding(
        kind=kind,
        label=label_for(kind),
        confidence=round(confidence, 2),
        params=params,
        sources=sources,
        txn_ids=sorted(txn_ids or []),
        amount_cents=amount_cents,
        period_key=period_key,
        occurred_on=occurred_on,
        statement_date=statement_date,
    )


def deadline_info(finding: Finding, today: date) -> dict[str, Any]:
    """Dispute-window block attached to every finding (WLF-01 rule C)."""
    deadline = finding.dispute_deadline
    days_left = finding.days_left(today)
    return {
        "statement_date": finding.statement_date.isoformat()
        if finding.statement_date else None,
        "dispute_deadline": deadline.isoformat() if deadline else None,
        "days_left": days_left,
        "window_days": DISPUTE_WINDOW_DAYS,
        "expired": bool(days_left is not None and days_left < 0),
    }
