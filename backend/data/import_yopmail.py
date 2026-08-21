"""Import a YOPmail scraper JSON export into the canonical email tables.

The scraper output is deliberately kept as JSON/HTML files.  This command
normalizes the JSON into ``emails`` while retaining the original records in
``dataset_rows`` so a cron run remains auditable and repeatable.

Usage::

    python -m data.import_yopmail --input ../scripts/yopmail_scraper/output/wealifytester/emails_full.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.config import settings
from app.db.migrations import apply_migrations
from app.engine.loader_wlf import load_emails


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON array in {path}")
    if not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"Every item in {path} must be an object")
    return payload


def _loader_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Adapt scraper field names to the existing WLF email normalizer.

    ``load_emails`` intentionally extracts the real sender and event time from
    the body because the sandbox relay export has misleading envelope columns.
    The same behavior is useful for YOPmail records: the body is authoritative
    when it contains the original sender and the CSV event timestamp.
    """
    rows: list[dict[str, Any]] = []
    for record in records:
        message_id = str(record.get("id") or "").strip()
        inbox = str(record.get("inbox") or "").strip().lower()
        if not message_id or not inbox:
            continue

        links = record.get("extracted_links") or []
        codes = record.get("extracted_codes") or []
        if not isinstance(links, list):
            links = [links]
        if not isinstance(codes, list):
            codes = [codes]

        # Existing scraper versions put the relay sender in `date`; newer
        # versions may put the actual date there. Only retain it as a relay
        # address when it looks like an address/header.
        date_field = str(record.get("date") or "").strip()
        relay = date_field if "@" in date_field else ""
        rows.append({
            "ID": message_id,
            "Inbox": inbox,
            "Subject": str(record.get("subject") or "").strip(),
            "Date": relay,
            "Body Text": str(record.get("body_text") or ""),
            "Extracted Links": ";".join(str(item) for item in links if item),
            "Extracted Codes": ";".join(str(item) for item in codes if item),
            "Scraped At": str(record.get("scraped_at") or ""),
        })
    return rows


def _card_ids(conn: psycopg.Connection) -> dict[str, str]:
    return {
        row["card_code"]: row["card_id"]
        for row in conn.execute(
            "SELECT card_code, card_id FROM cards WHERE card_code IS NOT NULL"
        ).fetchall()
    }


def _default_mailbox(inbox: str) -> str:
    user = inbox.split("@", 1)[0].strip()
    return user[7:] if user.lower().startswith("wealify") else user


