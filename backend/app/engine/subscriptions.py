"""Recurring-subscription detection, next-charge forecast, silent price rises
and "forgot to cancel" candidates (WLF-01 tasks 4 and 6)."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from dateutil.relativedelta import relativedelta

from .email_match import EmailReconResult
from .loader import Dataset
from .merchants import resolve
from .models import (
    CardTxnType,
    EmailMatchStatus,
    Finding,
    FindingKind,
    Source,
    SourceKind,
    TxnType,
)
from .labels import make_finding

MIN_CHARGES = 3
CADENCES: dict[str, dict[str, Any]] = {
    "weekly": {"min": 6, "max": 8, "max_sd": 2.0, "per_year": 52},
    "monthly": {"min": 26, "max": 35, "max_sd": 4.0, "per_year": 12},
    "quarterly": {"min": 85, "max": 95, "max_sd": 6.0, "per_year": 4},
    "yearly": {"min": 350, "max": 380, "max_sd": 10.0, "per_year": 1},
}
# Number of trailing charges with no receipt before we ask the user to confirm
# they still want the subscription.
FORGOTTEN_STREAK = 3


@dataclass
class Charge:
    ref: str
    when: date
    amount_cents: int
    source: SourceKind
    descriptor: str
    has_email: bool = False


@dataclass
class PriceChange:
    from_cents: int
    to_cents: int
    effective_on: date
    ref: str

    @property
    def is_increase(self) -> bool:
        return self.to_cents > self.from_cents


@dataclass
class Subscription:
    merchant_key: str
    merchant_name: str | None
    descriptor: str
    cadence: str
    median_interval_days: float
    interval_sd_days: float
    charges: list[Charge]
    price_changes: list[PriceChange] = field(default_factory=list)

    @property
    def current_amount_cents(self) -> int:
        return abs(self.charges[-1].amount_cents)

    @property
    def first_charge(self) -> date:
        return self.charges[0].when

    @property
    def last_charge(self) -> date:
        return self.charges[-1].when

    @property
    def next_charge(self) -> date:
        last = self.last_charge
        if self.cadence == "weekly":
            return last + relativedelta(days=7)
        if self.cadence == "monthly":
            return last + relativedelta(months=1)
        if self.cadence == "quarterly":
            return last + relativedelta(months=3)
        return last + relativedelta(years=1)

    @property
    def per_year(self) -> int:
        return CADENCES[self.cadence]["per_year"]

    @property
    def annual_cost_cents(self) -> int:
        return self.current_amount_cents * self.per_year

    @property
    def charges_without_receipt(self) -> int:
        """Length of the trailing run of charges with no matching email."""
        streak = 0
        for charge in reversed(self.charges):
            if charge.has_email:
                break
            streak += 1
        return streak

    @property
    def total_paid_cents(self) -> int:
        return sum(abs(c.amount_cents) for c in self.charges)

    def as_dict(self) -> dict[str, Any]:
        return {
            "merchant_key": self.merchant_key,
            "merchant": self.merchant_name,
            "descriptor": self.descriptor,
            "cadence": self.cadence,
            "charge_count": len(self.charges),
            "current_amount_cents": self.current_amount_cents,
            "first_charge": self.first_charge.isoformat(),
            "last_charge": self.last_charge.isoformat(),
            "next_charge": self.next_charge.isoformat(),
            "annual_cost_cents": self.annual_cost_cents,
            "total_paid_cents": self.total_paid_cents,
            "median_interval_days": self.median_interval_days,
            "interval_sd_days": round(self.interval_sd_days, 2),
            "charges_without_receipt": self.charges_without_receipt,
            "price_changes": [
                {
                    "from_cents": p.from_cents,
                    "to_cents": p.to_cents,
                    "effective_on": p.effective_on.isoformat(),
                    "ref": p.ref,
                    "is_increase": p.is_increase,
                }
                for p in self.price_changes
            ],
            "refs": [c.ref for c in self.charges],
        }


def _collect_charges(ds: Dataset, recon: EmailReconResult) -> dict[str, list[Charge]]:
    matched = {
        ref for ref, row in recon.by_ref.items()
        if row.status is EmailMatchStatus.MATCHED
    }
    groups: dict[str, list[Charge]] = {}
    for t in ds.account:
        if t.type is not TxnType.PURCHASE:
            continue
        groups.setdefault(t.merchant_key or t.description, []).append(
            Charge(t.txn_id, t.day, t.amount_cents, SourceKind.STATEMENT,
                   t.description, t.txn_id in matched)
        )
    for c in ds.card:
        if c.type is not CardTxnType.PURCHASE:
            continue
        groups.setdefault(c.merchant_key or c.merchant_raw, []).append(
            Charge(c.card_txn_id, c.day, c.amount_cents, SourceKind.CARD,
                   c.merchant_raw, c.card_txn_id in matched)
        )
    for charges in groups.values():
        charges.sort(key=lambda c: (c.when, c.ref))
    return groups


def _cadence_of(gaps: list[int]) -> tuple[str, float, float] | None:
    if not gaps:
        return None
    median = statistics.median(gaps)
    sd = statistics.pstdev(gaps) if len(gaps) > 1 else 0.0
    for name, spec in CADENCES.items():
        if spec["min"] <= median <= spec["max"] and sd <= spec["max_sd"]:
            return name, median, sd
    return None


def detect(ds: Dataset, recon: EmailReconResult) -> list[Subscription]:
    out: list[Subscription] = []
    for key, charges in _collect_charges(ds, recon).items():
        if len(charges) < MIN_CHARGES:
            continue
        gaps = [(b.when - a.when).days for a, b in zip(charges, charges[1:])]
        cadence = _cadence_of(gaps)
        if cadence is None:
            continue
        name, median, sd = cadence
        merchant = resolve(charges[-1].descriptor)
        changes: list[PriceChange] = []
        for prev, cur in zip(charges, charges[1:]):
            if abs(prev.amount_cents) != abs(cur.amount_cents):
                changes.append(PriceChange(
                    from_cents=abs(prev.amount_cents),
                    to_cents=abs(cur.amount_cents),
                    effective_on=cur.when,
                    ref=cur.ref,
                ))
        out.append(Subscription(
            merchant_key=key,
            merchant_name=merchant.name if merchant else None,
            descriptor=charges[-1].descriptor,
            cadence=name,
            median_interval_days=median,
            interval_sd_days=sd,
            charges=charges,
            price_changes=changes,
        ))
    return sorted(out, key=lambda s: -s.annual_cost_cents)


def _price_notice_email(ds: Dataset, sub: Subscription,
                        change: PriceChange) -> Source | None:
    """Look for the merchant's own notice mentioning both prices."""
    merchant = resolve(sub.descriptor)
    if not merchant:
        return None
    for email in ds.emails:
        if email.from_domain not in merchant.domains:
            continue
        amounts = {abs(a) for a in email.amounts_cents}
        if change.from_cents in amounts and change.to_cents in amounts:
            return Source(SourceKind.EMAIL, email.message_id, email.subject)
    return None


