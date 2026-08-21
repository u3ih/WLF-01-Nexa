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

# Currencies with no minor unit. Amounts are still stored as integer "cents"
# (value * 100) so every sum stays exact and currency-agnostic; only the
# *display* drops the two decimals that these currencies do not have.
ZERO_DECIMAL_CURRENCIES = frozenset({"VND", "JPY", "KRW", "IDR", "CLP", "ISK"})

CURRENCY_SYMBOLS = {"USD": "$", "EUR": "\u20ac", "GBP": "\u00a3", "VND": "\u20ab"}


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
    """Format signed cents as a display string, e.g. -1995 -> '-$19.95'.

    Zero-decimal currencies (\u0111\u1ed3ng, yen...) print without the two
    decimals they do not have: 896600000 VND -> '8.966.000 \u20ab'.
    """
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(cents), 100)
    if currency in ZERO_DECIMAL_CURRENCIES:
        grouped = f"{whole:,}".replace(",", ".")
        symbol = CURRENCY_SYMBOLS.get(currency, currency)
        return f"{sign}{grouped} {symbol}"
    symbol = CURRENCY_SYMBOLS.get(currency) or f"{currency} "
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
    PAYIN = "payin"                          # money arriving from outside
    PAYOUT = "payout"                        # money leaving to outside
    TRANSFER_TO_CARD = "transfer_to_card"    # account -> card load
    TRANSFER_TO_WALLET = "transfer_to_wallet"  # receiving account -> Wealify wallet
    FEE = "fee"
    PURCHASE = "purchase"                    # direct debit / ACH spend on account
    REFUND = "refund"


class CardTxnType(str, Enum):
    LOAD = "load"
    PURCHASE = "purchase"
    FEE = "fee"
    REFUND = "refund"
    WITHDRAW = "withdraw"                    # card balance sent back out


class TxnStatus(str, Enum):
    """Settlement state of a row.

    The sample statements carry rows that never moved money (declined top-ups,
    cancelled withdrawals) and rows still in flight. Only SETTLED_STATUSES may
    be counted in a total; the rest are reported separately, never silently
    dropped and never silently summed.
    """

    SUCCESS = "success"
    PENDING = "pending"
    PROCESSING = "processing"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_settled(self) -> bool:
        return self is TxnStatus.SUCCESS

    @property
    def is_in_flight(self) -> bool:
        return self in (TxnStatus.PENDING, TxnStatus.PROCESSING)


SETTLED_STATUSES = frozenset({TxnStatus.SUCCESS})


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
    balance_after_cents: int | None = None   # None when the source has no running balance
    status: TxnStatus = TxnStatus.SUCCESS
    account_ref: str = ""             # virtual-account number, masked at the boundary
    decline_reason: str = ""
    merchant: str | None = None       # resolved by merchants.py
    merchant_key: str | None = None

    @property
    def day(self) -> date:
        return self.when.date()

    @property
    def is_outflow(self) -> bool:
        return self.amount_cents < 0

    @property
    def is_settled(self) -> bool:
        return self.status.is_settled


@dataclass
class Card:
    """One card on the account.

    The export identifies a card three ways and they all have to agree: the
    card table calls it `CARD_0004`, the wallet lines and the receipt emails
    call it `VC04`, and the transaction rows carry only the nickname. `code`
    holds the VC form because that is the one the other ledgers join on.

    No PAN is present anywhere; `masked` is the display string the export
    supplies, and nothing here is ever rendered unmasked.
    """

    code: str                  # "VC04" — the join key used by wallet refs and emails
    name: str                  # "Volcano EU"
    currency: str = "USD"
    card_number: str = ""      # full only inside the engine; absent in this export
    last4: str = ""
    status: str = "active"     # active | frozen | cancelled | trial
    card_id: str = ""          # "CARD_0004" — the card table's own key
    masked: str = ""           # "**** **** **** 0004", as the export writes it
    network: str = ""
    purpose: str = ""
    expiry: str = ""
    # The card table states its own running figures. They are reported as the
    # issuer's numbers, never recomputed into them and never silently trusted
    # over the transaction rows.
    balance_cents: int | None = None
    total_deposit_cents: int | None = None
    total_withdrawal_cents: int | None = None

    @property
    def label(self) -> str:
        return f"{self.name} ({self.code})" if self.code else self.name

    @property
    def is_open(self) -> bool:
        return self.status == "active"