def import_yopmail(input_path: Path, mailbox: str | None = None,
                   html_root: Path | None = None,
                   dsn: str | None = None) -> dict[str, int]:
    """Import one scraper JSON file and upsert its messages."""
    input_path = input_path.resolve()
    records = _records(input_path)
    rows = _loader_rows(records)
    messages = load_emails(rows)
    if len(messages) != len(rows):
        raise ValueError(
            f"Could not parse {len(rows) - len(messages)} email record(s); "
            "each record needs a body timestamp or scraped_at"
        )

    selected_mailbox = (mailbox or "").strip()
    if not selected_mailbox and records:
        selected_mailbox = _default_mailbox(str(records[0].get("inbox") or ""))
    selected_mailbox = selected_mailbox or "yopmail"
    source_dir = (html_root or input_path.parent).resolve()
    metadata = {
        "source": "yopmail_scraper",
        "input": str(input_path),
        "mailbox": selected_mailbox,
        "record_count": len(records),
    }

    apply_migrations(dsn)
    with psycopg.connect(dsn or settings.database_url, row_factory=dict_row) as conn:
        import_row = conn.execute(
            """
            INSERT INTO dataset_imports
                (source_dir, selected_mailbox, status, metadata)
            VALUES (%s, %s, 'completed', %s)
            RETURNING id
            """,
            (str(source_dir), selected_mailbox, _json(metadata)),
        ).fetchone()
        import_id = import_row["id"]

        file_row = conn.execute(
            """
            INSERT INTO dataset_files
                (import_id, file_name, file_kind, sha256, encoding, delimiter,
                 row_count, is_canonical, header)
            VALUES (%s, %s, 'yopmail_emails', %s, 'utf-8', 'json', %s, TRUE, %s)
            RETURNING id
            """,
            (
                import_id,
                str(input_path.relative_to(source_dir)
                    if input_path.is_relative_to(source_dir) else input_path),
                hashlib.sha256(input_path.read_bytes()).hexdigest(),
                len(records),
                _json(list(records[0].keys()) if records else []),
            ),
        ).fetchone()
        file_id = file_row["id"]

        for row_number, record in enumerate(records, start=1):
            conn.execute(
                """
                INSERT INTO dataset_rows (file_id, row_number, payload)
                VALUES (%s, %s, %s)
                ON CONFLICT (file_id, row_number) DO UPDATE SET
                    payload = EXCLUDED.payload
                """,
                (file_id, row_number, _json(record)),
            )

        card_ids = _card_ids(conn)
        records_by_id = {
            str(record.get("id") or "").strip(): record for record in records
        }
        inserted = 0
        updated = 0
        for message in messages:
            record = records_by_id.get(message.message_id, {})
            raw = dict(record)
            html_file = str(record.get("body_html_file") or "").strip() or None
            card_id = card_ids.get(message.card_code)
            row = conn.execute(
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
                RETURNING id, (xmax = 0) AS inserted
                """,
                (
                    selected_mailbox,
                    message.message_id,
                    message.to_addr,
                    message.from_name,
                    message.from_addr,
                    message.reply_to,
                    message.to_addr,
                    message.relay_from_name,
                    message.relay_from_addr,
                    message.subject,
                    message.when,
                    message.body,
                    message.genre,
                    message.txn_ref,
                    card_id,
                    message.currency,
                    html_file,
                    file_id,
                    import_id,
                    _json(raw),
                ),
            ).fetchone()
            if row["inserted"]:
                inserted += 1
            else:
                updated += 1

            email_id = row["id"]
            conn.execute("DELETE FROM email_amounts WHERE email_id = %s", (email_id,))
            conn.execute("DELETE FROM email_links WHERE email_id = %s", (email_id,))
            conn.execute("DELETE FROM email_codes WHERE email_id = %s", (email_id,))
            for ordinal, amount in enumerate(message.amounts_cents, start=1):
                conn.execute(
                    "INSERT INTO email_amounts (email_id, ordinal, amount_cents) "
                    "VALUES (%s, %s, %s)",
                    (email_id, ordinal, amount),
                )
            for url in message.links:
                conn.execute(
                    "INSERT INTO email_links (email_id, url) VALUES (%s, %s) "
                    "ON CONFLICT DO NOTHING",
                    (email_id, url),
                )
            for code in message.codes:
                conn.execute(
                    "INSERT INTO email_codes (email_id, code) VALUES (%s, %s) "
                    "ON CONFLICT DO NOTHING",
                    (email_id, code),
                )

        conn.execute(
            "UPDATE dataset_imports SET finished_at = now(), file_count = 1, "
            "row_count = %s WHERE id = %s",
            (len(records), import_id),
        )

    return {
        "import_id": import_id,
        "records": len(records),
        "parsed": len(messages),
        "inserted": inserted,
        "updated": updated,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Import YOPmail scraper JSON into Postgres")
    parser.add_argument("--input", type=Path, required=True,
                        help="Path to emails_full.json")
    parser.add_argument("--mailbox", default=None,
                        help="Stable mailbox key; defaults to the YOPmail user")
    parser.add_argument("--html-root", type=Path, default=None,
                        help="Root directory containing the scraper HTML files")
    parser.add_argument("--dsn", default=None)
    args = parser.parse_args()
    counts = import_yopmail(args.input, args.mailbox, args.html_root, args.dsn)
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