def findings(ds: Dataset, subs: list[Subscription]) -> list[Finding]:
    statement_date = ds.statement_date
    out: list[Finding] = []
    for sub in subs:
        charge_sources = [
            Source(c.source, c.ref, c.descriptor) for c in sub.charges[-3:]
        ]
        out.append(make_finding(
            FindingKind.RECURRING_SUBSCRIPTION,
            params={
                "merchant": sub.merchant_name,
                "descriptor": sub.descriptor,
                "cadence": sub.cadence,
                "amount_cents": sub.current_amount_cents,
                "charge_count": len(sub.charges),
                "first_charge": sub.first_charge.isoformat(),
                "next_charge": sub.next_charge.isoformat(),
                "annual_cost_cents": sub.annual_cost_cents,
            },
            sources=charge_sources,
            statement_date=statement_date,
            txn_ids=[c.ref for c in sub.charges],
            amount_cents=sub.current_amount_cents,
            confidence=round(min(0.99, 0.8 + 0.02 * len(sub.charges)), 2),
            occurred_on=sub.last_charge,
            period_key=f"sub:{sub.merchant_key}",
        ))

        for change in sub.price_changes:
            if not change.is_increase:
                continue
            sources = [Source(SourceKind.CARD if sub.charges[-1].source
                              is SourceKind.CARD else SourceKind.STATEMENT,
                              change.ref, sub.descriptor)]
            notice = _price_notice_email(ds, sub, change)
            if notice:
                sources.append(notice)
            delta = change.to_cents - change.from_cents
            out.append(make_finding(
                FindingKind.PRICE_INCREASE,
                params={
                    "merchant": sub.merchant_name,
                    "descriptor": sub.descriptor,
                    "old_amount_cents": change.from_cents,
                    "new_amount_cents": change.to_cents,
                    "delta_cents": delta,
                    "percent": round(100 * delta / change.from_cents, 1),
                    "effective_on": change.effective_on.isoformat(),
                    "annual_delta_cents": delta * sub.per_year,
                    "notice_email_found": bool(notice),
                },
                sources=sources,
                statement_date=statement_date,
                txn_ids=[change.ref],
                amount_cents=change.to_cents,
                confidence=0.95,
                occurred_on=change.effective_on,
                period_key=f"hike:{sub.merchant_key}:{change.effective_on:%Y-%m}",
            ))

        streak = sub.charges_without_receipt
        if streak >= FORGOTTEN_STREAK:
            unbacked = [c for c in sub.charges if not c.has_email][-streak:]
            out.append(make_finding(
                FindingKind.FORGOTTEN_SUBSCRIPTION,
                params={
                    "merchant": sub.merchant_name,
                    "descriptor": sub.descriptor,
                    "amount_cents": sub.current_amount_cents,
                    "charges_without_receipt": streak,
                    "since": unbacked[0].when.isoformat(),
                    "wasted_if_unused_cents": sum(
                        abs(c.amount_cents) for c in unbacked
                    ),
                    "annual_cost_cents": sub.annual_cost_cents,
                    "next_charge": sub.next_charge.isoformat(),
                },
                sources=[Source(c.source, c.ref, c.descriptor) for c in unbacked[:3]],
                statement_date=statement_date,
                txn_ids=[c.ref for c in unbacked],
                amount_cents=sub.current_amount_cents,
                confidence=0.6,
                occurred_on=sub.last_charge,
                period_key=f"forgotten:{sub.merchant_key}",
            ))
    return out


def forecast(subs: list[Subscription]) -> dict[str, Any]:
    return {
        "count": len(subs),
        "monthly_run_rate_cents": sum(
            s.current_amount_cents * s.per_year // 12 for s in subs
        ),
        "annual_projection_cents": sum(s.annual_cost_cents for s in subs),
        "upcoming": [
            {
                "merchant": s.merchant_name or s.descriptor,
                "descriptor": s.descriptor,
                "next_charge": s.next_charge.isoformat(),
                "amount_cents": s.current_amount_cents,
            }
            for s in sorted(subs, key=lambda s: s.next_charge)
        ],
    }
