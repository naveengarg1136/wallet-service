#!/usr/bin/env bash
# Minimal bash + curl burst (mirrors the rubric's xargs -P style). For the full
# PASS/FAIL harness incl. reversal use scripts/burst.py.
#
#   ./scripts/burst.sh http://localhost:8000
set -euo pipefail
BASE="${1:-http://localhost:8000}"
USER="user-$(date +%s)-$RANDOM"

echo "== Gate 1: 50 concurrent POST /wallets for a fresh user =="
seq 50 | xargs -P50 -I{} curl -s -X POST "$BASE/wallets" \
  -H "Authorization: Bearer $USER" | \
  python3 -c "import sys,json; ids={json.loads(l)['id'] for l in sys.stdin if l.strip()}; print('distinct wallets:', len(ids)); sys.exit(0 if len(ids)==1 else 1)"

echo "== Seed A, then 30 concurrent identical transfers (same idempotency key) =="
A=$(curl -s -X POST "$BASE/wallets" -H "Authorization: Bearer $USER-A" | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
B=$(curl -s -X POST "$BASE/wallets" -H "Authorization: Bearer $USER-B" | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -s -X POST "$BASE/wallets/$A/deposit" -H "Authorization: Bearer $USER-A" \
  -H 'Content-Type: application/json' -d "{\"amount_paise\":100000,\"idempotency_key\":\"seed-$RANDOM\"}" >/dev/null
KEY="idem-$RANDOM"
seq 30 | xargs -P30 -I{} curl -s -X POST "$BASE/transfers" -H "Authorization: Bearer $USER-A" \
  -H 'Content-Type: application/json' \
  -d "{\"from\":\"$A\",\"to\":\"$B\",\"amount_paise\":500,\"idempotency_key\":\"$KEY\"}" >/dev/null
echo "A balance: $(curl -s "$BASE/wallets/$A" -H "Authorization: Bearer $USER-A" | python3 -c "import sys,json;print(json.load(sys.stdin)['balance_paise'])") (expect 99500)"
echo "B balance: $(curl -s "$BASE/wallets/$B" -H "Authorization: Bearer $USER-B" | python3 -c "import sys,json;print(json.load(sys.stdin)['balance_paise'])") (expect 500)"
