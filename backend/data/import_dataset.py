"""Import the Wealify CSV export into the canonical Postgres tables.

The loader remains the single authority for interpreting the export's odd
delimiters, encodings, dates, money formats and stale VA file.  This command
stores both the normalized entities and every source row, so a later export can
be imported again without losing provenance.

Usage:
    python -m data.import_dataset
    python -m data.import_dataset --mailbox senior
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.config import settings
from app.db.migrations import apply_migrations
from app.engine.loader_wlf import (
    _decode,
    _money,
    _rate,
    _text,
    _when,
    load_export_dataset,
    read_csv,
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _date(value: str) -> Any:
    parsed = _when(value)
    return parsed.date() if parsed else None


def _timestamp(value: str) -> datetime | None:
    return _when(value)


def _money_or_none(value: Any, *, decimal_comma: bool = False) -> int | None:
    return _money(value, decimal_comma=decimal_comma)


def _execute_one(conn: psycopg.Connection, sql: str, params: tuple[Any, ...]) -> dict[str, Any]:
    return conn.execute(sql, params).fetchone()


def _file_kind(name: str) -> str:
    if name == "cards.csv":
        return "cards"
    if name == "virtual_accounts.csv":
        return "virtual_accounts"
    if name == "transactions_card.csv":
        return "transactions"
    if name == "transactions_va.csv":
        return "legacy_transactions"
    return "emails"


def _source_files(conn: psycopg.Connection, data_dir: Path, import_id: int,
                  known_transaction_ids: set[str]) -> dict[str, int]:
    """Persist file metadata and all raw rows; return file-name -> id."""
    result: dict[str, int] = {}
    for path in sorted(data_dir.glob("*.csv")):
        text, encoding = _decode(path)
        delimiter = ";" if text.splitlines()[0].count(";") > text.splitlines()[0].count(",") else ","
        rows = read_csv(path)
        stale = path.name == "transactions_va.csv" and bool(rows) and all(
            _text(row.get("transaction_id")) in known_transaction_ids
            for row in rows
        )
        skip_reason = (
            "stale duplicate of transactions_card.csv; retained as raw rows only"
            if stale else None
        )
        file_row = _execute_one(
            conn,
            """
            INSERT INTO dataset_files
                (import_id, file_name, file_kind, sha256, encoding, delimiter,
                 row_count, is_canonical, skip_reason, header)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                import_id, path.name, _file_kind(path.name),
                hashlib.sha256(path.read_bytes()).hexdigest(), encoding, delimiter,
                len(rows), not stale, skip_reason,
                _json(list(rows[0].keys()) if rows else text.splitlines()[0].split(delimiter)),
            ),
        )
        file_id = file_row["id"]
        result[path.name] = file_id
        for row_number, row in enumerate(rows, start=1):
            conn.execute(
                """
                INSERT INTO dataset_rows (file_id, row_number, payload,
                                          is_canonical, skip_reason)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (file_id, row_number) DO UPDATE SET
                    payload = EXCLUDED.payload,
                    is_canonical = EXCLUDED.is_canonical,
                    skip_reason = EXCLUDED.skip_reason
                """,
                (file_id, row_number, _json(row), not stale, skip_reason),
            )
    return result


def _upsert_cards(conn: psycopg.Connection, data_dir: Path, import_id: int) -> dict[str, str]:
    rows = read_csv(data_dir / "cards.csv")
    by_id = {_text(row.get("card_id")): row for row in rows}
    cards = load_export_dataset(data_dir).cards
    card_codes: dict[str, str] = {}
    for card in cards:
        raw = by_id.get(card.card_id, {})
        created = _timestamp(_text(raw.get("created_at")))
        expiry = _date(_text(raw.get("expiry_date")))
        card_code = card.code or None
        conn.execute(
            """
            INSERT INTO cards
                (card_id, card_code, card_name, last4, card_number_masked,
                 expiry_date, status, balance_cents, currency,
                 total_deposit_cents, total_withdrawal_cents, purpose, email,
                 phone, card_network, created_at, source_import_id, raw_payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s)
            ON CONFLICT (card_id) DO UPDATE SET
                card_code = EXCLUDED.card_code,
                card_name = EXCLUDED.card_name,
                last4 = EXCLUDED.last4,
                card_number_masked = EXCLUDED.card_number_masked,
                expiry_date = EXCLUDED.expiry_date,
                status = EXCLUDED.status,
                balance_cents = EXCLUDED.balance_cents,
                currency = EXCLUDED.currency,
                total_deposit_cents = EXCLUDED.total_deposit_cents,
                total_withdrawal_cents = EXCLUDED.total_withdrawal_cents,
                purpose = EXCLUDED.purpose,
                email = EXCLUDED.email,
                phone = EXCLUDED.phone,
                card_network = EXCLUDED.card_network,
                created_at = EXCLUDED.created_at,
                source_import_id = EXCLUDED.source_import_id,
                raw_payload = EXCLUDED.raw_payload
            """,
            (
                card.card_id, card_code, card.name, card.last4,
                card.masked or None, expiry, card.status, card.balance_cents,
                card.currency, card.total_deposit_cents,
                card.total_withdrawal_cents, card.purpose,
                _text(raw.get("email")) or None, _text(raw.get("phone")) or None,
                card.network, created, import_id, _json(raw),
            ),
        )
        if card_code:
            card_codes[card_code] = card.card_id
    return card_codes


