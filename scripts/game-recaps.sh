#!/usr/bin/env bash
# game-recaps.sh — write the recap for games that finished and never got one.
#
# The scoreboard hook (_core.kick_game_stories) already re-fires for a finished game whose
# cached story still previews it, so any game a reader looks at gets its recap for free.
# What the hook cannot do is cover a game nobody opened — and those are exactly the games
# where a stale preview sits longest before anyone notices.
#
# So this is a sweep, not the primary path. It walks back over the last two days, keeps
# only the finals, and asks for a story; generate_game_story skips anything already written
# after the final whistle, so a re-run costs nothing but the scoreboard fetches.
#
# Cost per run is bounded by finals in the window, not by the slate: one DeepSeek call each,
# once, and never again for that game.
set -uo pipefail
cd /root/legendarypicks/backend
export LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db
PY=/root/legendarypicks/backend/venv/bin/python
LOG=/var/log/legendarypicks-recaps.log

LEAGUES="${LP_RECAP_LEAGUES:-nba nhl mlb nfl mls lcup}"

log(){ printf '[%s] %s\n' "$(date -Is)" "$*" | tee -a "$LOG"; }
log "=== recap sweep start (${LEAGUES}) ==="
# shellcheck disable=SC2086
"$PY" pregenerate_game_stories.py --finals --days 2 $LEAGUES 2>&1 | tee -a "$LOG" \
  || log "  WARN: recap sweep exited non-zero"
log "=== recap sweep done ==="
