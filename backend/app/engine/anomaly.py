"""Duplicate charges, duplicated fees, unidentified merchants, high-value
charges with no receipt, and advanced anomaly detection (WLF-01 task 4).

Implements all detection rules from the reconciliation & control principles:
  - Exact & suspected duplicates (doc §5)
  - Off-hours transactions, rapid spending (doc §8)
  - Spending spike, category concentration (doc §9)
  - Late refunds
  - Subscription lifecycle checks (doc §7):
    no welcome email, charged after cancel, free trial converted
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from .classify import wallet_only_events
from .email_match import EmailReconResult
from .loader import Dataset
from .merchants import normalize_descriptor, processor_hint, resolve
from .models import (
    CardTxn,
    CardTxnType,
    EmailMatchStatus,
    Finding,
    FindingKind,
    Source,
    SourceKind,
    Txn,
    TxnType,
    WalletEvent,
)
from .labels import make_finding

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

# Exact duplicate: same merchant_key + same amount within this window.
DUPLICATE_WINDOW_SECONDS = 15 * 60

# Suspected duplicate: similar descriptors, amount tolerance, 24h window.
SUSPECTED_DUP_DESCRIPTOR_SIMILARITY = 0.80
SUSPECTED_DUP_AMOUNT_TOLERANCE = 0.15
SUSPECTED_DUP_WINDOW_SECONDS = 24 * 60 * 60

# Off-hours: transactions between 23:00 and 06:00.
OFF_HOURS_START = 23
OFF_HOURS_END = 6

# Rapid spending: >=3 purchases within 30 minutes.
RAPID_SPEND_COUNT = 3
RAPID_SPEND_WINDOW_MINUTES = 30

# Category concentration: a single category exceeds 60% of total spend.
CATEGORY_CONCENTRATION_THRESHOLD = 0.60

# Spending spike: >1.5x previous month or >2 sigma above rolling mean.
SPENDING_SPIKE_MULTIPLIER = 1.50
SPENDING_SPIKE_STDDEV = 2.0

# High-value threshold for "no receipt" — 90th percentile.
MISSING_EMAIL_PERCENTILE = 0.90

# Late refund: refund arriving >30 days after original charge.
LATE_REFUND_DAYS = 30

# Free trial: typical max trial duration.
FREE_TRIAL_MAX_DAYS = 45


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

@dataclass
class _Charge:
    ref: str
    when: Any               # datetime
    amount_cents: int
    descriptor: str
    merchant_key: str
    source: SourceKind
    currency: str = "USD"


def _purchases(ds: Dataset) -> list[_Charge]:
    out = [
        _Charge(t.txn_id, t.when, t.amount_cents, t.description,
                t.merchant_key or t.description, SourceKind.STATEMENT,
                t.currency)
        for t in ds.account if t.type is TxnType.PURCHASE and t.is_settled
    ]
    out += [
        _Charge(c.card_txn_id, c.when, c.amount_cents, c.merchant_raw,
                c.merchant_key or c.merchant_raw, SourceKind.CARD, c.currency)
        for c in ds.card if c.type is CardTxnType.PURCHASE and c.is_settled
    ]
    return sorted(out, key=lambda c: (c.when, c.ref))


def _levenshtein_ratio(a: str, b: str) -> float:
    """Normalised similarity (1.0 = identical)."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    dist = prev[-1]
    max_len = max(len(a), len(b))
    return 1.0 - (dist / max_len) if max_len else 1.0


def _normalised(descriptor: str) -> str:
    return normalize_descriptor(descriptor).upper()


def purchase_p90_cents(ds: Dataset, currency: str | None = None) -> int:
    charges = _purchases(ds)
    if currency is not None:
        charges = [c for c in charges if c.currency == currency]
    magnitudes = sorted(abs(c.amount_cents) for c in charges)
    if not magnitudes:
        return 0
    index = min(len(magnitudes) - 1,
                int(len(magnitudes) * MISSING_EMAIL_PERCENTILE))
    return magnitudes[index]


