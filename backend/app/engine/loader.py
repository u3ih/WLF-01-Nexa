"""Load the sample dataset: account statement (CSV or PDF), card statement,
wallet ledger and mailbox."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from pathlib import Path

from ..config import settings
from .merchants import merchant_key, resolve
from .models import (
    Card,
    VirtualAccount,
    CardTxn,
    CardTxnType,
    EmailMsg,
    Txn,
    TxnType,
    Wallet,
    WalletEvent,
    parse_money,
)

# "$19.95", but also "19.95 USD" / "192.52 EUR" — a receipt written for a
# non-US reader often puts the code after the figure and no symbol in front.
MONEY_IN_TEXT = re.compile(
    r"\$\s?(?P<sym>[\d,]+\.\d{2})"
    r"|(?P<num>[\d,]+\.\d{2})\s?(?P<code>USD|EUR|GBP)\b"
)


def money_in_text(text: str) -> list[int]:
    """Every money figure in a body, in cents, in the order it appears."""
    out: list[int] = []
    for m in MONEY_IN_TEXT.finditer(text):
        raw = m.group("sym") or m.group("num")
        if raw:
            out.append(parse_money(raw))
    return out


@dataclass
class Dataset:
    meta: dict
    account: list[Txn] = field(default_factory=list)
    card: list[CardTxn] = field(default_factory=list)
    wallet: Wallet | None = None
    emails: list[EmailMsg] = field(default_factory=list)
    # Cards on the account. A statement can cover several, and a finding has to
    # be able to say which one it happened on.
    cards: list[Card] = field(default_factory=list)
    # Receiving accounts. Present as entities even when the export ships no
    # transaction rows for them — the gap is then stated, not hidden.
    virtual_accounts: list[VirtualAccount] = field(default_factory=list)
    # Mailboxes the export contained, beyond the owner's. Kept addressable so
    # a different inbox can be analysed without reloading.
    mailboxes: dict[str, list[EmailMsg]] = field(default_factory=dict)
    # Anything about the input worth telling the user: a file skipped, a column
    # that held a placeholder, a ledger the export did not include.
    notes: list[str] = field(default_factory=list)
    source_files: dict[str, str] = field(default_factory=dict)

    @property
    def statement_date(self) -> date:
        return date.fromisoformat(self.meta["statement_date"])

    @property
    def owner_email(self) -> str:
        return self.meta.get("owner_email", "")

    def card_by_code(self, code: str) -> Card | None:
        return next((c for c in self.cards if c.code == code), None)

    def card_by_name(self, name: str) -> Card | None:
        return next((c for c in self.cards if c.name == name), None)

    def account_by_number(self, number: str) -> VirtualAccount | None:
        return next((a for a in self.virtual_accounts
                     if a.account_number == number), None)

    @property
    def currencies(self) -> list[str]:
        seen = {t.currency for t in self.account} | {c.currency for c in self.card}
        if self.wallet:
            seen |= {e.currency for e in self.wallet.events}
        return sorted(seen) or ["USD"]


def _attach_merchant_txn(txn: Txn) -> Txn:
    found = resolve(txn.description)
    txn.merchant = found.name if found else None
    txn.merchant_key = merchant_key(txn.description)
    return txn


def _attach_merchant_card(txn: CardTxn) -> CardTxn:
    found = resolve(txn.merchant_raw)
    txn.merchant = found.name if found else None
    txn.merchant_key = merchant_key(txn.merchant_raw)
    return txn


# ------------------------------------------------------------------ account CSV

def load_account_csv(path: Path) -> list[Txn]:
    out: list[Txn] = []
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            txn = Txn(
                txn_id=row["txn_id"],
                when=datetime.fromisoformat(row["datetime"]),
                posted_date=date.fromisoformat(row["posted_date"]),
                type=TxnType(row["type"]),
                description=row["description"].strip(),
                counterparty=row.get("counterparty", "").strip(),
                amount_cents=parse_money(row["amount"]),
                currency=row.get("currency", "USD"),
                balance_after_cents=parse_money(row.get("balance_after") or "0"),
            )
            out.append(_attach_merchant_txn(txn))
    return sorted(out, key=lambda t: (t.when, t.txn_id))


# ------------------------------------------------------------------ account PDF

PDF_ROW = re.compile(
    r"^(?P<dt>\d{4}-\d{2}-\d{2}T[\d:]{8})\s\|\s(?P<id>[A-Z]+-\d+)\s\|\s"
    r"(?P<type>[a-z_]+)\s\|\s(?P<desc>.*?)\s\|\s(?P<amount>-?[\d,]+\.\d{2})\s\|\s"
    r"(?P<balance>-?[\d,]+\.\d{2})$"
)


def load_account_pdf(path: Path) -> list[Txn]:
    """Parse the PDF statement. Kept deliberately strict: a row that does not
    match is skipped rather than guessed at."""
    import pdfplumber

    out: list[Txn] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            for line in (page.extract_text() or "").splitlines():
                m = PDF_ROW.match(line.strip())
                if not m:
                    continue
                when = datetime.fromisoformat(m["dt"])
                txn = Txn(
                    txn_id=m["id"],
                    when=when,
                    posted_date=when.date(),
                    type=TxnType(m["type"]),
                    description=m["desc"].strip(),
                    counterparty="",
                    amount_cents=parse_money(m["amount"]),
                    balance_after_cents=parse_money(m["balance"]),
                )
                out.append(_attach_merchant_txn(txn))
    return sorted(out, key=lambda t: (t.when, t.txn_id))


# --------------------------------------------------------------------- card CSV

def load_card_csv(path: Path) -> list[CardTxn]:
    out: list[CardTxn] = []
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            txn = CardTxn(
                card_txn_id=row["card_txn_id"],
                when=datetime.fromisoformat(row["datetime"]),
                posted_date=date.fromisoformat(row["posted_date"]),
                type=CardTxnType(row["type"]),
                merchant_raw=row["merchant_raw"].strip(),
                mcc=row.get("mcc", ""),
                amount_cents=parse_money(row["amount"]),
                card_number=row.get("card_number", ""),
                currency=row.get("currency", "USD"),
                load_ref=(row.get("load_ref") or "").strip() or None,
            )
            out.append(_attach_merchant_card(txn))
    return sorted(out, key=lambda t: (t.when, t.card_txn_id))


# ------------------------------------------------------------------------ wallet

def load_wallet(path: Path) -> Wallet:
    raw = json.loads(path.read_text())
    events = [
        WalletEvent(
            event_id=e["event_id"],
            when=datetime.fromisoformat(e["datetime"]),
            kind=e["kind"],
            amount_cents=parse_money(e["amount"]),
            ref=e.get("ref"),
            note=e.get("note", ""),
        )
        for e in raw["events"]
    ]
    return Wallet(
        wallet_id=raw["wallet_id"],
        currency=raw.get("currency", "USD"),
        opening_balance_cents=parse_money(raw["opening_balance"]),
        opening_date=date.fromisoformat(raw["opening_date"]),
        reported_balance_cents=parse_money(raw["reported_balance"]),
        reported_at=date.fromisoformat(raw["reported_at"]),
        events=sorted(events, key=lambda e: (e.when, e.event_id)),
    )


# ----------------------------------------------------------------------- mailbox

def _parse_addr(raw: str | None) -> tuple[str, str]:
    if not raw:
        return "", ""
    m = re.match(r"^\s*(?P<name>[^<]*?)\s*<(?P<addr>[^>]+)>\s*$", raw)
    if m:
        return m["name"].strip(), m["addr"].strip().lower()
    return "", raw.strip().lower()


def load_mailbox(directory: Path) -> list[EmailMsg]:
    parser = BytesParser(policy=policy.default)
    out: list[EmailMsg] = []
    for path in sorted(directory.glob("*.eml")):
        msg = parser.parsebytes(path.read_bytes())
        from_name, from_addr = _parse_addr(msg.get("From"))
        _, reply_to = _parse_addr(msg.get("Reply-To"))
        _, to_addr = _parse_addr(msg.get("To"))
        try:
            when = parsedate_to_datetime(msg.get("Date")).replace(tzinfo=None)
        except (TypeError, ValueError):
            when = datetime.min
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_content()
                    break
        else:
            body = msg.get_content()
        subject = msg.get("Subject", "")
        amounts = money_in_text(f"{subject}\n{body}")
        out.append(
            EmailMsg(
                message_id=msg.get("Message-ID", path.name),
                from_name=from_name,
                from_addr=from_addr,
                reply_to=reply_to or None,
                to_addr=to_addr,
                subject=subject,
                when=when,
                body=body,
                genre=msg.get("X-Nexa-Genre", "other"),
                amounts_cents=amounts,
            )
        )
    return sorted(out, key=lambda e: (e.when, e.message_id))


# ------------------------------------------------------------------ full dataset

def load_dataset(data_dir: Path, use_pdf: bool = False) -> Dataset:
    """Load whichever sample layout `data_dir` holds.

    Two exist: the Wealify CSV export (`cards.csv` and friends) and the
    generated layout (`account_meta.json` plus CSVs and an `.eml` mailbox).
    The directory is inspected rather than configured, so pointing the app at
    either one is all it takes.
    """
    if (data_dir / "cards.csv").exists():
        from .loader_wlf import load_export_dataset

        return load_export_dataset(data_dir, mailbox=settings.mailbox or None)

    meta = json.loads((data_dir / "account_meta.json").read_text())
    account_csv = data_dir / "account_statement.csv"
    account_pdf = data_dir / "account_statement.pdf"
    if use_pdf and account_pdf.exists():
        account = load_account_pdf(account_pdf)
        account_source = account_pdf.name
    else:
        account = load_account_csv(account_csv)
        account_source = account_csv.name
    ds = Dataset(
        meta=meta,
        account=account,
        card=load_card_csv(data_dir / "card_statement.csv"),
        wallet=load_wallet(data_dir / "wallet_ledger.json"),
        emails=load_mailbox(data_dir / "mailbox"),
        source_files={
            "account": account_source,
            "card": "card_statement.csv",
            "wallet": "wallet_ledger.json",
            "mailbox": "mailbox/",
        },
    )
    return ds
