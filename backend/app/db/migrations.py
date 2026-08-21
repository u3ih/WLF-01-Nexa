"""Small, dependency-free migration runner for the Nexa Postgres database."""

from __future__ import annotations

import argparse
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from ..config import settings

_MIGRATION_LOCATIONS = (
    Path(__file__).resolve().parents[3] / "migrations",  # repository layout
    Path(__file__).resolve().parents[2] / "migrations",  # Docker image layout
)
MIGRATIONS_DIR = next(
    (path for path in _MIGRATION_LOCATIONS if path.is_dir()),
    _MIGRATION_LOCATIONS[0],
)


def apply_migrations(dsn: str | None = None) -> list[str]:
    """Apply every not-yet-applied SQL migration in lexical order."""
    applied: list[str] = []
    with psycopg.connect(dsn or settings.database_url, row_factory=dict_row) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        existing = {
            row["version"]
            for row in conn.execute(
                "SELECT version FROM schema_migrations"
            ).fetchall()
        }
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in existing:
                continue
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s)",
                (path.name,),
            )
            applied.append(path.name)
    return applied


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply Nexa database migrations")
    parser.add_argument("--dsn", default=None, help="Postgres DSN; defaults to NEXA_DATABASE_URL")
    args = parser.parse_args()
    applied = apply_migrations(args.dsn)
    print("Applied: " + ", ".join(applied) if applied else "Database is up to date")


if __name__ == "__main__":
    main()
