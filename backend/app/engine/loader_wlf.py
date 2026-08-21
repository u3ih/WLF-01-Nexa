"""Load the Wealify sample export into a `Dataset`.

Two shapes of the same export are handled: the current one, a directory of
CSVs (`cards.csv`, `virtual_accounts.csv`, `transactions_card.csv`, one
`email_*.csv` per mailbox), and the earlier workbook. `load_dataset` picks by
inspecting the directory.

Five things about this export need saying before the code makes sense.

1. **One transaction file, two ledgers.** `transactions_card.csv` carries a
   `source_type` column: `Thẻ` rows moved a card balance, `Ví` rows moved the
   wallet. The `type` column names nine flows in Vietnamese, and its wording is
   from the platform's point of view — `Rút tiền về ví` is money *leaving* the
   wallet for a card. Type is therefore read together with the reference and
   the sign, never from the label alone.

2. **The receiving-account ledger is not in this export.** `virtual_accounts.csv`
   lists the accounts and a `total_received` each, and nothing itemises them.
   `transactions_va.csv`, despite its name, holds no `WLF15-VA-*` row at all —
   it is a stale copy of the card and wallet rows in the previous schema, with
   its Vietnamese text corrupted. It is detected and skipped rather than parsed,
   because parsing it would double every card figure.

3. **Placeholder text sits in numeric columns.** `fee` reads `NaN undefined` on
   192 of the 193 rows that have it, and `exchange_rate` reads `NaN = 1 USD`.
   Both are absent data wearing a number's clothing; they are parsed to `None`,
   never to `0` and never to a float `nan` that would poison every total.

4. **Three date formats and two decimal conventions.** Transactions use
   `21/08/2026 | 01:27 PM`, the card table `14/8/26 14:00`, the account table
   ISO-8601 with a `Z`. The card table also writes money with a decimal comma
   (`49,7` is forty-nine seventy), while transactions use a decimal point and
   thousands commas (`1,936.92 USD`).

5. **The mailbox is a relay.** Every message was delivered by the sandbox
   address `no-reply@wealify.com`; the sender the user is asked to trust —
   including the look-alike ones — is written in the body after
   `Người gửi gốc (CSV)`. Look-alike detection reads that, not the envelope.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .loader import Dataset, _attach_merchant_card, _attach_merchant_txn
from .models import (
    Card,
    CardTxn,
    CardTxnType,
    EmailMsg,
    SourceKind,
    Txn,
    TxnStatus,
    TxnType,
    VirtualAccount,
    Wallet,
    WalletEvent,
)

# ------------------------------------------------------------------ file names

CARDS_CSV = "cards.csv"
ACCOUNTS_CSV = "virtual_accounts.csv"
TXN_CSV = "transactions_card.csv"
LEGACY_VA_CSV = "transactions_va.csv"
EMAIL_GLOB = "email_*.csv"

# --------------------------------------------------------------- placeholders

# Text the export writes into a column that has no value. Treated as absent.
PLACEHOLDERS = frozenset({
    "", "-", "--", "n/a", "na", "nan", "null", "none", "undefined",
    "nan undefined", "nan = 1 usd", "không có người quản lý",
})


def _is_blank(raw: Any) -> bool:
    text = str(raw if raw is not None else "").strip().lower()
    if text in PLACEHOLDERS:
        return True
    # "NaN = 1 USD", "NaN undefined" and friends: any cell whose numeric part is
    # the string NaN carries no figure, whatever else is appended to it.
    return text.startswith("nan")


def _text(raw: Any) -> str:
    """A cell as clean text.

    Spreadsheet exports quote an account number with a leading apostrophe to
    stop Excel eating the leading zero, and pad cells with stray whitespace.
    A placeholder comes back as the empty string.
    """
    if _is_blank(raw):
        return ""
    return str(raw).strip().strip("'").strip()


# --------------------------------------------------------------------- numbers

NUMBER = re.compile(r"-?[\d.,]+")


def _money(raw: Any, *, decimal_comma: bool = False) -> int | None:
    """A money cell as signed integer cents, or None when it holds no figure.

    Two conventions appear in one export. Transactions write `1,936.92 USD`:
    comma groups thousands, point separates decimals. The card table writes
    `49,7`: the comma *is* the decimal point. Guessing between them from the
    string alone is unreliable — `1,617` is either — so the caller says which
    file it is reading.
    """
    if _is_blank(raw):
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float, Decimal)):
        return int((Decimal(str(raw)) * 100).quantize(Decimal("1")))
    found = NUMBER.search(str(raw))
    if not found:
        return None
    text = found.group(0)
    if decimal_comma:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", "")
    try:
        return int((Decimal(text) * 100).quantize(Decimal("1")))
    except InvalidOperation:
        return None


def _money_or_zero(raw: Any, *, decimal_comma: bool = False) -> int:
    value = _money(raw, decimal_comma=decimal_comma)
    return 0 if value is None else value


def _rate(raw: Any) -> float | None:
    """An exchange rate, or None. `NaN = 1 USD` is not a rate."""
    if _is_blank(raw):
        return None
    found = NUMBER.search(str(raw).replace(",", ""))
    if not found:
        return None
    try:
        value = float(found.group(0))
    except ValueError:
        return None
    return value if value > 0 else None


CURRENCY_IN_TEXT = re.compile(r"\b([A-Z]{3})\b")


def _currency_of(raw: Any, default: str = "USD") -> str:
    """The currency code inside a cell like `747.75 USD`."""
    found = CURRENCY_IN_TEXT.search(str(raw or ""))
    return found.group(1) if found else default


# ----------------------------------------------------------------------- dates

DATE_FORMATS = (
    "%d/%m/%Y | %I:%M %p",     # transactions: 21/08/2026 | 01:27 PM
    "%d/%m/%Y %I:%M %p",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%d/%m/%y %H:%M",          # card table: 14/8/26 14:00
    "%d/%m/%y",                # expiry: 29/12/26
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
)


def _when(raw: Any) -> datetime | None:
    """Parse any of the export's date shapes. None when the cell is empty.

    Day-first throughout: `12/04/2026` is April. Every format in this export
    is day-first, so there is no ambiguity to resolve — but reading it
    month-first would silently move a third of the rows to another month.
    """
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=None)
    text = _text(raw)
    if not text:
        return None
    text = re.sub(r"\s*\|\s*", " | ", text)
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    iso = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        # Naive throughout: the export mixes local wall-clock stamps with UTC
        # scrape stamps, and comparing them as if both were UTC would shift
        # dates across a day boundary.
        return datetime.fromisoformat(iso).replace(tzinfo=None)
    except ValueError:
        return None


# ------------------------------------------------------------------ csv reading

ENCODINGS = ("utf-8-sig", "utf-8", "cp1258", "latin-1")


def _decode(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    for encoding in ENCODINGS:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace"), "latin-1"


def read_csv(path: Path) -> list[dict[str, Any]]:
    """Read one export CSV.

    The delimiter is not consistent across the files — `cards.csv` and one of
    the mailboxes are semicolon-separated while the rest use commas — so it is
    sniffed from the header rather than assumed. A BOM is stripped by the
    codec, and the encoding is tried in order because one file is not UTF-8.
    """
    text, _ = _decode(path)
    if not text.strip():
        return []
    header = text.splitlines()[0]
    delimiter = ";" if header.count(";") > header.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    rows = []
    for row in reader:
        if any(v is not None and str(v).strip() for v in row.values()):
            rows.append({(k or "").strip(): v for k, v in row.items()})
    return rows


# ------------------------------------------------------------------ vocabulary

STATUS_WORDS: dict[str, TxnStatus] = {
    "success": TxnStatus.SUCCESS,
    "succeeded": TxnStatus.SUCCESS,
    "completed": TxnStatus.SUCCESS,
    "active": TxnStatus.SUCCESS,
    "thành công": TxnStatus.SUCCESS,
    "pending": TxnStatus.PENDING,
    "đang chờ": TxnStatus.PENDING,
    "process": TxnStatus.PROCESSING,
    "processing": TxnStatus.PROCESSING,
    "đang xử lý": TxnStatus.PROCESSING,
    # The export uses "Failure"/"Cancel" here and "Failed"/"Cancelled"
    # elsewhere. Both spellings of each are mapped: a status this code does not
    # recognise would fall through to SUCCESS and be counted as real money.
    "fail": TxnStatus.FAILED,
    "failed": TxnStatus.FAILED,
    "failure": TxnStatus.FAILED,
    "declined": TxnStatus.FAILED,
    "thất bại": TxnStatus.FAILED,
    "cancel": TxnStatus.CANCELLED,
    "cancelled": TxnStatus.CANCELLED,
    "canceled": TxnStatus.CANCELLED,
    "đã huỷ": TxnStatus.CANCELLED,
}

UNKNOWN_STATUS_NOTE = (
    "transactions_card.csv: status {value!r} is not one this build knows; "
    "the row is treated as not settled so it cannot inflate a total"
)


def _status(raw: Any, unknown: set[str] | None = None) -> TxnStatus:
    text = _text(raw).lower()
    if not text:
        return TxnStatus.SUCCESS
    found = STATUS_WORDS.get(text)
    if found is None:
        # Fail closed. An unrecognised status must not be spent as if settled.
        if unknown is not None:
            unknown.add(text)
        return TxnStatus.PROCESSING
    return found


CARD_STATUS_WORDS = {
    "active": "active",
    "frozen": "frozen",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "closed": "cancelled",
    "inactive": "inactive",
    "process": "process",
}

# The `type` column, in the export's Vietnamese. `source_type` says which
# balance moved; `type` says what the movement was.
T_CARD_SPEND = "thẻ chi tiêu"
T_CARD_LOAD = "nạp tiền vào thẻ"
T_CARD_WITHDRAW = "rút tiền từ thẻ"
T_CARD_REFUND = "hoàn tiền về thẻ"
T_WALLET_CREDIT = "nạp tiền"
T_WALLET_CREDIT_FROM_CARD = "nạp tiền vào ví"
T_WALLET_DEBIT = "rút tiền về ví"
T_WALLET_FEE = "rút tiền từ ví"
T_WALLET_REFERENCE = "tham chiếu"

LEDGER_CARD = "thẻ"
LEDGER_WALLET = "ví"

# --------------------------------------------------------------- reference cues

FX_FEE = re.compile(r"^\s*(FX fee|Phí chuyển đổi|Foreign transaction fee)", re.I)
CARD_CODE_IN_TEXT = re.compile(r"\b(VC\d{2})\b")
LAST4_IN_TEXT = re.compile(r"(\d{4})\s*$")
WALLET_TO_CARD = re.compile(r"^\s*(Nạp vào thẻ|Nap vao the)\b", re.I)
WALLET_OPENING = re.compile(r"^\s*Số dư đầu kỳ", re.I)
WALLET_FROM_ACCOUNT = re.compile(r"^\s*Nhận\s*&\s*chuyển về ví", re.I)
WALLET_FROM_CARD = re.compile(r"^\s*Nạp tiền vào ví", re.I)
WALLET_TO_BANK = re.compile(r"^\s*(Rút về ngân hàng|Withdraw to bank)", re.I)
WALLET_TO_CRYPTO = re.compile(r"^\s*Rút tiền về ví\s*\S+\s*\(", re.I)
COUNTERPARTY_AFTER_COLON = re.compile(r":\s*([^(]+?)\s*(?:\(|$)")
BANK_NAME = re.compile(r"ngân hàng\s+([A-Za-zÀ-ỹ]+)", re.I)
CHAIN_NAME = re.compile(r"\(([A-Za-z]+)\)\s*$")
TRIAL_CARD = re.compile(r"trial", re.I)


def _card_code(*sources: str) -> str:
    """The card's join key.

    `VC04` is preferred because the wallet lines and the receipt emails both
    spell a card that way. Failing that, the trailing four digits of the
    masked number give the same index — `**** **** **** 0004` is `VC04`.
    """
    for text in sources:
        found = CARD_CODE_IN_TEXT.search(text or "")
        if found:
            return found.group(1)
    for text in sources:
        found = LAST4_IN_TEXT.search((text or "").strip())
        if found:
            index = int(found.group(1))
            if 1 <= index <= 99:
                return f"VC{index:02d}"
    return ""


# ------------------------------------------------------------------ card table

def load_cards(rows: list[dict[str, Any]]) -> list[Card]:
    """The card registry from `cards.csv`.

    Money in this file uses a decimal comma, so `49,7` is forty-nine seventy
    and not four hundred and ninety-seven.
    """
    out: list[Card] = []
    for row in rows:
        name = _text(row.get("card_name"))
        if not name:
            continue
        masked = _text(row.get("card_number_masked"))
        code = _card_code(masked, _text(row.get("last4")))
        raw_status = _text(row.get("status")).lower()
        status = CARD_STATUS_WORDS.get(raw_status, raw_status or "active")
        if status == "active" and TRIAL_CARD.search(name):
            status = "trial"
        out.append(Card(
            code=code,
            name=name,
            currency=_text(row.get("currency")) or "USD",
            card_number="",          # no PAN in this export, by design
            last4=(masked[-4:] if masked[-4:].isdigit() else ""),
            status=status,
            card_id=_text(row.get("card_id")),
            masked=masked,
            network=_text(row.get("card_network")),
            purpose=_text(row.get("purpose")),
            expiry=_text(row.get("expiry_date")),
            # `email` and `phone` from this table are deliberately not kept:
            # the analysis never needs them, and the owner's address is carried
            # once in `meta` for the report feature instead.
            balance_cents=_money(row.get("balance"), decimal_comma=True),
            total_deposit_cents=_money(row.get("total_deposit"),
                                       decimal_comma=True),
            total_withdrawal_cents=_money(row.get("total_withdrawal"),
                                          decimal_comma=True),
        ))
    return sorted(out, key=lambda c: (c.code or "ZZ", c.name))


# --------------------------------------------------------------- account table

def load_virtual_accounts(rows: list[dict[str, Any]]) -> list[VirtualAccount]:
    out: list[VirtualAccount] = []
    for row in rows:
        number = _text(row.get("account_number"))
        masked = _text(row.get("account_number_masked"))
        raw_status = _text(row.get("status")).lower()
        out.append(VirtualAccount(
            # One row ships an already-masked number and no real one. Storing
            # the mask as the number would make it look like a real account
            # identifier, so it is left empty and only the mask is kept.
            account_number="" if number == masked else number,
            masked=masked or number,
            name=_text(row.get("account_name")),
            nickname=_text(row.get("account_nickname")),
            payout_source=_text(row.get("payout_source")),
            bank_name=_text(row.get("bank_name")),
            swift_bic=_text(row.get("swift_bic")),
            currency=_text(row.get("currency")) or "USD",
            total_received_cents=_money(row.get("total_received")),
            fee_note=_text(row.get("fee")),
            status=CARD_STATUS_WORDS.get(raw_status, raw_status or "active"),
            managed_by=_text(row.get("managed_by")),
        ))
    return sorted(out, key=lambda a: a.label)


# ---------------------------------------------------------- transaction typing

def _card_type(kind: str, reference: str) -> CardTxnType:
    if kind == T_CARD_LOAD:
        return CardTxnType.LOAD
    if kind == T_CARD_WITHDRAW:
        return CardTxnType.WITHDRAW
    if kind == T_CARD_REFUND:
        return CardTxnType.REFUND
    # Everything else on a card is spending — except an FX fee, which the
    # export files under spending but which is the issuer's charge, not a
    # purchase. Typing it as a fee keeps it out of subscription series and out
    # of the spend total.
    return CardTxnType.FEE if FX_FEE.match(reference) else CardTxnType.PURCHASE


def _wallet_note(kind: str, reference: str, cents: int) -> str:
    """What a wallet line did, read from its reference as well as its type.

    The `type` column is worded from the platform's side and cannot be trusted
    alone: `Rút tiền về ví` covers both "wallet pays a card" and "wallet pays
    a crypto address", and `Tham chiếu` ("reference") says nothing at all. The
    reference and the sign settle it.
    """
    if WALLET_TO_CARD.match(reference):
        return "transfer_to_card"
    if WALLET_TO_BANK.match(reference) or WALLET_TO_CRYPTO.match(reference):
        return "payout"
    if WALLET_OPENING.match(reference):
        return "opening"
    if WALLET_FROM_ACCOUNT.match(reference):
        return "payin"
    if WALLET_FROM_CARD.match(reference):
        return "card_to_wallet"
    if kind == T_WALLET_FEE or FX_FEE.match(reference):
        return "fee"
    if kind == T_WALLET_REFERENCE:
        return "payout" if cents < 0 else "payin"
    if kind in (T_WALLET_CREDIT, T_WALLET_CREDIT_FROM_CARD):
        return "payin"
    return "payout" if cents < 0 else "payin"


def _counterparty(reference: str) -> str:
    bank = BANK_NAME.search(reference)
    if bank:
        return bank.group(1)
    chain = CHAIN_NAME.search(reference)
    if chain and WALLET_TO_CRYPTO.match(reference):
        return chain.group(1)
    named = COUNTERPARTY_AFTER_COLON.search(reference)
    return named.group(1).strip() if named else ""


@dataclass
class _TxnFile:
    """What one pass over `transactions_card.csv` produced."""

    card: list[CardTxn]
    wallet_events: list[WalletEvent]
    opening_cents: int
    opening_day: date | None
    notes: list[str]


def load_transactions(rows: list[dict[str, Any]],
                      cards: list[Card]) -> _TxnFile:
    """Split `transactions_card.csv` into the card ledger and the wallet ledger."""
    by_name = {c.name: c for c in cards}
    card_rows: list[CardTxn] = []
    events: list[WalletEvent] = []
    opening_cents = 0
    opening_day: date | None = None
    unknown_status: set[str] = set()
    undated = 0

    for row in rows:
        when = _when(row.get("created_at"))
        if when is None:
            # A row with no timestamp cannot be placed in a period, matched to
            # a receipt, or checked for a duplicate. Dropping it is reported.
            undated += 1
            continue
        ledger = _text(row.get("source_type")).lower()
        kind = _text(row.get("type")).lower()
        reference = _text(row.get("reference"))
        currency = _text(row.get("currency")) or "USD"
        cents = _money_or_zero(row.get("amount"))
        status = _status(row.get("status"), unknown_status)
        txn_id = _text(row.get("transaction_id"))
        name = _text(row.get("card_name"))
        card = by_name.get(name)
        code = _card_code(_text(row.get("card_last4")), reference,
                          card.masked if card else "")

        if ledger == LEDGER_CARD:
            txn = CardTxn(
                card_txn_id=txn_id,
                when=when,
                posted_date=when.date(),
                type=_card_type(kind, reference),
                merchant_raw=reference,
                mcc=_text(row.get("mcc")),
                amount_cents=cents,
                card_number="",
                currency=currency,
                load_ref=_text(row.get("linked_transaction_id")) or None,
                status=status,
                card_code=code or (card.code if card else ""),
                card_name=name,
                ledger=SourceKind.CARD,
                completed_at=_when(row.get("completed_at")),
                user_amount_cents=_money(row.get("user_amount")),
                settled_amount_cents=_money(row.get("settled_amount")),
                fee_cents=_money(row.get("fee")),
                fx_rate=_rate(row.get("exchange_rate")),
                raw_type=_text(row.get("type")),
            )
            # `linked_transaction_id` points at the row itself on every row that
            # has it, so it identifies nothing. Dropped rather than used as a
            # match basis that would always trivially succeed.
            if txn.load_ref == txn.card_txn_id:
                txn.load_ref = None
            card_rows.append(_attach_merchant_card(txn))
            continue

        note = _wallet_note(kind, reference, cents)
        if note == "opening" and opening_day is None:
            opening_cents = cents
            opening_day = when.date()
            continue
        events.append(WalletEvent(
            event_id=txn_id,
            when=when,
            kind="credit" if cents >= 0 else "debit",
            amount_cents=abs(cents),
            # These rows are the wallet's own record, not a copy of a statement
            # line, so there is no account reference to point back at.
            ref=None,
            note=note,
            descriptor=reference,
            currency=currency,
            status=status,
            target_card_code=(code if note == "transfer_to_card" else ""),
            counterparty=_counterparty(reference),
        ))

    notes = [UNKNOWN_STATUS_NOTE.format(value=v) for v in sorted(unknown_status)]
    if undated:
        notes.append(f"{TXN_CSV}: {undated} row(s) had no readable created_at "
                     f"and were left out")
    return _TxnFile(
        card=sorted(card_rows, key=lambda c: (c.when, c.card_txn_id)),
        wallet_events=sorted(events, key=lambda e: (e.when, e.event_id)),
        opening_cents=opening_cents,
        opening_day=opening_day,
        notes=notes,
    )


def build_wallet(parsed: _TxnFile, wallet_id: str) -> Wallet | None:
    if not parsed.wallet_events:
        return None
    first = min(e.when for e in parsed.wallet_events).date()
    return Wallet(
        wallet_id=wallet_id,
        currency="USD",
        opening_balance_cents=parsed.opening_cents,
        opening_date=parsed.opening_day or first,
        # The export states no closing balance. Left unknown so the engine
        # reports "chưa đủ dữ liệu" rather than a gap of exactly zero.
        reported_balance_cents=None,
        reported_at=None,
        events=parsed.wallet_events,
    )


# ---------------------------------------------------------------- stale ledger

def is_stale_duplicate(rows: list[dict[str, Any]],
                       known_ids: set[str]) -> bool:
    """Is this file a superseded copy of the transactions we already have?

    `transactions_va.csv` is named for the receiving accounts but contains no
    `WLF15-VA-` row; its ids are a subset of `transactions_card.csv` in an
    older schema. Detected by content rather than by filename, so a real
    receiving-account ledger dropped in under that name would still be read.
    """
    if not rows:
        return True
    ids = {_text(r.get("transaction_id")) for r in rows}
    ids.discard("")
    if not ids:
        return True
    if any(i.startswith("WLF15-VA-") for i in ids):
        return False
    return ids <= known_ids


def load_legacy_account(rows: list[dict[str, Any]]) -> list[Txn]:
    """Read a receiving-account ledger if one is actually present."""
    out: list[Txn] = []
    unknown: set[str] = set()
    for row in rows:
        when = _when(row.get("created_at") or row.get("Thời gian"))
        if when is None:
            continue
        reference = _text(row.get("reference")
                          or row.get("Nội dung chuyển khoản"))
        kind = _text(row.get("type") or row.get("Loại giao dịch")).lower()
        magnitude = abs(_money_or_zero(row.get("amount") or row.get("Số tiền")))
        if kind.startswith("top") or kind.startswith("nạp"):
            type_ = TxnType.PAYIN
        elif "ví" in reference.lower():
            type_ = TxnType.TRANSFER_TO_WALLET
        else:
            type_ = TxnType.PAYOUT
        txn = Txn(
            txn_id=_text(row.get("transaction_id") or row.get("Id")),
            when=when,
            posted_date=when.date(),
            type=type_,
            description=reference or kind,
            counterparty=_counterparty(reference),
            amount_cents=magnitude if type_ is TxnType.PAYIN else -magnitude,
            currency=_text(row.get("currency")
                           or row.get("Đơn vị tiền tệ")) or "USD",
            balance_after_cents=None,
            status=_status(row.get("status") or row.get("Trạng thái"), unknown),
            account_ref=_text(row.get("account_number") or row.get("Số thẻ")),
        )
        out.append(_attach_merchant_txn(txn))
    return sorted(out, key=lambda t: (t.when, t.txn_id))


# --------------------------------------------------------------------- mailbox

# The origin sender stops at whichever marker comes next. `Người nhận:` was
# added to some bodies; without it in the stop set the recipient address gets
# swallowed into the sender and every look-alike check reads the wrong domain.
ORIGIN_SENDER = re.compile(
    r"Người gửi gốc \(CSV\):\s*(?P<who>.+?)\s+(?=Người nhận:|Email id:)"
)
RECIPIENT = re.compile(r"Người nhận:\s*(?P<to>\S+@\S+)")
EMAIL_ID = re.compile(r"Email id:\s*(?P<id>EM-\d+)")
CSV_WHEN = re.compile(r"Thời điểm CSV:\s*(?P<when>\d{4}-\d{2}-\d{2} \d{2}:\d{2})")
ORDER_NO = re.compile(r"Wealify order_no:\s*(?P<ref>\S+)")
BODY_AMOUNT = re.compile(
    r"Số tiền:\s*(?P<amount>[\d.,]+)\s*(?P<currency>[A-Z]{3})"
    r"(?:\s*\(~\s*(?P<usd>[\d.,]+)\s*USD\))?"
)
BODY_KIND = re.compile(r"Loại:\s*(?P<kind>\S+)")
BODY_CARD = re.compile(r"Thẻ:\s*(?P<code>VC\d{2})")
ADDR = re.compile(r"^\s*(?P<name>[^<]*?)\s*<(?P<addr>[^>]+)>\s*$")

GENRE_BY_KIND = {"purchase": "receipt", "payin": "bank_notice"}


def _split_addr(raw: str) -> tuple[str, str]:
    m = ADDR.match(raw or "")
    if m:
        return m.group("name").strip(), m.group("addr").strip().lower()
    return "", (raw or "").strip().lower()


def _split_list(raw: Any, *separators: str) -> list[str]:
    text = str(raw or "")
    parts = [text]
    for sep in separators:
        parts = [p for chunk in parts for p in chunk.split(sep)]
    return [p.strip() for p in parts if p.strip()]


def load_emails(rows: list[dict[str, Any]]) -> list[EmailMsg]:
    """Rebuild each message from the relay envelope plus the body it wraps.

    The export's column names do not describe their contents: `From` holds the
    subject and `Date` holds the From header. The columns are read by their
    position in the schema, not by trusting the name.
    """
    out: list[EmailMsg] = []
    for row in rows:
        body = _text(row.get("Body Text"))
        subject = _text(row.get("Subject"))
        relay_name, relay_addr = _split_addr(_text(row.get("Date")))

        origin = ORIGIN_SENDER.search(body)
        if origin:
            from_name, from_addr = _split_addr(origin.group("who"))
        else:
            from_name, from_addr = relay_name, relay_addr

        stamp = CSV_WHEN.search(body)
        when = (datetime.strptime(stamp.group("when"), "%Y-%m-%d %H:%M")
                if stamp else _when(row.get("Scraped At")))
        if when is None:
            continue

        amounts: list[int] = []
        currency = "USD"
        money = BODY_AMOUNT.search(body)
        if money:
            currency = money.group("currency")
            charged = _money(money.group("amount"))
            if charged is not None:
                amounts.append(charged)
            if money.group("usd"):
                # Both figures are kept: the card ledger records the charge in
                # its own currency, the wallet records the USD it settled at,
                # and a receipt has to be matchable against either.
                settled = _money(money.group("usd"))
                if settled is not None:
                    amounts.append(settled)

        kind = BODY_KIND.search(body)
        order = ORDER_NO.search(body)
        email_id = EMAIL_ID.search(body)
        recipient = RECIPIENT.search(body)
        card = BODY_CARD.search(body)

        out.append(EmailMsg(
            message_id=_text(row.get("ID")) or (email_id.group("id")
                                                if email_id else ""),
            from_name=from_name,
            from_addr=from_addr,
            reply_to=None,           # the export carries no Reply-To header
            to_addr=(recipient.group("to").lower() if recipient
                     else _text(row.get("Inbox")).lower()),
            subject=subject,
            when=when,
            body=body,
            genre=GENRE_BY_KIND.get(kind.group("kind") if kind else "", "other"),
            amounts_cents=amounts,
            relay_from_name=relay_name,
            relay_from_addr=relay_addr,
            txn_ref=order.group("ref") if order else None,
            card_code=card.group("code") if card else "",
            currency=currency,
            links=_split_list(row.get("Extracted Links"), ",", ";"),
            codes=_split_list(row.get("Extracted Codes"), ";"),
        ))
    return sorted(out, key=lambda e: (e.when, e.message_id))


def load_mailboxes(data_dir: Path) -> dict[str, list[EmailMsg]]:
    """Every `email_*.csv` in the directory, keyed by its suffix.

    `email_tester.csv` becomes `"tester"`. The files are variants of one
    mailbox at different noise levels, not different users — they reference the
    same transactions — so they are kept apart and one is chosen, never merged.
    Merging would let a message addressed to one inbox stand as the receipt for
    a transaction proved by another.
    """
    out: dict[str, list[EmailMsg]] = {}
    for path in sorted(data_dir.glob(EMAIL_GLOB)):
        name = path.stem
        key = name[len("email_"):] if name.startswith("email_") else name
        emails = load_emails(read_csv(path))
        if emails:
            out[key] = emails
    return out


# ---------------------------------------------------------------- full dataset

MISSING_VA_LEDGER_NOTE = (
    "This export lists {n} receiving account(s) but ships no transaction rows "
    "for them, so account-level checks (duplicate deposits, account → wallet "
    "matching) report insufficient data rather than a result"
)
STALE_VA_NOTE = (
    "{name} was skipped: it holds no WLF15-VA- row and its ids duplicate "
    "{txn} in an older schema, so reading it would double every card figure"
)


def _pick_mailbox(mailboxes: dict[str, list[EmailMsg]], owner_email: str,
                  prefer: str | None) -> tuple[str, list[EmailMsg]]:
    """Which inbox to analyse.

    An explicit choice wins. Otherwise the inbox whose address matches the one
    the card table registers, so the mailbox and the cards belong to the same
    person. Failing that, the largest inbox.
    """
    if not mailboxes:
        return "", []
    if prefer and prefer in mailboxes:
        return prefer, mailboxes[prefer]
    if owner_email:
        for key, emails in mailboxes.items():
            if any(e.to_addr == owner_email for e in emails):
                return key, emails
    key = max(mailboxes, key=lambda k: len(mailboxes[k]))
    return key, mailboxes[key]


def load_export_dataset(data_dir: Path, mailbox: str | None = None) -> Dataset:
    """Build a `Dataset` from the Wealify CSV export directory."""
    card_rows = read_csv(data_dir / CARDS_CSV)
    cards = load_cards(card_rows)
    accounts = load_virtual_accounts(read_csv(data_dir / ACCOUNTS_CSV))
    txn_rows = read_csv(data_dir / TXN_CSV)
    parsed = load_transactions(txn_rows, cards)
    wallet = build_wallet(parsed, wallet_id="WLF15-WALLET")
    notes = list(parsed.notes)

    # Taken from the raw rows, not from the parsed objects: the opening-balance
    # row is consumed into the wallet's opening figure and keeps no event of
    # its own, and leaving its id out here would make a stale copy of this same
    # file look like a ledger we do not have.
    known_ids = {_text(r.get("transaction_id")) for r in txn_rows}
    known_ids.discard("")
    account: list[Txn] = []
    legacy = data_dir / LEGACY_VA_CSV
    if legacy.exists():
        rows = read_csv(legacy)
        if is_stale_duplicate(rows, known_ids):
            notes.append(STALE_VA_NOTE.format(name=LEGACY_VA_CSV, txn=TXN_CSV))
        else:
            account = load_legacy_account(rows)
    if not account and accounts:
        notes.append(MISSING_VA_LEDGER_NOTE.format(n=len(accounts)))

    mailboxes = load_mailboxes(data_dir)
    owner_email = _owner_email(card_rows)
    mailbox_key, emails = _pick_mailbox(mailboxes, owner_email, mailbox)
    if not owner_email and emails:
        owner_email = emails[0].to_addr
    notes.append(
        f"{TXN_CSV}: timestamps are UTC throughout (57 rows say so with a Z "
        f"suffix, the rest do not) — 7 hours behind the Vietnam wall-clock "
        f"times the earlier export used"
    )
    if len(mailboxes) > 1:
        others = ", ".join(f"{k} ({len(v)})" for k, v in sorted(mailboxes.items())
                           if k != mailbox_key)
        notes.append(f"mailbox '{mailbox_key}' ({len(emails)}) is the one "
                     f"analysed; also present: {others}")

    days = ([t.day for t in account] + [c.day for c in parsed.card]
            + [e.day for e in parsed.wallet_events]
            + ([wallet.opening_date] if wallet else []))
    statement_date = max(days) if days else date.today()
    period_start = min(days) if days else statement_date

    meta = {
        "owner_name": "",
        "owner_email": owner_email,
        "account_number": next((a.account_number for a in accounts
                                if a.account_number), ""),
        "card_number": "",
        "card_brand": next((c.network for c in cards if c.network),
                           "Wealify virtual card (sample)"),
        "statement_date": statement_date.isoformat(),
        "period_start": period_start.isoformat(),
        "currency": "USD",
        "mailbox": mailbox_key,
        "mailboxes": {k: len(v) for k, v in sorted(mailboxes.items())},
        "cards": [{"code": c.code, "card_id": c.card_id, "name": c.name,
                   "currency": c.currency, "status": c.status} for c in cards],
        "virtual_accounts": [{"masked": a.masked, "label": a.label,
                              "currency": a.currency, "status": a.status,
                              "payout_source": a.payout_source}
                             for a in accounts],
        "note": "Wealify WLF-15 sample export. Synthetic data, no real person.",
    }
    return Dataset(
        meta=meta,
        account=account,
        card=parsed.card,
        wallet=wallet,
        emails=emails,
        cards=cards,
        virtual_accounts=accounts,
        mailboxes=mailboxes,
        notes=notes,
        source_files={
            "account": (LEGACY_VA_CSV if account
                        else f"{ACCOUNTS_CSV} (totals only, no ledger)"),
            "card": f"{TXN_CSV} (source_type=Thẻ)",
            "wallet": f"{TXN_CSV} (source_type=Ví)",
            "cards": CARDS_CSV,
            "mailbox": f"email_{mailbox_key}.csv" if mailbox_key else "",
        },
    )


def _owner_email(card_rows: list[dict[str, Any]]) -> str:
    """The address the card table registers for the account holder."""
    for row in card_rows:
        found = _text(row.get("email"))
        if found:
            return found.lower()
    return ""
