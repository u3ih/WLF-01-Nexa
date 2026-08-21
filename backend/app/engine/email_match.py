"""Match each transaction to the email that should explain it, and flag
look-alike senders (WLF-01 task 2).

Every row lands in exactly one of three states: matched / no_email_found /
email_suspicious. We never claim an email is fraudulent — only that its sender
does not line up with the brand it presents.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from .loader import Dataset
from .merchants import ALL_DOMAINS, RULES, Merchant, resolve
from .models import (
    CardTxn,
    CardTxnType,
    EmailMatchStatus,
    EmailMsg,
    SourceKind,
    Txn,
    TxnType,
)

DATE_WINDOW_DAYS = 3
MATCH_THRESHOLD = 0.70
TOKEN_SPLIT = re.compile(r"[^A-Z0-9]+")

# Phrases that pressure the reader. A supporting signal only — never a verdict.
URGENCY_PATTERNS = [
    re.compile(r"within \d+ hours", re.I),
    re.compile(r"\b(suspend|suspended|suspension)\b", re.I),
    re.compile(r"\b(declined|failed)\b.{0,40}\b(payment|card)\b", re.I),
    re.compile(r"\b(verify|confirm|update)\b.{0,25}\b(card|payment|billing)\b", re.I),
]


@dataclass
class MatchRow:
    ref: str
    source: SourceKind
    when: date
    descriptor: str
    merchant: str | None
    amount_cents: int
    status: EmailMatchStatus = EmailMatchStatus.NO_EMAIL_FOUND
    message_id: str | None = None
    email_from: str | None = None
    email_subject: str | None = None
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)


@dataclass
class SuspiciousEmail:
    message_id: str
    from_name: str
    from_addr: str
    reply_to: str | None
    subject: str
    when: date
    claimed_brand: str | None
    amounts_cents: list[int]
    reasons: list[str]
    matched_txn_ref: str | None = None


@dataclass
class EmailReconResult:
    rows: list[MatchRow]
    suspicious: list[SuspiciousEmail]

    @property
    def by_ref(self) -> dict[str, MatchRow]:
        return {r.ref: r for r in self.rows}

    @property
    def matched_count(self) -> int:
        return sum(1 for r in self.rows if r.status is EmailMatchStatus.MATCHED)

    @property
    def missing_count(self) -> int:
        return sum(1 for r in self.rows
                   if r.status is EmailMatchStatus.NO_EMAIL_FOUND)


def _tokens(text: str) -> set[str]:
    return {t for t in TOKEN_SPLIT.split(text.upper()) if len(t) >= 4}


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _brand_from_text(text: str) -> Merchant | None:
    """Which brand does this sender claim to be? Matched on the display name."""
    lowered = text.lower()
    best: Merchant | None = None
    for rule in RULES:
        name = rule.merchant.name.lower()
        head = name.split()[0]
        if len(head) < 4:
            continue
        if head in lowered and (best is None or len(head) > len(best.name.split()[0])):
            best = rule.merchant
    return best


def _domain_core(domain: str) -> str:
    """netfl1x-billing.com -> netfl1xbilling (comparable form)."""
    label = domain.split(".")[0]
    return re.sub(r"[^a-z0-9]", "", label.lower())


def _score(descriptor: str, merchant: Merchant | None, amount_cents: int,
           when: date, email: EmailMsg) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    magnitude = abs(amount_cents)

    if magnitude and magnitude in [abs(a) for a in email.amounts_cents]:
        score += 0.6
        reasons.append("amount_exact")

    delta = abs((email.when.date() - when).days)
    if delta <= DATE_WINDOW_DAYS:
        score += 0.2 * (1 - delta / (DATE_WINDOW_DAYS + 1))
        reasons.append(f"date_within_{delta}d")
    else:
        return 0.0, ["date_out_of_window"]

    haystack = f"{email.from_name} {email.from_addr} {email.subject} {email.body}"
    if merchant and email.from_domain in merchant.domains:
        score += 0.25
        reasons.append("sender_domain_known")
    elif merchant and merchant.name.split()[0].lower() in haystack.lower():
        score += 0.15
        reasons.append("brand_named")
    overlap = _tokens(descriptor) & _tokens(haystack)
    if overlap:
        score += 0.1
        reasons.append("descriptor_tokens:" + ",".join(sorted(overlap)[:3]))

    return round(min(score, 1.0), 3), reasons


def find_suspicious_emails(ds: Dataset) -> list[SuspiciousEmail]:
    out: list[SuspiciousEmail] = []
    all_amounts = [
        (abs(t.amount_cents), t.day, t.txn_id) for t in ds.account
    ] + [
        (abs(c.amount_cents), c.day, c.card_txn_id) for c in ds.card
    ]

    for email in ds.emails:
        reasons: list[str] = []
        claimed = _brand_from_text(f"{email.from_name} {email.subject}")

        if claimed and email.from_domain not in claimed.domains:
            reasons.append("sender_domain_not_registered_for_brand")
            for known in claimed.domains:
                if _levenshtein(_domain_core(email.from_domain),
                                _domain_core(known)) <= 2:
                    reasons.append("lookalike_domain")
                    break
        if (email.reply_to_domain
                and email.reply_to_domain != email.from_domain):
            reasons.append("reply_to_domain_differs")
        if email.from_domain not in ALL_DOMAINS and claimed:
            reasons.append("unrecognised_sender_domain")

        matched_ref = None
        if email.amounts_cents:
            for cents in email.amounts_cents:
                hit = next(
                    (ref for amt, day, ref in all_amounts
                     if amt == abs(cents)
                     and abs((email.when.date() - day).days) <= 5),
                    None,
                )
                if hit:
                    matched_ref = hit
                    break
            if matched_ref is None:
                reasons.append("no_transaction_matches_the_amount")

        if any(p.search(f"{email.subject} {email.body}") for p in URGENCY_PATTERNS):
            reasons.append("pressure_language")

        # Require at least one identity-level signal, not just tone.
        identity_signals = {
            "sender_domain_not_registered_for_brand", "lookalike_domain",
            "reply_to_domain_differs",
        }
        if reasons and identity_signals & set(reasons):
            out.append(SuspiciousEmail(
                message_id=email.message_id,
                from_name=email.from_name,
                from_addr=email.from_addr,
                reply_to=email.reply_to,
                subject=email.subject,
                when=email.when.date(),
                claimed_brand=claimed.name if claimed else None,
                amounts_cents=email.amounts_cents,
                reasons=sorted(set(reasons)),
                matched_txn_ref=matched_ref,
            ))
    return out


def reconcile(ds: Dataset) -> EmailReconResult:
    """Greedy best-first matching: an email can back only one transaction."""
    suspicious = find_suspicious_emails(ds)
    suspicious_ids = {s.message_id for s in suspicious}

    rows: list[MatchRow] = []
    for t in ds.account:
        # Fees are the bank's own lines — they have no third-party receipt.
        if t.type not in (TxnType.PURCHASE, TxnType.PAYOUT, TxnType.PAYIN):
            continue
        rows.append(MatchRow(
            ref=t.txn_id, source=SourceKind.STATEMENT, when=t.day,
            descriptor=t.description, merchant=t.merchant,
            amount_cents=t.amount_cents,
        ))
    for c in ds.card:
        if c.type is not CardTxnType.PURCHASE:
            continue
        rows.append(MatchRow(
            ref=c.card_txn_id, source=SourceKind.CARD, when=c.day,
            descriptor=c.merchant_raw, merchant=c.merchant,
            amount_cents=c.amount_cents,
        ))

    candidates: list[tuple[float, MatchRow, EmailMsg, list[str]]] = []
    by_day: dict[date, list[EmailMsg]] = {}
    for email in ds.emails:
        for offset in range(-DATE_WINDOW_DAYS, DATE_WINDOW_DAYS + 1):
            by_day.setdefault(email.when.date() + timedelta(days=offset), []).append(email)

    for row in rows:
        merchant = resolve(row.descriptor)
        for email in by_day.get(row.when, []):
            score, reasons = _score(row.descriptor, merchant, row.amount_cents,
                                    row.when, email)
            if score >= MATCH_THRESHOLD:
                candidates.append((score, row, email, reasons))

    candidates.sort(key=lambda c: (-c[0], c[1].ref, c[2].message_id))
    used_emails: set[str] = set()
    for score, row, email, reasons in candidates:
        if row.status is EmailMatchStatus.MATCHED or email.message_id in used_emails:
            continue
        used_emails.add(email.message_id)
        row.status = (EmailMatchStatus.EMAIL_SUSPICIOUS
                      if email.message_id in suspicious_ids
                      else EmailMatchStatus.MATCHED)
        row.message_id = email.message_id
        row.email_from = email.from_addr
        row.email_subject = email.subject
        row.score = score
        row.reasons = reasons

    return EmailReconResult(rows=sorted(rows, key=lambda r: (r.when, r.ref)),
                            suspicious=suspicious)


def summary(result: EmailReconResult) -> dict[str, Any]:
    return {
        "total": len(result.rows),
        "matched": result.matched_count,
        "no_email_found": result.missing_count,
        "email_suspicious": sum(
            1 for r in result.rows if r.status is EmailMatchStatus.EMAIL_SUSPICIOUS
        ),
        "suspicious_emails": len(result.suspicious),
    }
