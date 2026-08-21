#!/usr/bin/env bash
# Scrape one YOPmail inbox and import the resulting messages into Postgres.
# This file is intended to be called by system cron.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRAPER_DIR="$ROOT/scripts/yopmail_scraper"
USER_NAME="${YOPMAIL_USER:-wealifytester}"
OUTPUT_DIR="${YOPMAIL_OUTPUT_DIR:-$SCRAPER_DIR/output/$USER_NAME}"
LIMIT="${YOPMAIL_LIMIT:-0}"
DELAY="${YOPMAIL_DELAY_MS:-800}"
MAILBOX="${YOPMAIL_MAILBOX:-${USER_NAME#wealify}}"
NODE_BIN="${NODE_BIN:-$(command -v node || true)}"
NEXA_PYTHON="${NEXA_PYTHON:-$ROOT/backend/.venv/bin/python}"
LOCK_DIR="${YOPMAIL_LOCK_DIR:-$ROOT/backend/.yopmail-cron.lock}"

die() {
  printf 'yopmail cron: %s\n' "$*" >&2
  exit 1
}

[ -n "$NODE_BIN" ] && [ -x "$NODE_BIN" ] || die "node not found; set NODE_BIN"
[ -x "$NEXA_PYTHON" ] || die "Python venv not found at $NEXA_PYTHON"
[ -f "$SCRAPER_DIR/package.json" ] || die "scraper package not found at $SCRAPER_DIR"

# mkdir is portable on macOS/Linux and prevents two long Puppeteer runs from
# overlapping when a previous cron invocation is still processing CAPTCHA or
# a slow inbox.
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  printf 'yopmail cron: another run is active; skipping\n'
  exit 0
fi
cleanup() {
  rmdir "$LOCK_DIR" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

cd "$SCRAPER_DIR"
"$NODE_BIN" scrape_full.js \
  --user "$USER_NAME" \
  --output "$OUTPUT_DIR" \
  --limit "$LIMIT" \
  --delay "$DELAY" \
  --headless true \
  --require-unlocked true

cd "$ROOT/backend"
"$NEXA_PYTHON" -m data.import_yopmail \
  --input "$OUTPUT_DIR/emails_full.json" \
  --html-root "$OUTPUT_DIR" \
  --mailbox "$MAILBOX"
