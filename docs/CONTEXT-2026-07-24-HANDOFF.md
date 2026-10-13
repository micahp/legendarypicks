# CONTEXT HANDOFF — 2026-07-24: Underdog UFC props shipped (uncommitted), MLB combo chart
built (Hermes, committed not pushed), R/RBI backfill PARTIAL — resume carefully, resource-check
hook still to build

Read first on reset. Everything below happened in one session on `dev`, starting from
`bab94eb` (see `CONTEXT-2026-07-23-HANDOFF-2.md` for what came before).

## ⚑ WHAT'S DONE — uncommitted, needs a commit pass

Working tree right now (`git status` in `/root/legendarypicks`):
- `backend/bovada_scraper.py` (modified) — removed `win_by_ko`/`win_by_submission` from
  `_UFC_METHOD`, keeping only `win_by_decision`. Reason: Underdog now sources those two markets
  (see below), verified empirically that Underdog's `knockouts`/`submissions` O/U 0.5 lines price
  the same real event as Bovada's win-by-method props (implied probabilities lined up closely
  per-fighter across the whole card), so Bovada's copy was redundant. User explicitly said "just
  remove the bovada ones" after initially trying a same-market-both-sources fold — don't re-add
  Bovada's version without asking.
- `backend/ingest_mlb_logs.py` (modified) — this is MY follow-up fix on top of Hermes's commit,
  see the R/RBI backfill section below. Added `--start`/`--end` CLI args for chunked backfills
  (script previously only supported a trailing `--days N` window from "now").
- `components/Props/MarketSlateBoard.tsx` (modified) — market tabs on the props board now sort
  by prop count descending (removed the old static `MARKET_PRIORITY` list + `marketRank()`).
  User's ask: "sort them by number of props in the market... that should put significant strikes
  first." Verified live against `/api/props/slate?summary=1` — sig_strikes does lead.
