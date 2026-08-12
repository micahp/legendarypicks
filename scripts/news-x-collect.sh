#!/usr/bin/env bash
# news-x-collect.sh — the FAST lane of the news collector: X timelines only.
#
# Separate from news-collect.sh because the X accounts post far faster than the
# nightly cadence. Measured 2026-08-10: @UnderdogNFL runs ~83 posts/day against
# a 20-post RSS window, so its feed holds only about six hours and a once-daily
# run captures roughly a quarter of it. The posts that go stale fastest are the
# ones that matter most — who sat out practice, who is not travelling, who was
# just suspended.
#
# Cheap by construction: 17 HTTP requests, no ESPN, no Bluesky, no DeepSeek.
# Idempotent upserts, so overlapping windows cost nothing but a refreshed row.
# At the 2-hour cadence that is ~200 requests/day against a free Nitter mirror.
set -uo pipefail
cd /root/legendarypicks/backend
# Honour an inherited LP_DB_PATH; default to dev. Was an unconditional export
# that silently overrode its own unit's Environment= — the same bug as
# news-collect.sh, and the reason a prod news job could not have worked even if
# somebody had written one.
export LP_DB_PATH="${LP_DB_PATH:-/root/legendarypicks/backend/data/picks.dev.db}"
PY=/root/legendarypicks/backend/venv/bin/python
LOG="${LP_NEWS_LOG:-/var/log/legendarypicks-news.log}"

log(){ printf '[%s] %s\n' "$(date -Is)" "$*" | tee -a "$LOG"; }
log "=== x collect start ==="
"$PY" ingest_league_news.py --x-only 2>&1 | tee -a "$LOG" || log "  WARN: x collect exited non-zero"
log "=== x collect done ==="
