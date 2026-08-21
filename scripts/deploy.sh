#!/usr/bin/env bash
# Build and run the whole stack in Docker: postgres + backend + frontend.
# Usage: ./scripts/deploy.sh [up|down|logs|rebuild]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

say() { printf '\033[36m▸ %s\033[0m\n' "$*"; }
die() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

command -v docker >/dev/null || die "docker not found"
docker info >/dev/null 2>&1 || die "docker is not running"

ACTION="${1:-up}"
[ -f .env ] || cp .env.example .env

case "$ACTION" in
  up|rebuild)
    [ "$ACTION" = "rebuild" ] && say "rebuilding images"
    say "building and starting postgres + backend + frontend"
    docker compose --profile full up -d --build
    say "waiting for the backend to answer"
    for _ in $(seq 1 60); do
      if curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then break; fi
      sleep 2
    done
    ./scripts/smoke.sh || die "smoke test failed — check: docker compose logs backend"
    printf '\033[32m✓ deployed: http://localhost:3000 (API http://localhost:8000/docs)\033[0m\n'
    ;;
  down)
    docker compose --profile full down
    ;;
  logs)
    docker compose --profile full logs -f --tail=80
    ;;
  *)
    die "unknown action: $ACTION (use up | down | logs | rebuild)"
    ;;
esac
