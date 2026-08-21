"""Postgres-backed application state.

Only four things are persisted, and none of them is money: the flag journal,
the fingerprints used to avoid repeating an alert, deadline reminders, and
report drafts awaiting the user's confirmation.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id              BIGSERIAL PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    trigger         TEXT NOT NULL DEFAULT 'manual',
    new_count       INTEGER NOT NULL DEFAULT 0,
    suppressed_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS flags (
    fingerprint     TEXT PRIMARY KEY,
    kind            TEXT NOT NULL,
    label           TEXT NOT NULL,
    confidence      NUMERIC(4,2) NOT NULL,
    amount_cents    BIGINT NOT NULL DEFAULT 0,
    txn_ids         JSONB NOT NULL DEFAULT '[]'::jsonb,
    period_key      TEXT NOT NULL DEFAULT '',
    occurred_on     DATE,
    statement_date  DATE,
    dispute_deadline DATE,
    params          JSONB NOT NULL DEFAULT '{}'::jsonb,
    sources         JSONB NOT NULL DEFAULT '[]'::jsonb,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    seen_count      INTEGER NOT NULL DEFAULT 1,
    first_scan_id   BIGINT REFERENCES scans(id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id              BIGSERIAL PRIMARY KEY,
    logged_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    event           TEXT NOT NULL,
    fingerprint     TEXT,
    kind            TEXT,
    label           TEXT,
    confidence      NUMERIC(4,2),
    reason          TEXT NOT NULL DEFAULT '',
    detail          JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS reminders (
    id              BIGSERIAL PRIMARY KEY,
    fingerprint     TEXT NOT NULL REFERENCES flags(fingerprint) ON DELETE CASCADE,
    due_date        DATE NOT NULL,
    kind            TEXT NOT NULL,
    title           TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'open',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (fingerprint, due_date)
);

CREATE TABLE IF NOT EXISTS report_drafts (
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    recipient       TEXT NOT NULL,
    subject         TEXT NOT NULL,
    body            TEXT NOT NULL,
    period_key      TEXT NOT NULL DEFAULT '',
    lang            TEXT NOT NULL DEFAULT 'vi',
    confirm_token   TEXT NOT NULL UNIQUE,
    status          TEXT NOT NULL DEFAULT 'draft',
    confirmed_at    TIMESTAMPTZ,
    sent_at         TIMESTAMPTZ,
    delivery        TEXT NOT NULL DEFAULT 'outbox',
    file_path       TEXT
);

CREATE INDEX IF NOT EXISTS flags_kind_idx ON flags (kind);
CREATE INDEX IF NOT EXISTS audit_log_fingerprint_idx ON audit_log (fingerprint);
CREATE INDEX IF NOT EXISTS reminders_due_idx ON reminders (due_date, status);
"""


