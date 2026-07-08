#!/usr/bin/env bash
# Keep the live-discounts widget alive without a browser: hitting the endpoint is what
# writes price snapshots, sets Class C pregame levels, and fires receipts.
set -u
URL="http://localhost:8095/api/live/discounts?league=mlb,wc"
LOG="/root/legendarypicks/logs/live-discounts-poll.log"

resp=$(curl -s --max-time 55 "$URL") || { echo "$(date -u +%FT%TZ) curl-fail" >> "$LOG"; exit 0; }
echo "$resp" | jq -c '{t: .generated_at, cards: (.cards | length),
  fired: [.cards[].class], degraded: .degraded}' >> "$LOG" 2>>"$LOG"
