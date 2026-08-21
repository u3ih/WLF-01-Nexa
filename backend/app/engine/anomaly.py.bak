"""Duplicate charges, duplicated fees, unidentified merchants and high-value
charges with no receipt (WLF-01 task 4)."""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

from .email_match import EmailReconResult
from .loader import Dataset
from .merchants import normalize_descriptor, processor_hint, resolve
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

# Two identical charges closer together than this are worth a look.
DUPLICATE_WINDOW_SECONDS = 15 * 60
# High-value threshold for "no receipt anywhere" — the 90th percentile of the
# user's own purchases, so it adapts to the person rather than a fixed number.
MISSING_EMAIL_PERCENTILE = 0.90


@dataclass
class _Charge:
    ref: str
    when: Any               # datetime
    amount_cents: int
    descriptor: str
    merchant_key: str
    source: SourceKind


def _purchases(ds: Dataset) -> list[_Charge]:
    out = [
        _Charge(t.txn_id, t.when, t.amount_cents, t.description,
                t.merchant_key or t.description, SourceKind.STATEMENT)
        for t in ds.account if t.type is TxnType.PURCHASE
    ]
    out += [
        _Charge(c.card_txn_id, c.when, c.amount_cents, c.merchant_raw,
                c.merchant_key or c.merchant_raw, SourceKind.CARD)
        for c in ds.card if c.type is CardTxnType.PURCHASE
    ]
    return sorted(out, key=lambda c: (c.when, c.ref))


def purchase_p90_cents(ds: Dataset) -> int:
    magnitudes = sorted(abs(c.amount_cents) for c in _purchases(ds))
    if not magnitudes:
        return 0
    index = min(len(magnitudes) - 1,
                int(len(magnitudes) * MISSING_EMAIL_PERCENTILE))
    return magnitudes[index]


def duplicate_charges(ds: Dataset) -> list[Finding]:
    """Same merchant, same amount, minutes apart."""
    statement_date = ds.statement_date
    groups: dict[tuple[str, int], list[_Charge]] = defaultdict(list)
    for charge in _purchases(ds):
        groups[(charge.merchant_key, abs(charge.amount_cents))].append(charge)

    out: list[Finding] = []
    for (merchant_key, amount), charges in groups.items():
        charges.sort(key=lambda c: c.when)
        for first, second in zip(charges, charges[1:]):
            gap = (second.when - first.when).total_seconds()
            if gap > DUPLICATE_WINDOW_SECONDS:
                continue
            merchant = resolve(first.descriptor)
            out.append(make_finding(
                FindingKind.DUPLICATE_CHARGE,
                params={
                    "merchant": merchant.name if merchant else None,
                    "descriptor": first.descriptor,
                    "amount_cents": amount,
                    "seconds_apart": int(gap),
                    "occurred_on": first.when.date().isoformat(),
                    "first_time": first.when.isoformat(timespec="seconds"),
                    "second_time": second.when.isoformat(timespec="seconds"),
                },
                sources=[
                    Source(first.source, first.ref, first.descriptor),
                    Source(second.source, second.ref, second.descriptor),
                ],
                statement_date=statement_date,
                txn_ids=[first.ref, second.ref],
                amount_cents=amount,
                confidence=0.85,
                occurred_on=first.when.date(),
                period_key=f"dup:{merchant_key}:{first.when:%Y-%m-%d}",
            ))
    return out


def double_fees(ds: Dataset) -> list[Finding]:
    """The same fee, same amount, same day, more than once."""
    statement_date = ds.statement_date
    groups: dict[tuple[str, int, date], list] = defaultdict(list)
    for t in ds.account:
        if t.type is not TxnType.FEE:
            continue
        groups[(normalize_descriptor(t.description), abs(t.amount_cents),
                t.day)].append(t)
    for c in ds.card:
        if c.type is not CardTxnType.FEE:
            continue
        groups[(normalize_descriptor(c.merchant_raw), abs(c.amount_cents),
                c.day)].append(c)

    out: list[Finding] = []
    for (descriptor, amount, day), rows in sorted(groups.items()):
        if len(rows) < 2:
            continue
        refs = [getattr(r, "txn_id", None) or r.card_txn_id for r in rows]
        out.append(make_finding(
            FindingKind.DOUBLE_FEE,
            params={
                "descriptor": descriptor,
                "amount_cents": amount,
                "count": len(rows),
                "total_cents": amount * len(rows),
                "occurred_on": day.isoformat(),
            },
            sources=[
                Source(SourceKind.STATEMENT if hasattr(r, "txn_id")
                       else SourceKind.CARD, ref, descriptor)
                for r, ref in zip(rows, refs)
            ],
            statement_date=statement_date,
            txn_ids=refs,
            amount_cents=amount * (len(rows) - 1),
            confidence=0.85,
            occurred_on=day,
            period_key=f"fee:{descriptor}:{day.isoformat()}",
        ))
    return out