# ---------------------------------------------------------------------------
# 1. Exact duplicate charges
# ---------------------------------------------------------------------------

def duplicate_charges(ds: Dataset) -> list[Finding]:
    """Same merchant, same amount, minutes apart."""
    statement_date = ds.statement_date
    groups: dict[tuple[str, int, str], list[_Charge]] = defaultdict(list)
    for charge in _purchases(ds):
        groups[(charge.merchant_key, abs(charge.amount_cents),
                charge.currency)].append(charge)

    out: list[Finding] = []
    for (merchant_key, amount, currency), charges in groups.items():
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
                    "currency": currency,
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
                period_key=f"dup:{merchant_key}:{currency}:{first.when:%Y-%m-%d}",
            ))
    return out


# ---------------------------------------------------------------------------
# 2. Suspected duplicate (fuzzy match — doc §5)
# ---------------------------------------------------------------------------

def suspected_duplicates(ds: Dataset) -> list[Finding]:
    """Charges with similar descriptors and amounts within 24h."""
    statement_date = ds.statement_date
    charges = _purchases(ds)
    out: list[Finding] = []
    seen: set[tuple[str, str]] = set()

    for i, a in enumerate(charges):
        for b in charges[i + 1:]:
            gap = (b.when - a.when).total_seconds()
            if gap > SUSPECTED_DUP_WINDOW_SECONDS:
                continue
            if a.merchant_key == b.merchant_key:
                continue
            pair = frozenset({a.ref, b.ref})
            if pair in seen:
                continue
            seen.add(pair)

            amt_a = abs(a.amount_cents)
            amt_b = abs(b.amount_cents)
            if amt_a == 0 and amt_b == 0:
                continue
            ratio = min(amt_a, amt_b) / max(amt_a, amt_b)
            if ratio < (1.0 - SUSPECTED_DUP_AMOUNT_TOLERANCE):
                continue

            norm_a = _normalised(a.descriptor)
            norm_b = _normalised(b.descriptor)
            similarity = _levenshtein_ratio(norm_a, norm_b)
            if similarity < SUSPECTED_DUP_DESCRIPTOR_SIMILARITY:
                continue

            merchant_a = resolve(a.descriptor)
            merchant_b = resolve(b.descriptor)
            out.append(make_finding(
                FindingKind.SUSPECTED_DUPLICATE,
                params={
                    "descriptor_a": a.descriptor,
                    "descriptor_b": b.descriptor,
                    "merchant_a": merchant_a.name if merchant_a else None,
                    "merchant_b": merchant_b.name if merchant_b else None,
                    "amount_a_cents": amt_a,
                    "amount_b_cents": amt_b,
                    "seconds_apart": int(gap),
                    "similarity": round(similarity, 3),
                    "occurred_on": a.when.date().isoformat(),
                },
                sources=[
                    Source(a.source, a.ref, a.descriptor),
                    Source(b.source, b.ref, b.descriptor),
                ],
                statement_date=statement_date,
                txn_ids=[a.ref, b.ref],
                amount_cents=max(amt_a, amt_b),
                confidence=round(0.4 + similarity * 0.3, 2),
                occurred_on=a.when.date(),
                period_key=f"susdup:{a.ref}:{b.ref}",
            ))
    return out


# ---------------------------------------------------------------------------
# 3. Off-hours transaction (doc §8)
# ---------------------------------------------------------------------------