class Store:
    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or settings.database_url
        self._pool: ConnectionPool | None = None
        self._ready = False
        self.last_error: str | None = None

    # -- connection -------------------------------------------------------

    @property
    def pool(self) -> ConnectionPool:
        if self._pool is None:
            self._pool = ConnectionPool(
                self.dsn, min_size=1, max_size=5, open=False,
                kwargs={"row_factory": dict_row},
            )
            self._pool.open()
        return self._pool

    @contextmanager
    def conn(self) -> Iterator[psycopg.Connection]:
        with self.pool.connection() as connection:
            yield connection

    def init_schema(self) -> bool:
        try:
            with self.conn() as c:
                c.execute(SCHEMA)
            self._ready = True
            self.last_error = None
        except Exception as exc:                       # noqa: BLE001
            self._ready = False
            self.last_error = f"{type(exc).__name__}: {exc}"
        return self._ready

    def health(self) -> dict[str, Any]:
        try:
            with self.conn() as c:
                row = c.execute("SELECT current_database() AS db,"
                                " version() AS version").fetchone()
            counts = self.counts()
            return {"connected": True, "database": row["db"],
                    "server": row["version"].split(",")[0], **counts}
        except Exception as exc:                       # noqa: BLE001
            return {"connected": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "hint": "start Postgres with: docker compose up -d postgres"}

    def counts(self) -> dict[str, int]:
        with self.conn() as c:
            return {
                "flags": c.execute("SELECT count(*) AS n FROM flags")
                .fetchone()["n"],
                "audit_entries": c.execute("SELECT count(*) AS n FROM audit_log")
                .fetchone()["n"],
                "reminders": c.execute("SELECT count(*) AS n FROM reminders")
                .fetchone()["n"],
                "scans": c.execute("SELECT count(*) AS n FROM scans").fetchone()["n"],
            }

    # -- scans ------------------------------------------------------------

    def start_scan(self, trigger: str = "manual") -> int:
        with self.conn() as c:
            return c.execute(
                "INSERT INTO scans (trigger) VALUES (%s) RETURNING id", (trigger,)
            ).fetchone()["id"]

    def finish_scan(self, scan_id: int, new_count: int, suppressed: int) -> None:
        with self.conn() as c:
            c.execute(
                "UPDATE scans SET finished_at = now(), new_count = %s,"
                " suppressed_count = %s WHERE id = %s",
                (new_count, suppressed, scan_id),
            )

    def scan_history(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.conn() as c:
            return c.execute(
                "SELECT id, started_at, finished_at, trigger, new_count,"
                " suppressed_count FROM scans ORDER BY id DESC LIMIT %s",
                (limit,),
            ).fetchall()

    # -- flags ------------------------------------------------------------

    def upsert_flag(self, payload: dict[str, Any], scan_id: int | None = None
                    ) -> bool:
        """Insert a flag, or bump its last-seen stamp if we have seen it before.

        Returns True only for a genuinely new flag — that is what keeps a
        recurring scan from reporting the same item twice.
        """
        with self.conn() as c:
            row = c.execute(
                """
                INSERT INTO flags (fingerprint, kind, label, confidence,
                    amount_cents, txn_ids, period_key, occurred_on,
                    statement_date, dispute_deadline, params, sources,
                    first_scan_id)
                VALUES (%(fingerprint)s, %(kind)s, %(label)s, %(confidence)s,
                    %(amount_cents)s, %(txn_ids)s, %(period_key)s,
                    %(occurred_on)s, %(statement_date)s, %(dispute_deadline)s,
                    %(params)s, %(sources)s, %(scan_id)s)
                ON CONFLICT (fingerprint) DO UPDATE
                    SET last_seen_at = now(),
                        seen_count = flags.seen_count + 1
                RETURNING (xmax = 0) AS inserted
                """,
                {**payload, "scan_id": scan_id},
            ).fetchone()
        return bool(row["inserted"])

    def flags(self, limit: int = 500) -> list[dict[str, Any]]:
        with self.conn() as c:
            return c.execute(
                "SELECT * FROM flags ORDER BY first_seen_at DESC LIMIT %s",
                (limit,),
            ).fetchall()

    def known_fingerprints(self) -> set[str]:
        with self.conn() as c:
            rows = c.execute("SELECT fingerprint FROM flags").fetchall()
        return {r["fingerprint"] for r in rows}

    # -- audit journal ----------------------------------------------------

    def log(self, event: str, *, fingerprint: str | None = None,
            kind: str | None = None, label: str | None = None,
            confidence: float | None = None, reason: str = "",
            detail: dict[str, Any] | None = None) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO audit_log (event, fingerprint, kind, label,"
                " confidence, reason, detail)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (event, fingerprint, kind, label, confidence, reason,
                 json.dumps(detail or {}, default=str)),
            )

    def audit_entries(self, limit: int = 1000) -> list[dict[str, Any]]:
        with self.conn() as c:
            return c.execute(
                "SELECT id, logged_at, event, fingerprint, kind, label,"
                " confidence, reason, detail FROM audit_log"
                " ORDER BY id DESC LIMIT %s",
                (limit,),
            ).fetchall()

    # -- reminders --------------------------------------------------------

    def add_reminder(self, fingerprint: str, due: date, kind: str,
                     title: str) -> bool:
        with self.conn() as c:
            row = c.execute(
                "INSERT INTO reminders (fingerprint, due_date, kind, title)"
                " VALUES (%s, %s, %s, %s)"
                " ON CONFLICT (fingerprint, due_date) DO NOTHING"
                " RETURNING id",
                (fingerprint, due, kind, title),
            ).fetchone()
        return row is not None

    def reminders(self, include_closed: bool = False) -> list[dict[str, Any]]:
        sql = ("SELECT r.*, f.kind AS flag_kind, f.amount_cents FROM reminders r"
               " JOIN flags f ON f.fingerprint = r.fingerprint")
        if not include_closed:
            sql += " WHERE r.status = 'open'"
        sql += " ORDER BY r.due_date ASC"
        with self.conn() as c:
            return c.execute(sql).fetchall()

    # -- report drafts ----------------------------------------------------

    def create_draft(self, recipient: str, subject: str, body: str,
                     period_key: str, lang: str, token: str,
                     delivery: str) -> int:
        with self.conn() as c:
            return c.execute(
                "INSERT INTO report_drafts (recipient, subject, body,"
                " period_key, lang, confirm_token, delivery)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (recipient, subject, body, period_key, lang, token, delivery),
            ).fetchone()["id"]

    def draft_by_token(self, token: str) -> dict[str, Any] | None:
        with self.conn() as c:
            return c.execute(
                "SELECT * FROM report_drafts WHERE confirm_token = %s", (token,)
            ).fetchone()

    def mark_draft_sent(self, draft_id: int, file_path: str | None) -> None:
        with self.conn() as c:
            c.execute(
                "UPDATE report_drafts SET status = 'sent', confirmed_at = now(),"
                " sent_at = now(), file_path = %s WHERE id = %s",
                (file_path, draft_id),
            )

    # -- housekeeping -----------------------------------------------------

    def purge(self) -> dict[str, int]:
        """Wipe all stored state (contest rule 9: delete sample data and logs)."""
        with self.conn() as c:
            before = self.counts()
            c.execute("TRUNCATE reminders, audit_log, flags, report_drafts,"
                      " scans RESTART IDENTITY CASCADE")
        return before


store = Store()