def unknown_merchants(ds: Dataset) -> list[Finding]:
    """Descriptors the dictionary cannot resolve. We explain the processor
    prefix when we recognise it, and otherwise say so plainly — never guess."""
    statement_date = ds.statement_date
    groups: dict[str, list[_Charge]] = defaultdict(list)
    for charge in _purchases(ds):
        if resolve(charge.descriptor) is None:
            groups[normalize_descriptor(charge.descriptor)].append(charge)

    out: list[Finding] = []
    for descriptor, charges in sorted(groups.items()):
        total = sum(abs(c.amount_cents) for c in charges)
        latest = charges[-1]
        out.append(make_finding(
            FindingKind.UNKNOWN_MERCHANT,
            params={
                "descriptor": latest.descriptor,
                "normalized": descriptor,
                "processor_hint": processor_hint(latest.descriptor),
                "charge_count": len(charges),
                "amount_cents": abs(latest.amount_cents),
                "total_cents": total,
                "occurred_on": latest.when.date().isoformat(),
            },
            sources=[Source(c.source, c.ref, c.descriptor) for c in charges[-3:]],
            statement_date=statement_date,
            txn_ids=[c.ref for c in charges],
            amount_cents=abs(latest.amount_cents),
            confidence=0.5,
            occurred_on=latest.when.date(),
            period_key=f"unknown:{descriptor}",
        ))
    return out


def missing_receipts(ds: Dataset, recon: EmailReconResult) -> list[Finding]:
    """High-value purchases with no email anywhere in the mailbox."""
    statement_date = ds.statement_date
    threshold = purchase_p90_cents(ds)
    purchase_refs = {c.ref: c for c in _purchases(ds)}

    out: list[Finding] = []
    for row in recon.rows:
        if row.ref not in purchase_refs:
            continue
        if row.status is not EmailMatchStatus.NO_EMAIL_FOUND:
            continue
        if abs(row.amount_cents) < threshold:
            continue
        charge = purchase_refs[row.ref]
        merchant = resolve(charge.descriptor)
        out.append(make_finding(
            FindingKind.MISSING_EMAIL,
            params={
                "merchant": merchant.name if merchant else None,
                "descriptor": charge.descriptor,
                "amount_cents": abs(charge.amount_cents),
                "occurred_on": charge.when.date().isoformat(),
                "threshold_cents": threshold,
                "mailbox_searched": True,
            },
            sources=[Source(charge.source, charge.ref, charge.descriptor)],
            statement_date=statement_date,
            txn_ids=[charge.ref],
            amount_cents=abs(charge.amount_cents),
            confidence=0.7,
            occurred_on=charge.when.date(),
            period_key=f"noemail:{charge.ref}",
        ))
    return out


def suspicious_email_findings(ds: Dataset, recon: EmailReconResult) -> list[Finding]:
    statement_date = ds.statement_date
    out: list[Finding] = []
    for item in recon.suspicious:
        out.append(make_finding(
            FindingKind.SUSPICIOUS_EMAIL,
            params={
                "from_name": item.from_name,
                "from_addr": item.from_addr,
                "reply_to": item.reply_to,
                "subject": item.subject,
                "claimed_brand": item.claimed_brand,
                "amount_cents": abs(item.amounts_cents[0])
                if item.amounts_cents else 0,
                "received_on": item.when.isoformat(),
                "reasons": item.reasons,
                "matched_txn_ref": item.matched_txn_ref,
            },
            sources=[Source(SourceKind.EMAIL, item.message_id, item.subject)],
            statement_date=statement_date,
            txn_ids=[],
            amount_cents=abs(item.amounts_cents[0]) if item.amounts_cents else 0,
            confidence=0.55,
            occurred_on=item.when,
            period_key=f"phish:{item.message_id}",
        ))
    return out


def detect(ds: Dataset, recon: EmailReconResult) -> list[Finding]:
    return (
        duplicate_charges(ds)
        + double_fees(ds)
        + unknown_merchants(ds)
        + missing_receipts(ds, recon)
        + suspicious_email_findings(ds, recon)
    )


def stats(ds: Dataset) -> dict[str, Any]:
    magnitudes = [abs(c.amount_cents) for c in _purchases(ds)]
    return {
        "purchase_count": len(magnitudes),
        "purchase_p90_cents": purchase_p90_cents(ds),
        "purchase_median_cents": int(statistics.median(magnitudes)) if magnitudes else 0,
    }