def off_hours_transactions(ds: Dataset) -> list[Finding]:
    """Flag purchases made outside normal waking hours (23:00-06:00)."""
    statement_date = ds.statement_date
    out: list[Finding] = []

    for charge in _purchases(ds):
        hour = charge.when.hour
        if OFF_HOURS_START <= hour or hour <= OFF_HOURS_END:
            merchant = resolve(charge.descriptor)
            out.append(make_finding(
                FindingKind.OFF_HOURS_TXN,
                params={
                    "merchant": merchant.name if merchant else None,
                    "descriptor": charge.descriptor,
                    "amount_cents": abs(charge.amount_cents),
                    "occurred_on": charge.when.date().isoformat(),
                    "time": charge.when.strftime("%H:%M"),
                    "hour": hour,
                },
                sources=[Source(charge.source, charge.ref, charge.descriptor)],
                statement_date=statement_date,
                txn_ids=[charge.ref],
                amount_cents=abs(charge.amount_cents),
                confidence=0.4,
                occurred_on=charge.when.date(),
                period_key=f"offhr:{charge.ref}",
            ))
    return out


# ---------------------------------------------------------------------------
# 4. Rapid spending (doc §8)
# ---------------------------------------------------------------------------

def rapid_spending(ds: Dataset) -> list[Finding]:
    """Multiple purchases in quick succession (>=3 within 30 minutes)."""
    statement_date = ds.statement_date
    charges = _purchases(ds)
    out: list[Finding] = []

    for i in range(len(charges)):
        window: list[_Charge] = [charges[i]]
        for j in range(i + 1, len(charges)):
            gap = (charges[j].when - charges[i].when).total_seconds()
            if gap > RAPID_SPEND_WINDOW_MINUTES * 60:
                break
            window.append(charges[j])

        if len(window) < RAPID_SPEND_COUNT:
            continue
        if i > 0:
            prev_gap = (charges[i].when - charges[i - 1].when).total_seconds()
            if prev_gap <= RAPID_SPEND_WINDOW_MINUTES * 60:
                continue

        total = sum(abs(c.amount_cents) for c in window)
        merchants = list(dict.fromkeys(
            resolve(c.descriptor).name if resolve(c.descriptor) else c.descriptor
            for c in window
        ))
        out.append(make_finding(
            FindingKind.RAPID_SPENDING,
            params={
                "count": len(window),
                "total_cents": total,
                "window_minutes": RAPID_SPEND_WINDOW_MINUTES,
                "merchants": merchants[:5],
                "first_time": window[0].when.isoformat(timespec="seconds"),
                "last_time": window[-1].when.isoformat(timespec="seconds"),
                "occurred_on": window[0].when.date().isoformat(),
            },
            sources=[Source(c.source, c.ref, c.descriptor) for c in window],
            statement_date=statement_date,
            txn_ids=[c.ref for c in window],
            amount_cents=total,
            confidence=0.55,
            occurred_on=window[0].when.date(),
            period_key=f"rapid:{window[0].when.date()}:{window[0].ref}",
        ))
    return out


# ---------------------------------------------------------------------------
# 5. Spending spike — period-over-period (doc §9)
# ---------------------------------------------------------------------------