def _upsert_virtual_accounts(conn: psycopg.Connection, data_dir: Path,
                             import_id: int) -> dict[str, int]:
    rows = read_csv(data_dir / "virtual_accounts.csv")
    accounts = load_export_dataset(data_dir).virtual_accounts
    by_key: dict[str, int] = {}
    for account in accounts:
        raw = next(
            (row for row in rows
             if _text(row.get("account_name")) == account.name
             and _text(row.get("account_number_masked")) == account.masked),
            {},
        )
        account_number = account.account_number or None
        external_key = account_number or f"{account.name}|{account.masked}"
        created = _timestamp(_text(raw.get("created_at")))
        row = _execute_one(
            conn,
            """
            INSERT INTO virtual_accounts
                (external_key, account_name, account_nickname, account_number,
                 account_number_masked, payout_source, bank_name, swift_bic,
                 total_received_cents, currency, fee_note, status, managed_by,
                 created_at, source_import_id, raw_payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s)
            ON CONFLICT (external_key) DO UPDATE SET
                account_name = EXCLUDED.account_name,
                account_nickname = EXCLUDED.account_nickname,
                account_number = EXCLUDED.account_number,
                account_number_masked = EXCLUDED.account_number_masked,
                payout_source = EXCLUDED.payout_source,
                bank_name = EXCLUDED.bank_name,
                swift_bic = EXCLUDED.swift_bic,
                total_received_cents = EXCLUDED.total_received_cents,
                currency = EXCLUDED.currency,
                fee_note = EXCLUDED.fee_note,
                status = EXCLUDED.status,
                managed_by = EXCLUDED.managed_by,
                created_at = EXCLUDED.created_at,
                source_import_id = EXCLUDED.source_import_id,
                raw_payload = EXCLUDED.raw_payload
            RETURNING id
            """,
            (
                external_key, account.name, account.nickname or None,
                account_number, account.masked, account.payout_source or None,
                account.bank_name or None, account.swift_bic or None,
                account.total_received_cents, account.currency, account.fee_note or None,
                account.status, account.managed_by or None, created, import_id,
                _json(raw),
            ),
        )
        by_key[external_key] = row["id"]
        if account_number:
            by_key[account_number] = row["id"]
    return by_key


def _upsert_wallet(conn: psycopg.Connection, dataset: Any, import_id: int) -> int | None:
    wallet = dataset.wallet
    if wallet is None:
        return None
    row = _execute_one(
        conn,
        """
        INSERT INTO wallets
            (wallet_key, currency, opening_balance_cents, opening_date,
             reported_balance_cents, reported_at, source_import_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (wallet_key) DO UPDATE SET
            currency = EXCLUDED.currency,
            opening_balance_cents = EXCLUDED.opening_balance_cents,
            opening_date = EXCLUDED.opening_date,
            reported_balance_cents = EXCLUDED.reported_balance_cents,
            reported_at = EXCLUDED.reported_at,
            source_import_id = EXCLUDED.source_import_id
        RETURNING id
        """,
        (wallet.wallet_id, wallet.currency, wallet.opening_balance_cents,
         wallet.opening_date, wallet.reported_balance_cents,
         wallet.reported_at, import_id),
    )
    return row["id"]


