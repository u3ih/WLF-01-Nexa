#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/backend"

NEXA_PYTHON="${NEXA_PYTHON:-.venv/bin/python}"
exec "$NEXA_PYTHON" -m app.db.migrations "$@"