def spending_spike(ds: Dataset) -> list[Finding]:
    """Detect months where total spend significantly exceeds the rolling
    average — both absolute (mean + N*sigma) and relative (>50% vs previous)."""
    statement_date = ds.statement_date
    out: list[Finding] = []

    monthly: dict[str, int] = defaultdict(int)
    for charge in _purchases(ds):
        key = charge.when.strftime("%Y-%m")
        monthly[key] += abs(charge.amount_cents)

    if len(monthly) < 2:
        return out

    sorted_months = sorted(monthly.items())
    current_key, current_spend = sorted_months[-1]
    prev_values = [v for k, v in sorted_months[:-1]]
    mean = statistics.mean(prev_values)
    stdev = statistics.stdev(prev_values) if len(prev_values) >= 2 else 0

    spike_abs = stdev > 0 and current_spend > (mean + SPENDING_SPIKE_STDDEV * stdev)
    prev_month_key, prev_month_spend = sorted_months[-2]
    spike_rel = (prev_month_spend > 0 and
                 current_spend > prev_month_spend * SPENDING_SPIKE_MULTIPLIER)

    if spike_abs or spike_rel:
        cause = []
        if spike_abs:
            over = (current_spend - mean) / stdev if stdev else 0
            cause.append(f"{over:.1f}sigma above mean")
        if spike_rel:
            pct = (current_spend - prev_month_spend) / prev_month_spend * 100
            cause.append(f"{pct:.0f}% increase from {prev_month_key}")

        current_charges = [c for c in _purchases(ds)
                           if c.when.strftime("%Y-%m") == current_key]
        top_merchants: dict[str, int] = defaultdict(int)
        for c in current_charges:
            name = resolve(c.descriptor)
            key = name.name if name else c.descriptor
            top_merchants[key] += abs(c.amount_cents)
        top_3 = sorted(top_merchants.items(), key=lambda x: -x[1])[:3]

        out.append(make_finding(
            FindingKind.SPENDING_SPIKE,
            params={
                "period": current_key,
                "spend_cents": current_spend,
                "previous_period": prev_month_key,
                "previous_spend_cents": prev_month_spend,
                "mean_cents": int(mean),
                "stddev_cents": int(stdev),
                "multiplier": round(current_spend / prev_month_spend, 2)
                if prev_month_spend else None,
                "top_merchants": [{"name": m, "amount_cents": a}
                                  for m, a in top_3],
                "reasons": cause,
                "month_count": len(sorted_months),
            },
            sources=[Source(SourceKind.STATEMENT, "monthly_aggregate",
                            f"spend in {current_key}"),
                     Source(SourceKind.STATEMENT, "monthly_aggregate",
                            f"spend in {prev_month_key}")],
            statement_date=statement_date,
            txn_ids=[],
            amount_cents=current_spend - prev_month_spend,
            confidence=0.65 if spike_abs and spike_rel else 0.5,
            occurred_on=date.fromisoformat(f"{current_key}-01"),
            period_key=f"spike:{current_key}",
        ))
    return out


# ---------------------------------------------------------------------------
# 6. Category concentration (doc §9)
# ---------------------------------------------------------------------------

def category_concentration(ds: Dataset) -> list[Finding]:
    """Flag when a single merchant category accounts for an abnormally large
    share of total spending in the statement period."""
    statement_date = ds.statement_date
    out: list[Finding] = []

    category_totals: dict[str, int] = defaultdict(int)
    charge_by_cat: dict[str, list[_Charge]] = defaultdict(list)

    for charge in _purchases(ds):
        merchant = resolve(charge.descriptor)
        cat = merchant.category if merchant else "unknown"
        category_totals[cat] += abs(charge.amount_cents)
        charge_by_cat[cat].append(charge)

    total_spend = sum(category_totals.values())
    if total_spend == 0:
        return out

    for cat, cat_total in category_totals.items():
        share = cat_total / total_spend
        if share >= CATEGORY_CONCENTRATION_THRESHOLD:
            cat_charges = charge_by_cat[cat]
            top_merchants: dict[str, int] = defaultdict(int)
            for c in cat_charges:
                m = resolve(c.descriptor)
                key = m.name if m else c.descriptor
                top_merchants[key] += abs(c.amount_cents)
            top_3 = sorted(top_merchants.items(), key=lambda x: -x[1])[:3]

            out.append(make_finding(
                FindingKind.CATEGORY_CONCENTRATION,
                params={
                    "category": cat,
                    "category_cents": cat_total,
                    "total_cents": total_spend,
                    "share": round(share, 3),
                    "percent": round(share * 100, 1),
                    "charge_count": len(cat_charges),
                    "top_merchants": [{"name": m, "amount_cents": a}
                                      for m, a in top_3],
                },
                sources=[Source(c.source, c.ref, c.descriptor)
                         for c in cat_charges[:5]],
                statement_date=statement_date,
                txn_ids=[c.ref for c in cat_charges],
                amount_cents=cat_total,
                confidence=0.5,
                occurred_on=statement_date,
                period_key=f"concentration:{cat}:{statement_date:%Y-%m}",
            ))
    return out


