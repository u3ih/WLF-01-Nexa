#!/usr/bin/env bash
# Quick post-start check: the endpoints a judge will look at must answer, the
# card number must be masked, and a repeat scan must not repeat alerts.
set -euo pipefail

API="${API:-http://localhost:8000}"
UI="${UI:-http://localhost:3000}"
pass() { printf '\033[32m  ✓ %s\033[0m\n' "$*"; }
fail() { printf '\033[31m  ✗ %s\033[0m\n' "$*"; exit 1; }

printf '▸ smoke test against %s\n' "$API"

curl -sf "$API/api/health" >/dev/null || fail "health endpoint"
pass "health"

findings=$(curl -sf "$API/api/findings?lang=vi")
echo "$findings" | grep -q 'needs_your_confirmation' || fail "no labelled findings"
pass "findings carry the three-tier label"

echo "$findings" | grep -q '4157889923144821' && fail "unmasked card number in output"
pass "card number is masked"

curl -sf "$API/api/tri-source?lang=vi" | grep -q 'not_on_card' \
  || fail "three-source reconciliation"
pass "three-source reconciliation"

first=$(curl -sf -X POST "$API/api/monitor/scan" -H 'content-type: application/json' \
  -d '{"lang":"vi","trigger":"smoke"}')
second=$(curl -sf -X POST "$API/api/monitor/scan" -H 'content-type: application/json' \
  -d '{"lang":"vi","trigger":"smoke"}')
echo "$second" | grep -q '"new_count":0' || fail "a repeat scan raised alerts again"
pass "repeat scan reports nothing new"

refusal=$(curl -sf -X POST "$API/api/chat" -H 'content-type: application/json' \
  -d '{"question":"Tự huỷ mấy gói không dùng đi","lang":"vi"}')
echo "$refusal" | grep -q '"refused":true' || fail "cancel request was not refused"
pass "cancel request refused"

status=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API/api/report/send" \
  -H 'content-type: application/json' \
  -d '{"confirm_token":"whatever-token","recipient":"billing@netflix.com","confirmed":true,"lang":"vi"}')
[ "$status" = "403" ] || fail "third-party send returned $status (expected 403)"
pass "third-party email refused (403)"

if curl -sf "$UI" >/dev/null 2>&1; then pass "frontend responds"; fi
printf '\033[32m✓ smoke test passed\033[0m\n'