- `backend/ingest_underdog_props.py` (new, untracked) — ingests UFC props from Underdog
  Fantasy's public API (`api.underdogfantasy.com/beta/v5/over_under_lines`, no auth). 5 markets:
  `significant_strikes`, `fight_time`, `finishes`, `knockouts`, `submissions`. Only the
  `line_type=='balanced'` tier (primary line, skips Underdog's alt-price-point tiers). Handles
  fighter-order mismatches between Bovada/Underdog (checks both home/away orderings before
  creating a new `prop_games` row). **Known gap, not fixed**: Bovada spells one fighter "Ramazan
  Temurov", Underdog spells him "Ramazonbek Temirov" — landed as two separate players/games since
  matching is exact-name (same convention as the rest of the codebase's WC/UFC ingest). Real
  identity-resolution gap, out of scope for this pass.

None of this is committed. **Do NOT bundle these into one commit** — per standing rule
[[feedback_separate_commits_per_slice]], this is at minimum 3 separate logical slices: (1) the
Underdog UFC ingestion + market fold, (2) the props-board sort-by-count change, (3) the
`ingest_mlb_logs.py --start/--end` chunking addition (unrelated to Underdog, born from the
backfill incident below).

## ⚑ MLB combo prop chart (`hits_runs_rbis`) — Hermes built it, COMMITTED, NOT PUSHED

Delegated to Hermes with a fully-closed spec (exact file/line refs, exact MLB Stats API JSON
paths verified by me first). Hermes committed directly to `dev` as `628f240 feat(mlb): R/RBI
backfill + hits_runs_rbis compound chart` — this is sitting on `dev`, 1 commit ahead of
`origin/dev`, not yet pushed. Verified independently (not just trusting Hermes's report): curled
`/api/props/history?market=hits_runs_rbis&league=mlb` myself, real chart data confirmed (Jeremy
Pena, H+R+RBI sums 6.0/4.0/6.0 across last 3 games, projection 3.19). Non-compound markets
regression-checked clean (same SQL path as before, zero behavior change).

**What it touches**: `backend/_core.py` (`_MARKET_STAT_KEY['mlb']['hits_runs_rbis'] = ['H','R',
'RBI']`, a LIST instead of a string — signals compound/summed stat), `backend/routers/props.py`
(`prop_history()` now handles both string and list `stat_key`, list case sums COALESCE'd
json_extract terms, requires at least one non-null per settlement.py's `found_any` convention),
`backend/ingest_mlb_logs.py` (fetches R/RBI per unique `game_pk` from the MLB Stats API boxscore,
same source `settlement.py` already uses for live settlement — Statcast's per-batter event
stream can't derive these, would need whole-game baserunner-identity tracking).

## ⚠ R/RBI backfill — PARTIAL, resume carefully, this caused tonight's incident

Hermes's commit only backfilled 7 days (2026-07-17 → 07-23, 1847 rows) — its 140-day attempt
OOM'd on this box. I added `--start`/`--end` chunking to `ingest_mlb_logs.py` and ran the missing
range (2026-03-15 → 07-16) in 7-day chunks. **Stopped after chunk 8 of 17** (through ~2026-05-09)
when the user caught real system strain (load average hit 9+, their `/props` page load broke —
tunnel dropped a request mid-load, self-recovered ~60s later) that I had NOT proactively flagged.
I also wrongly told the user the loop was killed once when it wasn't (a `pkill -f` pattern
missed, it kept running one more chunk) — caught and fixed, but it happened.

**Current coverage** (verify before resuming, don't trust this doc's numbers — they're a
snapshot): `SELECT MIN(game_date),MAX(game_date),COUNT(*) FROM player_game_logs WHERE
league='mlb' AND source='statcast' AND json_extract(stats,'$.R') IS NOT NULL` returned
2026-03-15..2026-07-23 / 17849 rows at handoff time — but the middle of that range (~2026-05-10
through 07-16, the chunks after #8 that never ran) is still gapped. Query per-week to see the
real hole, don't trust the MIN/MAX alone.

**To resume**: `cd backend && LP_DB_PATH=data/picks.dev.db python3 ingest_mlb_logs.py --start
YYYY-MM-DD --end YYYY-MM-DD` (7-day windows — a single call over the full missing range WILL
OOM, confirmed twice tonight). **This time, throttle it** — sleep between chunks, check `uptime`
before starting, and tell the user what it'll cost BEFORE running, per the new standing rule
below. Remaining chunks (7-day, from where #8 left off): roughly 2026-05-10 through 2026-07-16,
~9-10 more chunks.

## New standing rule from tonight, saved to memory

[[feedback_resource_aware_before_heavy_ops]]: check machine load (`uptime`) and proactively flag
expected CPU/memory/duration cost BEFORE running any batch job / chunked loop / bulk fetch,
especially with a live dev server running on the same box. Don't wait to be asked. Also: after
issuing a `kill`/`pkill`, VERIFY the process is actually gone before reporting it stopped — a
kill command's exit code alone isn't proof.

## ✓ RESOLVED — resource-check is a skill, not a hook

Built `/root/legendarypicks/.claude/skills/resource-check/SKILL.md` (project skill, loaded by
judgment/relevance, not mechanically enforced). User explicitly rejected BOTH hook options
(real-block and informational-injection) — no hook, full stop. See
[[feedback_resource_aware_before_heavy_ops]] for the enforcement decision. Don't revisit
building a hook for this unless the user brings it up again.

## Current live state (verified at handoff time)

- Dev backend `:8096` / frontend `:3096` healthy, tunnel
  `https://someone-decorative-wearing-produce.trycloudflare.com` live. Load average back down to
  ~1.5-3.3 after stopping the backfill loop (was 9+ during the incident).
- `dev` branch: `origin/dev..dev` shows 1 commit ahead (Hermes's `628f240`), not pushed. Plus the
  3 uncommitted slices above on top of that.
- Underdog UFC props live on the dev board right now: 170 props across 13 fights on the
  2026-07-25 card, `source='underdog'` alongside existing `source='bovada'` rows, verified via
  the actual `/api/props/slate` the frontend calls.