# ---------------------------------------------------------------------------
# 7. Late refund (doc §8)
# ---------------------------------------------------------------------------

def late_refunds(ds: Dataset) -> list[Finding]:
    """A refund arriving well after the original charge (>30 days)."""
    statement_date = ds.statement_date
    out: list[Finding] = []

    refunds: list[Txn] = [t for t in ds.account if t.type is TxnType.REFUND]
    purchases: list[Txn] = [t for t in ds.account
                            if t.type is TxnType.PURCHASE and t.amount_cents < 0]

    for refund in refunds:
        refund_amount = abs(refund.amount_cents)
        if refund_amount == 0:
            continue

        best_match: Txn | None = None
        best_gap = timedelta.max
        for purchase in purchases:
            if abs(purchase.amount_cents) >= refund_amount * 0.8:
                gap = refund.day - purchase.day
                if gap >= timedelta(days=LATE_REFUND_DAYS) and gap < best_gap:
                    best_match = purchase
                    best_gap = gap

        if best_match is not None:
            merchant = resolve(best_match.description)
            out.append(make_finding(
                FindingKind.LATE_REFUND,
                params={
                    "merchant": merchant.name if merchant else None,
                    "descriptor": best_match.description,
                    "refund_amount_cents": refund_amount,
                    "original_amount_cents": abs(best_match.amount_cents),
                    "purchased_on": best_match.day.isoformat(),
                    "refunded_on": refund.day.isoformat(),
                    "days_late": best_gap.days,
                    "threshold_days": LATE_REFUND_DAYS,
                },
                sources=[
                    Source(SourceKind.STATEMENT, refund.txn_id,
                           f"refund on {refund.day}"),
                    Source(SourceKind.STATEMENT, best_match.txn_id,
                           f"purchase on {best_match.day}"),
                ],
                statement_date=statement_date,
                txn_ids=[refund.txn_id, best_match.txn_id],
                amount_cents=refund_amount,
                confidence=0.5,
                occurred_on=refund.day,
                period_key=f"laterefund:{refund.txn_id}",
            ))
    return out


# ---------------------------------------------------------------------------
# 8. Subscription lifecycle checks (doc §7)
# ---------------------------------------------------------------------------

def _subscription_first_charge_no_welcome(
    ds: Dataset,
    recon: EmailReconResult,
) -> list[Finding]:
    """First subscription charge with no welcome / receipt email at all."""
    statement_date = ds.statement_date
    out: list[Finding] = []

    by_merchant: dict[str, list[_Charge]] = defaultdict(list)
    for charge in _purchases(ds):
        by_merchant[charge.merchant_key].append(charge)

    for merchant_key, charges in by_merchant.items():
        charges.sort(key=lambda c: c.when)
        if len(charges) < 2:
            continue
        first = charges[0]

        match_row = recon.by_ref.get(first.ref)
        has_email = (match_row is not None and
                     match_row.status is EmailMatchStatus.MATCHED)

        if not has_email:
            merchant = resolve(first.descriptor)
            out.append(make_finding(
                FindingKind.SUBSCRIPTION_NO_WELCOME,
                params={
                    "merchant": merchant.name if merchant else None,
                    "descriptor": first.descriptor,
                    "amount_cents": abs(first.amount_cents),
                    "occurred_on": first.when.date().isoformat(),
                    "charge_count": len(charges),
                    "last_charge": charges[-1].when.date().isoformat(),
                },
                sources=[
                    Source(first.source, first.ref, first.descriptor),
                    Source(SourceKind.EMAIL, "mailbox",
                           "no welcome / receipt email found"),
                ],
                statement_date=statement_date,
                txn_ids=[first.ref],
                amount_cents=abs(first.amount_cents),
                confidence=0.4,
                occurred_on=first.when.date(),
                period_key=f"subnowelcome:{merchant_key}",
            ))
    return out


