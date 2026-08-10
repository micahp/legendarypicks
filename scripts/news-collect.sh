#!/usr/bin/env bash
# news-collect.sh — the daily league-news collector+cron (freshness policy = 1
# day, Micah 2026-08-09). Runs the two ingest scripts in order against the
# managed dev DB (news is dev-only; NOT promoted to prod yet):
#
#   1. ingest_league_news.py        collect+classify into news_items
#                                  (ESPN 7 req/host-budget-20 disk-cached 1h,
#                                   RSS, Bluesky)
#   2. ingest_league_narratives.py  conversation cards (1 DeepSeek batch call)
#
# (A league-summary "state of the league" pass was built then reverted
# 2026-08-09 — redundant with the per-conversation cards, which each carry
# their own anchor + fan voice. Each conversation gets to breathe; we do not
# roll them up. See PLAN-league-news-engine.md §9.1.)
#
# Each step is logged; a step failing does NOT abort the next — a transient
# ESPN 403 (the per-host wall, espn-request-budget doctrine) must not block the
# DeepSeek narrative refresh, which reads the stored news_items regardless.
# Idempotent upserts mean a re-run inside the cache TTL costs zero ESPN requests.
set -uo pipefail
cd /root/legendarypicks/backend
export LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db
PY=/root/legendarypicks/backend/venv/bin/python
LOG=/var/log/legendarypicks-news.log

log(){ printf '[%s] %s\n' "$(date -Is)" "$*" | tee -a "$LOG"; }

log "=== news collect start ==="
"$PY" ingest_league_news.py        2>&1 | tee -a "$LOG" || log "  WARN: collector exited non-zero"
"$PY" ingest_league_narratives.py  2>&1 | tee -a "$LOG" || log "  WARN: narratives exited non-zero"
log "=== news collect done ==="
