#!/usr/bin/env bash
# Install everything Nexa needs. Idempotent: safe to re-run.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

say() { printf '\033[36m▸ %s\033[0m\n' "$*"; }
warn() { printf '\033[33m! %s\033[0m\n' "$*"; }
die() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

command -v python3 >/dev/null || die "python3 not found (need 3.10+)"
command -v node >/dev/null || die "node not found (need 18+)"

PY_OK=$(python3 -c 'import sys; print(1 if sys.version_info >= (3,10) else 0)')
[ "$PY_OK" = "1" ] || die "python3 is too old; need 3.10+"

if [ ! -f .env ]; then
  cp .env.example .env
  say "created .env from .env.example"
fi

say "backend: virtualenv + dependencies"
[ -d backend/.venv ] || python3 -m venv backend/.venv
backend/.venv/bin/pip install -q --upgrade pip
backend/.venv/bin/pip install -q -r backend/requirements.txt

say "postgres"
POSTGRES_READY=0
if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
  docker compose up -d postgres >/dev/null
  for _ in $(seq 1 40); do
    # Probe the default `postgres` database first: `nexa` may be the database
    # we still need to create in an older volume.
    if docker compose exec -T postgres pg_isready -U nexa -d postgres >/dev/null 2>&1; then
      POSTGRES_READY=1
      say "postgres ready on localhost:55432"
      break
    fi
    sleep 1
  done
  if [ "$POSTGRES_READY" = "1" ]; then
    # POSTGRES_DB is only applied when the Postgres volume is initialized for
    # the first time. Older volumes may contain the `nexa` role but not the
    # application database, so reconcile that state explicitly.
    DB_EXISTS=$(docker compose exec -T postgres psql -U nexa -d postgres \
      -tAc "SELECT 1 FROM pg_database WHERE datname = 'nexa'" \
      | tr -d '[:space:]')
    if [ "$DB_EXISTS" != "1" ]; then
      say "creating database nexa in the existing Postgres volume"
      docker compose exec -T postgres createdb -U nexa nexa
    fi

    say "database migrations"
    ./scripts/migrate.sh
  else
    warn "Postgres did not become ready — database setup skipped"
  fi
else
  warn "docker is not running — start Postgres yourself and set NEXA_DATABASE_URL"
fi

say "sample data"
if [ ! -f backend/data/sample/ground_truth.json ]; then
  (cd backend && .venv/bin/python -m data.generate)
else
  say "sample data already present (make seed to regenerate)"
fi

if [ "$POSTGRES_READY" = "1" ]; then
  say "dataset import"
  ./scripts/import_dataset.sh
fi

say "frontend: npm install"
(cd frontend && npm install --no-audit --no-fund --loglevel=error)

say "ollama (optional)"
if command -v ollama >/dev/null; then
  if curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
    say "ollama is running: $(curl -sf http://localhost:11434/api/tags \
      | python3 -c 'import json,sys; print(", ".join(m["model"] for m in json.load(sys.stdin)["models"]))' 2>/dev/null || echo '?')"
  else
    warn "ollama installed but not running — 'ollama serve' enables model answers"
  fi
else
  warn "ollama not installed — the assistant will answer from the engine only"
fi

printf '\033[32m✓ setup complete. Start with: make dev\033[0m\n'