def _charged_after_cancel(ds: Dataset) -> list[Finding]:
    """Detect a charge after a long gap (>45 days) suggesting a cancelled
    subscription that restarted or was never fully stopped."""
    statement_date = ds.statement_date
    out: list[Finding] = []

    by_merchant: dict[str, list[_Charge]] = defaultdict(list)
    for charge in _purchases(ds):
        by_merchant[charge.merchant_key].append(charge)

    for merchant_key, charges in by_merchant.items():
        charges.sort(key=lambda c: c.when)
        if len(charges) < 3:
            continue

        for i in range(len(charges) - 1):
            gap = (charges[i + 1].when - charges[i].when).days
            if gap > 45:
                merchant = resolve(charges[i + 1].descriptor)
                out.append(make_finding(
                    FindingKind.CHARGED_AFTER_CANCEL,
                    params={
                        "merchant": merchant.name if merchant else None,
                        "descriptor": charges[i + 1].descriptor,
                        "amount_cents": abs(charges[i + 1].amount_cents),
                        "previous_charge": charges[i].when.date().isoformat(),
                        "this_charge": charges[i + 1].when.date().isoformat(),
                        "gap_days": gap,
                        "merchant_key": merchant_key,
                    },
                    sources=[
                        Source(charges[i + 1].source, charges[i + 1].ref,
                               charges[i + 1].descriptor),
                        Source(charges[i].source, charges[i].ref,
                               f"last charge before {gap}-day gap"),
                    ],
                    statement_date=statement_date,
                    txn_ids=[charges[i + 1].ref],
                    amount_cents=abs(charges[i + 1].amount_cents),
                    confidence=0.5,
                    occurred_on=charges[i + 1].when.date(),
                    period_key=f"aftercancel:{merchant_key}:{charges[i+1].when.date()}",
                ))
    return out


def _free_trial_converted(ds: Dataset) -> list[Finding]:
    """First paid charge after a smaller-amount charge — classic free-trial-
    to-paid conversion signal."""
    statement_date = ds.statement_date
    out: list[Finding] = []

    by_merchant: dict[str, list[_Charge]] = defaultdict(list)
    for charge in _purchases(ds):
        by_merchant[charge.merchant_key].append(charge)

    for merchant_key, charges in by_merchant.items():
        charges.sort(key=lambda c: c.when)
        if len(charges) < 2:
            continue

        first_amt = abs(charges[0].amount_cents)
        second_amt = abs(charges[1].amount_cents)

        if first_amt > 0 and second_amt > first_amt * 1.5:
            gap = (charges[1].when - charges[0].when).days
            if gap <= FREE_TRIAL_MAX_DAYS:
                merchant = resolve(charges[1].descriptor)
                out.append(make_finding(
                    FindingKind.FREE_TRIAL_CONVERTED,
                    params={
                        "merchant": merchant.name if merchant else None,
                        "descriptor": charges[1].descriptor,
                        "trial_amount_cents": first_amt,
                        "paid_amount_cents": second_amt,
                        "trial_start": charges[0].when.date().isoformat(),
                        "converted_on": charges[1].when.date().isoformat(),
                        "trial_days": gap,
                    },
                    sources=[
                        Source(charges[1].source, charges[1].ref,
                               charges[1].descriptor),
                        Source(charges[0].source, charges[0].ref,
                               f"trial charge on {charges[0].when.date()}"),
                    ],
                    statement_date=statement_date,
                    txn_ids=[charges[0].ref, charges[1].ref],
                    amount_cents=second_amt,
                    confidence=0.55,
                    occurred_on=charges[1].when.date(),
                    period_key=f"freetrial:{merchant_key}:{charges[1].when.date()}",
                ))
    return out


def _source_kind_of(obj: Any) -> SourceKind:
    """Return the SourceKind for any row type in double_fees."""
    if isinstance(obj, WalletEvent):
        return SourceKind.WALLET
    if hasattr(obj, "ledger"):
        return obj.ledger       # CardTxn — already stores SourceKind
    return SourceKind.STATEMENT  # Txn


