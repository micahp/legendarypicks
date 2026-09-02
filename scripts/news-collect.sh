#!/usr/bin/env bash
# news-collect.sh — the daily league-news collector+cron (freshness policy = 1
# day, Micah 2026-08-09). Runs the two ingest scripts in order against the
# managed dev DB (news is dev-only; NOT promoted to prod yet):
#
#   1. ingest_league_news.py        collect+classify into news_items
#                                  (ESPN 7 req/host-budget-20 disk-cached 1h,
#                                   RSS, Bluesky)
#   2. -m ingest_league_narratives  conversation cards (1 DeepSeek batch call)
#   3. discover_topics.py           propose NEW conversations from the corpus
#                                  (review with --list; nothing auto-publishes)
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
#
# Every step is time-budgeted, and that is the point: a step that HANGS never
# fails, so "a step failing does not abort the next" was never actually true.
# See news-lib.sh for the 2026-08-17 failure and the measurements behind it.
set -uo pipefail
cd /root/legendarypicks/backend
# Honour an inherited LP_DB_PATH; default to dev when nothing asked for one.
#
# This used to be an unconditional `export ...picks.dev.db`, which silently
# overrode the value its own systemd unit set. A production unit written the
# obvious way — Environment=LP_DB_PATH=.../picks.db — would have run against dev
# and reported success, which is why prod carried 0 news_items in every one of
# its six news tables while dev held 4,058.
export LP_DB_PATH="${LP_DB_PATH:-/root/legendarypicks/backend/data/picks.dev.db}"
PY=/root/legendarypicks/backend/venv/bin/python
LOG="${LP_NEWS_LOG:-/var/log/legendarypicks-news.log}"

. /root/legendarypicks/scripts/news-lib.sh   # log(), run_step()

# Say which database this run writes to, every run. A job that does not name its
# target cannot be audited afterwards, and this one was writing to a different
# database than its operator believed for as long as it has existed.
log "=== news collect start === DB=$LP_DB_PATH"
[ -f "$LP_DB_PATH" ] || { log "FATAL: $LP_DB_PATH does not exist"; exit 2; }
# Budgets are the healthy runtime with room, not a guess: measured 2026-08-17 on
# this box, the collector completes in ~4 min (ESPN+RSS in under one, the rest
# being Bluesky's 100 requests at min_interval=1.5). Discovery got 300 -> 420
# when its model ceiling rose to 24000: observed 168s, and reasoning time
# scales with that ceiling. They must sum to less than
# the unit's TimeoutStartSec (1800) or systemd kills the job before the last
# step can report — which is the failure this whole change exists to prevent.
run_step 600 ingest_league_news.py
run_step 420 -m ingest_league_narratives
# 3. Discovery: propose conversations nobody named. Nothing is published from
#    this — it writes candidates for review (discover_topics.py --list).
run_step 420 discover_topics.py
log "=== news collect done === DB=$LP_DB_PATH"
finish
