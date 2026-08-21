"""Core data structures for the Nexa statement-audit engine.

Money is stored as integer cents so every total is exact; use `parse_money`
and `fmt_money` at the boundaries (CSV in, JSON/UI out).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any

DISPUTE_WINDOW_DAYS = 60


# ---------------------------------------------------------------- money helpers

def parse_money(raw: str | int | float | Decimal) -> int:
    """Parse a money literal into signed integer cents."""
    if isinstance(raw, int):
        return raw
    if isinstance(raw, (float, Decimal)):
        return int((Decimal(str(raw)) * 100).quantize(Decimal("1")))
    text = str(raw).strip()
    if not text:
        return 0
    negative = text.startswith("(") and text.endswith(")")
    text = re.sub(r"[^0-9.\-]", "", text)
    if not text or text in {"-", "."}:
        return 0
    cents = int((Decimal(text) * 100).quantize(Decimal("1")))
    return -abs(cents) if negative else cents


def fmt_money(cents: int, currency: str = "USD") -> str:
    """Format signed cents as a display string, e.g. -1995 -> '-$19.95'."""
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(cents), 100)
    symbol = "$" if currency == "USD" else f"{currency} "
    return f"{sign}{symbol}{whole:,}.{frac:02d}"


def to_amount(cents: int) -> float:
    """Cents -> a JSON-friendly 2dp number in dollars (display only)."""
    return round(cents / 100, 2)


def fmt_vnd(cents: int, rate: float) -> str:
    """Format a USD amount as approximate đồng, rounded to the nearest 1.000 ₫
    so the conversion does not imply precision it does not have."""
    dong = round(abs(cents) / 100 * rate / 1000) * 1000
    sign = "-" if cents < 0 else ""
    return f"{sign}{dong:,.0f}".replace(",", ".") + " ₫"


def fmt_display(cents: int, lang: str = "vi", currency: str = "USD") -> str:
    """User-facing money.

    Vietnamese leads with đồng (marked approximate) and keeps the exact USD
    figure in brackets, because USD is what the statement actually says.
    """
    usd = fmt_money(cents, currency)
    if lang != "vi" or currency != "USD":
        return usd
    from ..config import settings

    if not settings.show_vnd or not settings.usd_vnd_rate:
        return usd
    return f"≈{fmt_vnd(cents, settings.usd_vnd_rate)} ({usd})"


def fx_note(lang: str = "vi") -> dict[str, Any]:
    """The conversion basis, surfaced everywhere ₫ appears."""
    from ..config import settings

    return {
        "base_currency": "USD",
        "vnd_rate": settings.usd_vnd_rate,
        "vnd_enabled": bool(settings.show_vnd and lang == "vi"),
        "source": "configured (NEXA_USD_VND_RATE)",
    }


# ---------------------------------------------------------------------- enums

class TxnType(str, Enum):
    PAYIN = "payin"                        # money arriving from outside
    PAYOUT = "payout"                      # money leaving to outside
    TRANSFER_TO_CARD = "transfer_to_card"  # account -> card load
    FEE = "fee"
    PURCHASE = "purchase"                  # direct debit / ACH spend on account
    REFUND = "refund"


class CardTxnType(str, Enum):
    LOAD = "load"
    PURCHASE = "purchase"
    FEE = "fee"
    REFUND = "refund"


class SourceKind(str, Enum):
    STATEMENT = "statement"
    CARD = "card"
    WALLET = "wallet"
    EMAIL = "email"


class Label(str, Enum):
    """The ONLY three verdicts this system is allowed to emit (WLF-01 rule C)."""

    RECURRING_CONFIRMED = "recurring_confirmed"
    NEEDS_YOUR_CONFIRMATION = "needs_your_confirmation"
    INSUFFICIENT_DATA = "insufficient_data"


class FindingKind(str, Enum):
    RECURRING_SUBSCRIPTION = "recurring_subscription"
    FORGOTTEN_SUBSCRIPTION = "forgotten_subscription"
    PRICE_INCREASE = "price_increase"
    DUPLICATE_CHARGE = "duplicate_charge"
    DOUBLE_FEE = "double_fee"
    DUPLICATE_PAYIN = "duplicate_payin"
    TRANSFER_NOT_ON_CARD = "transfer_not_on_card"
    WALLET_BALANCE_MISMATCH = "wallet_balance_mismatch"
    UNKNOWN_MERCHANT = "unknown_merchant"
    MISSING_EMAIL = "missing_email"
    SUSPICIOUS_EMAIL = "suspicious_email"


class EmailMatchStatus(str, Enum):
    MATCHED = "matched"
    NO_EMAIL_FOUND = "no_email_found"
    EMAIL_SUSPICIOUS = "email_suspicious"


# ----------------------------------------------------------------- data records

@dataclass
class Txn:
    """One line of the account statement."""

    txn_id: str
    when: datetime
    posted_date: date
    type: TxnType
    description: str
    counterparty: str
    amount_cents: int          # signed: inflow positive, outflow negative
    currency: str = "USD"
    balance_after_cents: int = 0
    merchant: str | None = None       # resolved by merchants.py
    merchant_key: str | None = None

    @property
    def day(self) -> date:
        return self.when.date()

    @property
    def is_outflow(self) -> bool:
        return self.amount_cents < 0


@dataclass
class CardTxn:
    """One line of the card statement."""

    card_txn_id: str
    when: datetime
    posted_date: date
    type: CardTxnType
    merchant_raw: str
    mcc: str
    amount_cents: int          # signed: load/refund positive, purchase/fee negative
    card_number: str           # full only inside the engine; masked at the boundary
    currency: str = "USD"
    load_ref: str | None = None       # links a load back to an account transfer
    merchant: str | None = None
    merchant_key: str | None = None

    @property
    def day(self) -> date:
        return self.when.date()


@dataclass
class WalletEvent:
    event_id: str
    when: datetime
    kind: str                  # "credit" | "debit"
    amount_cents: int          # always positive magnitude
    ref: str | None
    note: str = ""

    @property
    def signed_cents(self) -> int:
        return self.amount_cents if self.kind == "credit" else -self.amount_cents


@dataclass
class Wallet:
    wallet_id: str
    currency: str
    opening_balance_cents: int
    opening_date: date
    reported_balance_cents: int
    reported_at: date
    events: list[WalletEvent] = field(default_factory=list)

    @property
    def computed_balance_cents(self) -> int:
        return self.opening_balance_cents + sum(e.signed_cents for e in self.events)


@dataclass
class EmailMsg:
    message_id: str
    from_name: str
    from_addr: str
    reply_to: str | None
    to_addr: str
    subject: str
    when: datetime
    body: str
    genre: str = "receipt"     # receipt | subscription_confirmation | bank_notice | other
    amounts_cents: list[int] = field(default_factory=list)

    @property
    def from_domain(self) -> str:
        return self.from_addr.rsplit("@", 1)[-1].lower()

    @property
    def reply_to_domain(self) -> str | None:
        if not self.reply_to:
            return None
        return self.reply_to.rsplit("@", 1)[-1].lower()


@dataclass
class Source:
    """Provenance for a finding — every alert must name where it came from."""

    kind: SourceKind
    ref: str
    detail: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind.value, "ref": self.ref, "detail": self.detail}


@dataclass
class Finding:
    """A single flagged item. `params` feeds the i18n catalog so VI and EN
    render the same numbers."""

    kind: FindingKind
    label: Label
    confidence: float
    params: dict[str, Any]
    sources: list[Source]
    txn_ids: list[str] = field(default_factory=list)
    amount_cents: int = 0
    period_key: str = ""
    occurred_on: date | None = None
    statement_date: date | None = None

    @property
    def fingerprint(self) -> str:
        """Stable identity used to suppress repeat alerts across scans."""
        basis = "|".join(
            [
                self.kind.value,
                ",".join(sorted(self.txn_ids)),
                str(self.amount_cents),
                self.period_key,
            ]
        )
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]

    @property
    def dispute_deadline(self) -> date | None:
        """US dispute window: 60 days from the statement date."""
        if not self.statement_date:
            return None
        return self.statement_date + timedelta(days=DISPUTE_WINDOW_DAYS)

    def days_left(self, today: date) -> int | None:
        deadline = self.dispute_deadline
        if deadline is None:
            return None
        return (deadline - today).days