def double_fees(ds: Dataset) -> list[Finding]:
    """The same fee, same amount, same day, more than once."""
    statement_date = ds.statement_date
    groups: dict[tuple[str, int, date, str], list] = defaultdict(list)
    for t in ds.account:
        if t.type is not TxnType.FEE or not t.is_settled:
            continue
        groups[(normalize_descriptor(t.description), abs(t.amount_cents),
                t.day, t.currency)].append(t)
    for c in ds.card:
        if c.type is not CardTxnType.FEE or not c.is_settled:
            continue
        groups[(normalize_descriptor(c.merchant_raw), abs(c.amount_cents),
                c.day, c.currency)].append(c)
    # A fee charged straight to the wallet appears on no other ledger, so it
    # has to be checked here or a duplicated one is never seen.
    for e in wallet_only_events(ds):
        if e.note != "fee" or not e.is_settled:
            continue
        groups[(normalize_descriptor(e.descriptor or e.note), e.amount_cents,
                e.day, e.currency)].append(e)

    out: list[Finding] = []
    for (descriptor, amount, day, currency), rows in sorted(groups.items()):
        if len(rows) < 2:
            continue
        refs = [getattr(r, "txn_id", None) or getattr(r, "card_txn_id", None)
                or r.event_id for r in rows]
        out.append(make_finding(
            FindingKind.DOUBLE_FEE,
            params={
                "descriptor": descriptor,
                "amount_cents": amount,
                "currency": currency,
                "count": len(rows),
                "total_cents": amount * len(rows),
                "occurred_on": day.isoformat(),
            },
            sources=[
                Source(_source_kind_of(r), ref, descriptor)
                for r, ref in zip(rows, refs)
            ],
            statement_date=statement_date,
            txn_ids=refs,
            amount_cents=amount * (len(rows) - 1),
            confidence=0.85,
            occurred_on=day,
            period_key=f"fee:{descriptor}:{currency}:{day.isoformat()}",
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
    purchases = _purchases(ds)
    # One threshold per currency: a euro charge judged against a dollar
    # percentile would flag or excuse it for the wrong reason.
    thresholds = {c.currency: purchase_p90_cents(ds, c.currency)
                  for c in purchases}
    purchase_refs = {c.ref: c for c in purchases}

    out: list[Finding] = []
    for row in recon.rows:
        if row.ref not in purchase_refs:
            continue
        if row.status is not EmailMatchStatus.NO_EMAIL_FOUND:
            continue
        charge = purchase_refs[row.ref]
        threshold = thresholds.get(charge.currency, 0)
        if abs(row.amount_cents) < threshold:
            continue
        merchant = resolve(charge.descriptor)
        out.append(make_finding(
            FindingKind.MISSING_EMAIL,
            params={
                "merchant": merchant.name if merchant else None,
                "descriptor": charge.descriptor,
                "amount_cents": abs(charge.amount_cents),
                "currency": charge.currency,
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
    """Run every detector and return all findings."""
    return (
        duplicate_charges(ds)
        + suspected_duplicates(ds)
        + double_fees(ds)
        + unknown_merchants(ds)
        + missing_receipts(ds, recon)
        + suspicious_email_findings(ds, recon)
        + off_hours_transactions(ds)
        + rapid_spending(ds)
        + spending_spike(ds)
        + category_concentration(ds)
        + late_refunds(ds)
        + _subscription_first_charge_no_welcome(ds, recon)
        + _charged_after_cancel(ds)
        + _free_trial_converted(ds)
    )


def stats(ds: Dataset) -> dict[str, Any]:
    magnitudes = [abs(c.amount_cents) for c in _purchases(ds)]
    return {
        "purchase_count": len(magnitudes),
        "purchase_p90_cents": purchase_p90_cents(ds),
        "purchase_median_cents": int(statistics.median(magnitudes)) if magnitudes else 0,
    }