def _upsert_transactions(conn: psycopg.Connection, data_dir: Path, dataset: Any, import_id: int,
                         file_ids: dict[str, int], card_codes: dict[str, str],
                         account_ids: dict[str, int], wallet_id: int | None) -> None:
    source_file_id = file_ids.get("transactions_card.csv")
    raw_rows = read_csv(data_dir / "transactions_card.csv")
    raw_by_id = {_text(row.get("transaction_id")): row for row in raw_rows}
    for txn in dataset.card:
        raw = raw_by_id.get(txn.card_txn_id, {})
        _upsert_transaction(
            conn, import_id, source_file_id, txn.card_txn_id, "card",
            txn.when, txn.completed_at, txn.posted_date, txn.raw_type,
            txn.type.value, _text(raw.get("source_type")) or "Thẻ",
            txn.card_name, txn.card_code,
            txn.merchant_raw, txn.amount_cents, txn.user_amount_cents,
            txn.settled_amount_cents, txn.fx_rate, txn.currency, txn.status.value,
            _text(raw.get("linked_transaction_id")) or txn.load_ref,
            txn.fee_cents, txn.merchant, txn.mcc,
            _text(raw.get("gateway_ref")) or None, None,
            card_codes.get(txn.card_code), None, None, _json(raw),
        )

    if wallet_id is not None and dataset.wallet:
        for event in dataset.wallet.events:
            raw = raw_by_id.get(event.event_id, {})
            _upsert_transaction(
                conn, import_id, source_file_id, event.event_id, "wallet",
                event.when, _when(raw.get("completed_at")), event.when.date(),
                _text(raw.get("type")), event.note,
                _text(raw.get("source_type")) or "Ví", "",
                event.target_card_code, event.descriptor,
                event.signed_cents, None, None, None, event.currency,
                event.status.value, _text(raw.get("linked_transaction_id")) or None,
                _money_or_none(raw.get("fee")), _text(raw.get("merchant")) or None,
                _text(raw.get("mcc")) or None, _text(raw.get("gateway_ref")) or None,
                _text(raw.get("notes")) or None,
                card_codes.get(event.target_card_code), None, wallet_id,
                _json(raw),
            )

    for txn in dataset.account:
        _upsert_transaction(
            conn, import_id, file_ids.get("transactions_va.csv"), txn.txn_id,
            "virtual_account", txn.when, None, txn.posted_date, "",
            txn.type.value, "Virtual account", "", "", txn.description,
            txn.amount_cents, None, None, None, txn.currency, txn.status.value,
            None, None, txn.merchant, None, None, None, None,
            account_ids.get(txn.account_ref), None,
            _json({"txn_id": txn.txn_id}),
        )


def _upsert_transaction(conn: psycopg.Connection, import_id: int,
                        file_id: int | None, transaction_id: str, ledger: str,
                        created_at: datetime, completed_at: datetime | None,
                        posted_date: Any, raw_type: str, normalized_type: str,
                        source_type: str, card_name: str, card_last4: str,
                        reference: str, amount_cents: int,
                        user_amount_cents: int | None, settled_amount_cents: int | None,
                        exchange_rate: float | None, currency: str, status: str,
                        linked_transaction_id: str | None, fee_cents: int | None,
                        merchant: str | None, mcc: str | None, gateway_ref: str | None,
                        notes: str | None, card_id: str | None,
                        virtual_account_id: int | None,
                        wallet_id: int | None, raw_payload: str) -> None:
    conn.execute(
        """
        INSERT INTO financial_transactions
            (transaction_id, ledger, source_file_id, source_import_id, card_id,
             virtual_account_id, wallet_id, created_at, completed_at, posted_date,
             raw_type,
             normalized_type, source_type, card_name, card_last4, reference,
             amount_cents, user_amount_cents, settled_amount_cents, exchange_rate,
             currency, status, linked_transaction_id, fee_cents, merchant, mcc,
             gateway_ref, notes, raw_payload)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (ledger, transaction_id) DO UPDATE SET
            source_file_id = EXCLUDED.source_file_id,
            source_import_id = EXCLUDED.source_import_id,
            card_id = EXCLUDED.card_id,
            virtual_account_id = EXCLUDED.virtual_account_id,
            wallet_id = EXCLUDED.wallet_id,
            created_at = EXCLUDED.created_at,
            completed_at = EXCLUDED.completed_at,
            posted_date = EXCLUDED.posted_date,
            raw_type = EXCLUDED.raw_type,
            normalized_type = EXCLUDED.normalized_type,
            source_type = EXCLUDED.source_type,
            card_name = EXCLUDED.card_name,
            card_last4 = EXCLUDED.card_last4,
            reference = EXCLUDED.reference,
            amount_cents = EXCLUDED.amount_cents,
            user_amount_cents = EXCLUDED.user_amount_cents,
            settled_amount_cents = EXCLUDED.settled_amount_cents,
            exchange_rate = EXCLUDED.exchange_rate,
            currency = EXCLUDED.currency,
            status = EXCLUDED.status,
            linked_transaction_id = EXCLUDED.linked_transaction_id,
            fee_cents = EXCLUDED.fee_cents,
            merchant = EXCLUDED.merchant,
            mcc = EXCLUDED.mcc,
            gateway_ref = EXCLUDED.gateway_ref,
            notes = EXCLUDED.notes,
            raw_payload = EXCLUDED.raw_payload
        """,
        (transaction_id, ledger, file_id, import_id, card_id, virtual_account_id,
         wallet_id, created_at, completed_at, posted_date, raw_type, normalized_type,
         source_type, card_name, card_last4, reference, amount_cents,
         user_amount_cents, settled_amount_cents, exchange_rate, currency,
         status, linked_transaction_id, fee_cents, merchant, mcc, gateway_ref,
         notes, raw_payload),
    )