@dataclass
class VirtualAccount:
    """One receiving (virtual) account.

    This export lists the accounts and what each has received in total, but
    ships no per-transaction rows for them, so `total_received_cents` is the
    issuer's own figure and cannot be checked against a ledger. Anything that
    would need those rows must report `insufficient_data` instead.
    """

    account_number: str        # full only inside the engine; masked at the boundary
    masked: str
    name: str
    nickname: str = ""
    payout_source: str = ""    # "Payoneer", "Etsy", "Amazon", "Paypal", "PingPong"
    bank_name: str = ""
    swift_bic: str = ""
    currency: str = "USD"
    total_received_cents: int | None = None
    fee_note: str = ""         # "0%" as written; not a computed rate
    status: str = "active"     # active | inactive | process
    managed_by: str = ""

    @property
    def label(self) -> str:
        return self.nickname or self.name

    @property
    def has_ledger(self) -> bool:
        """This export ships no transaction rows for receiving accounts."""
        return False


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
    status: TxnStatus = TxnStatus.SUCCESS
    card_code: str = ""               # "VC04" — matches Card.code and the email "Thẻ:" line
    card_name: str = ""               # "Volcano EU"
    ledger: SourceKind = SourceKind.CARD   # which balance the row actually hit
    usd_amount_cents: int | None = None    # settled USD value when `currency` is not USD
    completed_at: datetime | None = None   # None while the row is still in flight
    # Figures the export states separately from `amount`. Each stays None when
    # the export leaves it blank or fills it with a placeholder, so a missing
    # figure never becomes a zero.
    user_amount_cents: int | None = None
    settled_amount_cents: int | None = None
    fee_cents: int | None = None
    fx_rate: float | None = None
    raw_type: str = ""                # the export's own wording, kept for display
    merchant: str | None = None
    merchant_key: str | None = None

    @property
    def day(self) -> date:
        return self.when.date()

    @property
    def is_settled(self) -> bool:
        return self.status.is_settled

    @property
    def is_foreign(self) -> bool:
        return self.currency != "USD"

    @property
    def is_in_flight(self) -> bool:
        return self.status.is_in_flight


@dataclass
class WalletEvent:
    event_id: str
    when: datetime
    kind: str                  # "credit" | "debit"
    amount_cents: int          # always positive magnitude
    ref: str | None
    note: str = ""
    descriptor: str = ""       # the wallet line as the statement words it
    currency: str = "USD"
    status: TxnStatus = TxnStatus.SUCCESS
    target_card_code: str = ""  # set on a wallet -> card load ("VC01")
    counterparty: str = ""      # "Paypal", "Amazon", "Payoneer", bank name

    @property
    def signed_cents(self) -> int:
        return self.amount_cents if self.kind == "credit" else -self.amount_cents

    @property
    def day(self) -> date:
        return self.when.date()

    @property
    def is_settled(self) -> bool:
        return self.status.is_settled


@dataclass
class Wallet:
    wallet_id: str
    currency: str
    opening_balance_cents: int
    opening_date: date
    # A statement that never states a closing balance leaves these None. The
    # engine then reports "ch\u01b0a \u0111\u1ee7 d\u1eef li\u1ec7u" instead of inventing a gap of zero.
    reported_balance_cents: int | None = None
    reported_at: date | None = None
    events: list[WalletEvent] = field(default_factory=list)

    def computed_balance(self, currency: str) -> int:
        """Closing balance in one currency.

        Scoped per currency on purpose: a wallet that holds USD and EUR has two
        balances, and adding them would produce a number that means nothing.
        Only settled events count — an in-flight debit has not left the wallet.
        """
        opening = self.opening_balance_cents if currency == self.currency else 0
        return opening + sum(e.signed_cents for e in self.events
                             if e.is_settled and e.currency == currency)

    @property
    def computed_balance_cents(self) -> int:
        """Closing balance in the wallet's own currency."""
        return self.computed_balance(self.currency)

    @property
    def has_reported_balance(self) -> bool:
        return self.reported_balance_cents is not None

    def events_in(self, currency: str) -> list[WalletEvent]:
        return [e for e in self.events if e.currency == currency]

    @property
    def currencies(self) -> list[str]:
        return sorted({e.currency for e in self.events} | {self.currency})


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
    # When the mailbox is a sandbox relay, `from_addr` above holds the sender the
    # *user is asked to trust* (parsed out of the body) and these hold the relay
    # that actually delivered it. Look-alike detection must read the former.
    relay_from_name: str = ""
    relay_from_addr: str = ""
    txn_ref: str | None = None       # transaction this receipt claims to explain
    card_code: str = ""              # "VC04" — the card the receipt names
    currency: str = "USD"
    links: list[str] = field(default_factory=list)
    codes: list[str] = field(default_factory=list)

    @property
    def from_domain(self) -> str:
        return self.from_addr.rsplit("@", 1)[-1].lower()

    @property
    def relay_domain(self) -> str | None:
        if not self.relay_from_addr:
            return None
        return self.relay_from_addr.rsplit("@", 1)[-1].lower()

    @property
    def is_relayed(self) -> bool:
        """True when the delivering mailbox is not the claimed sender."""
        return bool(self.relay_from_addr
                    and self.relay_from_addr.lower() != self.from_addr.lower())

    @property
    def link_domains(self) -> list[str]:
        out = []
        for url in self.links:
            m = re.match(r"https?://([^/?#]+)", url.strip(), re.I)
            if m:
                out.append(m.group(1).lower())
        return out

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
