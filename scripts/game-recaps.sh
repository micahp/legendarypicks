#!/usr/bin/env bash
# game-recaps.sh — the timer sweep for game stories, in both directions.
#
# The scoreboard hook (_core.kick_game_stories) already writes a preview when a game is
# first seen and re-fires for a finished game whose cached story still previews it, so
# any game a reader looks at gets its story for free. What the hook cannot do is cover a
# game nobody opened — and those are exactly the games where a missing preview or a stale
# preview sits longest before anyone notices.
#
# So this is a sweep, not the primary path. It runs twice:
#   1. FORWARD (no --finals): previews for today's and tomorrow's games, so a game nobody
#      opened still has a preview by kickoff.
#   2. BACKWARD (--finals): walks back over the last two days, keeps only the finals, and
#      asks for a recap; generate_game_story skips anything already written after the
#      final whistle, so a re-run costs nothing but the scoreboard fetches.
#
# Leagues come from the database (league_offering.offered_leagues) via the script's
# default — not from a list here, which is exactly the kind of list that goes stale
# silently. LP_RECAP_LEAGUES remains as an explicit override for emergencies.
#
# Cost per run is bounded by games in the window, not by the slate: one DeepSeek call
# each, once, and never again for that game.
set -uo pipefail
cd /root/legendarypicks/backend
export LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db
# The sweep fetches scoreboards for up to 8 leagues x 2 days, twice (forward +
# backward overlap on today), and ESPN's limit is a COUNT per host, not a rate —
# the timer's job is to not spend the budget. A disk cache makes the second
# sweep's overlap nearly free and makes re-runs (every 3 hours) free inside the
# 12h TTL.
export LP_ESPN_CACHE_DIR=/root/legendarypicks/backend/.espn-cache
PY=/root/legendarypicks/backend/venv/bin/python
LOG=/var/log/legendarypicks-recaps.log

ARGS=()
if [ -n "${LP_RECAP_LEAGUES:-}" ]; then
  # shellcheck disable=SC2206
  ARGS=( $LP_RECAP_LEAGUES )
fi

log(){ printf '[%s] %s\n' "$(date -Is)" "$*" | tee -a "$LOG"; }
log "=== preview sweep start ==="
# shellcheck disable=SC2086
"$PY" pregenerate_game_stories.py --days 2 "${ARGS[@]}" 2>&1 | tee -a "$LOG" \
  || log "  WARN: preview sweep exited non-zero"
log "=== preview sweep done ==="
log "=== recap sweep start ==="
# shellcheck disable=SC2086
"$PY" pregenerate_game_stories.py --finals --days 2 "${ARGS[@]}" 2>&1 | tee -a "$LOG" \
  || log "  WARN: recap sweep exited non-zero"
log "=== recap sweep done ==="