def _upsert_wallet_events(conn: psycopg.Connection, dataset: Any, import_id: int,
                          file_ids: dict[str, int], card_codes: dict[str, str],
                          wallet_id: int | None) -> None:
    if wallet_id is None or dataset.wallet is None:
        return
    for event in dataset.wallet.events:
        conn.execute(
            """
            INSERT INTO wallet_events
                (event_id, wallet_id, source_import_id, source_transaction_id,
                 event_at, kind, amount_cents, reference, note, descriptor,
                 currency, status, target_card_id, counterparty, raw_payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (event_id) DO UPDATE SET
                wallet_id = EXCLUDED.wallet_id,
                source_import_id = EXCLUDED.source_import_id,
                source_transaction_id = EXCLUDED.source_transaction_id,
                event_at = EXCLUDED.event_at,
                kind = EXCLUDED.kind,
                amount_cents = EXCLUDED.amount_cents,
                reference = EXCLUDED.reference,
                note = EXCLUDED.note,
                descriptor = EXCLUDED.descriptor,
                currency = EXCLUDED.currency,
                status = EXCLUDED.status,
                target_card_id = EXCLUDED.target_card_id,
                counterparty = EXCLUDED.counterparty,
                raw_payload = EXCLUDED.raw_payload
            """,
            (event.event_id, wallet_id, import_id, event.event_id, event.when,
             event.kind, event.amount_cents, event.ref, event.note,
             event.descriptor, event.currency, event.status.value,
             card_codes.get(event.target_card_code), event.counterparty,
             _json({"event_id": event.event_id, "descriptor": event.descriptor})),
        )


def _upsert_emails(conn: psycopg.Connection, data_dir: Path, dataset: Any,
                   import_id: int, file_ids: dict[str, int],
                   card_codes: dict[str, str]) -> None:
    for mailbox, emails in dataset.mailboxes.items():
        file_id = file_ids.get(f"email_{mailbox}.csv")
        raw_rows = read_csv(data_dir / f"email_{mailbox}.csv")
        raw_by_id = {_text(row.get("ID")): row for row in raw_rows}
        for email in emails:
            raw = raw_by_id.get(email.message_id, {})
            row = _execute_one(
                conn,
                """
                INSERT INTO emails
                    (mailbox, message_id, inbox, from_name, from_addr, reply_to,
                     to_addr, relay_from_name, relay_from_addr, subject, sent_at,
                     body_text, genre, transaction_ref, card_id, currency,
                     html_file, source_file_id, source_import_id, raw_payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (mailbox, message_id) DO UPDATE SET
                    inbox = EXCLUDED.inbox,
                    from_name = EXCLUDED.from_name,
                    from_addr = EXCLUDED.from_addr,
                    reply_to = EXCLUDED.reply_to,
                    to_addr = EXCLUDED.to_addr,
                    relay_from_name = EXCLUDED.relay_from_name,
                    relay_from_addr = EXCLUDED.relay_from_addr,
                    subject = EXCLUDED.subject,
                    sent_at = EXCLUDED.sent_at,
                    body_text = EXCLUDED.body_text,
                    genre = EXCLUDED.genre,
                    transaction_ref = EXCLUDED.transaction_ref,
                    card_id = EXCLUDED.card_id,
                    currency = EXCLUDED.currency,
                    html_file = EXCLUDED.html_file,
                    source_file_id = EXCLUDED.source_file_id,
                    source_import_id = EXCLUDED.source_import_id,
                    raw_payload = EXCLUDED.raw_payload
                RETURNING id
                """,
                (mailbox, email.message_id, email.to_addr, email.from_name,
                 email.from_addr, email.reply_to, email.to_addr,
                 email.relay_from_name, email.relay_from_addr, email.subject,
                 email.when, email.body, email.genre, email.txn_ref,
                 card_codes.get(email.card_code), email.currency,
                 _text(raw.get("HTML File")) or None, file_id, import_id,
                 _json(raw)),
            )
            email_id = row["id"]
            conn.execute("DELETE FROM email_amounts WHERE email_id = %s", (email_id,))
            conn.execute("DELETE FROM email_links WHERE email_id = %s", (email_id,))
            conn.execute("DELETE FROM email_codes WHERE email_id = %s", (email_id,))
            for ordinal, amount in enumerate(email.amounts_cents, start=1):
                conn.execute(
                    "INSERT INTO email_amounts (email_id, ordinal, amount_cents) VALUES (%s, %s, %s)",
                    (email_id, ordinal, amount),
                )
            for url in email.links:
                conn.execute("INSERT INTO email_links (email_id, url) VALUES (%s, %s) ON CONFLICT DO NOTHING", (email_id, url))
            for code in email.codes:
                conn.execute("INSERT INTO email_codes (email_id, code) VALUES (%s, %s) ON CONFLICT DO NOTHING", (email_id, code))


