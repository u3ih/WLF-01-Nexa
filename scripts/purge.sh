#!/usr/bin/env bash
# Contest rule 9: remove the sample data, the mail outbox, the logs and all
# stored state (flag journal, fingerprints, reminders, drafts).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

say() { printf '\033[36m▸ %s\033[0m\n' "$*"; }

if [ "${1:-}" != "--yes" ]; then
  printf 'This deletes sample data, the outbox, logs and all database state.\n'
  read -r -p 'Type "purge" to continue: ' answer
  [ "$answer" = "purge" ] || { echo "aborted"; exit 1; }
fi

say "database state"
if command -v docker >/dev/null && docker compose ps postgres --status running -q 2>/dev/null | grep -q .; then
  docker compose exec -T postgres psql -U nexa -d nexa -c \
    'TRUNCATE reminders, audit_log, flags, report_drafts, scans RESTART IDENTITY CASCADE;' \
    >/dev/null 2>&1 && say "tables truncated" || say "tables not present"
else
  say "postgres not running — skipping table truncation"
fi

say "files"
rm -rf backend/data/sample backend/outbox backend/logs
find . -name '*.log' -not -path './node_modules/*' -not -path './frontend/.next/*' -delete 2>/dev/null || true

if [ "${2:-}" = "--drop-volume" ] || [ "${1:-}" = "--drop-volume" ]; then
  say "dropping the postgres volume"
  docker compose down -v >/dev/null 2>&1 || true
fi

printf '\033[32m✓ purged. Regenerate with: make seed\033[0m\n'
