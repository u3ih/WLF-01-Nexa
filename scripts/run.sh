#!/usr/bin/env bash
# Start backend and frontend together. Ctrl-C stops both.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODE="${1:-dev}"            # dev | prod
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

say() { printf '\033[36m▸ %s\033[0m\n' "$*"; }

[ -d backend/.venv ] || { say "no virtualenv yet — running setup"; ./scripts/setup.sh; }
[ -f backend/data/sample/ground_truth.json ] || \
  (cd backend && .venv/bin/python -m data.generate)

if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
  docker compose up -d postgres >/dev/null 2>&1 || true
fi

# Only worth starting when the configured endpoint IS a local Ollama. A hosted
# OpenAI-compatible URL needs nothing started here.
AI_URL="$(grep -E '^NEXA_AI_URL=' .env 2>/dev/null | tail -1 | cut -d= -f2-)"
case "${AI_URL:-http://localhost:11434}" in
  *localhost:11434*|*127.0.0.1:11434*|*host.docker.internal:11434*)
    if command -v ollama >/dev/null && ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
      say "starting ollama serve in the background"
      (ollama serve >/dev/null 2>&1 &)
      sleep 2
    fi
    ;;
esac

pids=()
cleanup() {
  say "stopping"
  for pid in "${pids[@]:-}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

say "backend  → http://localhost:${BACKEND_PORT}  (docs at /docs)"
if [ "$MODE" = "prod" ]; then
  (cd backend && .venv/bin/python -m uvicorn app.main:app \
     --host 0.0.0.0 --port "$BACKEND_PORT") &
else
  (cd backend && .venv/bin/python -m uvicorn app.main:app \
     --host 127.0.0.1 --port "$BACKEND_PORT" --reload) &
fi
pids+=($!)

say "frontend → http://localhost:${FRONTEND_PORT}"
if [ "$MODE" = "prod" ]; then
  (cd frontend && npm run build >/dev/null && \
    BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}" npm run start) &
else
  (cd frontend && BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}" npm run dev) &
fi
pids+=($!)

printf '\033[32m✓ open http://localhost:%s\033[0m\n' "$FRONTEND_PORT"
wait