def import_dataset(data_dir: Path, mailbox: str | None = None,
                   dsn: str | None = None) -> dict[str, int]:
    apply_migrations(dsn)
    dataset = load_export_dataset(data_dir, mailbox=mailbox)
    transaction_rows = read_csv(data_dir / "transactions_card.csv")
    known_ids = {_text(row.get("transaction_id")) for row in transaction_rows}
    known_ids.discard("")

    with psycopg.connect(dsn or settings.database_url, row_factory=dict_row) as conn:
        import_row = _execute_one(
            conn,
            """
            INSERT INTO dataset_imports
                (source_dir, selected_mailbox, status, metadata)
            VALUES (%s, %s, 'completed', %s)
            RETURNING id
            """,
            (str(data_dir.resolve()), dataset.meta.get("mailbox", mailbox or ""),
             _json(dataset.meta)),
        )
        import_id = import_row["id"]
        file_ids = _source_files(conn, data_dir, import_id, known_ids)
        card_codes = _upsert_cards(conn, data_dir, import_id)
        account_ids = _upsert_virtual_accounts(conn, data_dir, import_id)
        wallet_id = _upsert_wallet(conn, dataset, import_id)
        _upsert_transactions(conn, data_dir, dataset, import_id, file_ids, card_codes,
                             account_ids, wallet_id)
        _upsert_wallet_events(conn, dataset, import_id, file_ids, card_codes,
                              wallet_id)
        _upsert_emails(conn, data_dir, dataset, import_id, file_ids, card_codes)
        conn.execute(
            "UPDATE dataset_imports SET finished_at = now(), file_count = %s, row_count = %s WHERE id = %s",
            (len(file_ids), sum(len(read_csv(path)) for path in data_dir.glob("*.csv")), import_id),
        )
        counts = {
            "import_id": import_id,
            "files": len(file_ids),
            "cards": conn.execute("SELECT count(*) AS n FROM cards").fetchone()["n"],
            "virtual_accounts": conn.execute("SELECT count(*) AS n FROM virtual_accounts").fetchone()["n"],
            "transactions": conn.execute("SELECT count(*) AS n FROM financial_transactions").fetchone()["n"],
            "wallet_events": conn.execute("SELECT count(*) AS n FROM wallet_events").fetchone()["n"],
            "emails": conn.execute("SELECT count(*) AS n FROM emails").fetchone()["n"],
            "raw_rows": conn.execute("SELECT count(*) AS n FROM dataset_rows").fetchone()["n"],
        }
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Import dataset CSVs into Nexa Postgres")
    parser.add_argument("--data-dir", type=Path, default=settings.data_dir)
    parser.add_argument("--mailbox", default=None, help="Mailbox to mark as selected (tester/senior/junior)")
    parser.add_argument("--dsn", default=None)
    args = parser.parse_args()
    counts = import_dataset(args.data_dir, args.mailbox, args.dsn)
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
