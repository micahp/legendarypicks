# CONTEXT HANDOFF — 2026-07-23: NFL Player Rankings shipped, v0.6.0 tagged+pushed

Read first on reset. Supersedes the 2026-07-21 handoff for live NFL/legendarypicks state.

## ⚑ WHAT SHIPPED THIS SESSION (all on `dev`, pushed, tagged `v0.6.0` @ `2435190`)

1. **Bug fix (unrelated to NFL, found first)**: `backend/routers/live_discounts.py` — doubleheader
   ticker mismatch. A live game's Kalshi price was matched to a SETTLED market from the day's
   other game (same team pair, different Kalshi ticker date since postponed/rescheduled games
   keep their original ticker date). Fixed by widening the date-token search to the prior ET day
   and excluding finalized markets unless the ESPN game itself is over. Commit `213c1d4`.

2. **`feat/nfl-camp-mode` branch closed out and merged to `dev`** (`35104ae`) — this was the
   big one. Draft Room → **Player Rankings**:
   - **Real ADP** (`backend/ingest_nfl_adp.py`): ESPN's own fantasy API (free, unauthenticated,
     `lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026/players`), joined on the
     existing `players.espn_id` spine — no fuzzy matching needed, ids match exactly. FantasyPros
     was ruled out (their ADP data loads from `/ajax/`/`/api/` paths their own robots.txt
     disallows). New `nfl_adp` table, 9,611 rows / 2,510 with real ADP.
   - **Season-projected fantasy points**: `analytics/projections.py`'s `project_stat()` on the
     `fpts_ppr` per-game series × `games_assumed` (capped 17). **Real bug found+fixed twice**:
     (1) 2024 ingest uses legacy key `fantasy_points_ppr`, 2025 pbp ingest uses canonical
     `fpts_ppr` — code only checked the legacy key, so every player's projection was silently
     built from 2024 data only (2025 invisible). (2) query ordered by game_date/game_no but
     never `season`, and game_date is blank for all NFL rows — 2024/2025 games interleaved by
     game_no alone, corrupting recency ordering. Both fixed, re-verified against real players
     (McCaffrey: was 47.8pts/4 games from stale 2024 data → 371.3pts/17 games, matches his real
     24.4 PPR/G).
   - **ADP + Season Proj are now always-visible columns** (not sort-gated — that was the exact
     mistake just fixed for ADP, don't repeat it), lead the sort row, ADP is the default sort
     (was `fantasy_ppr_g`, a rear-view stat).
   - Renamed "Draft Room" → "Player Rankings", dropped the card wrapper (plain section title —
     "Draft Room" implied live/interactive draft tooling that doesn't exist; this is a ranked
     cheat-sheet).
   - **Recent Trades** replaced the old unfiltered "Offseason Movers" transaction feed. Splits
     bundled multi-sentence transactions into one-trade-per-line, dedupes mirror entries (ESPN
     logs one row per team in a deal) by the SET OF PLAYER NAMES mentioned (reliable — team names
     in free text are often ambiguous, e.g. "Los Angeles" alone doesn't disambiguate Rams vs
     Chargers), and picks "the from team" side using real ADP as a significance proxy on whichever
     player is named before " for " in that entry's own sentence (not just the first name — that
     breaks when a team's side of the deal is picks-only, e.g. Denver's side of the Waddle trade
     names Waddle as what they RECEIVED, not gave up). Player names bolded.
   - Training Camp countdown card iterated several times (scoreboard-tile redesign: milestone
     name / countdown on the left, month+day date tile on the right) — see commit history
     `02c2802`→`dd1a27b` for the back-and-forth; final state is what's live now.
   - Delegated to Hermes (3 tasks, isolated worktrees off `dev`): NFL projections key-fix,
     ADP ingest, season-projection column. All reviewed, one real bug caught in ADP task's
     dedup approach before merge (scope creep pulling in unrelated `feat/nfl-camp-mode` files
     for browser validation — caught before commit, redirected to curl-only validation), one
     real data bug caught in season-proj task AFTER merge (the stale-2024-data bug above — found
     by actually reading the rendered numbers, not trusting Hermes's own "10 players, all PASS"
     self-report, which only checked plausibility, not which season the data came from).

3. **v0.6.0 tagged and pushed** (`git tag -f v0.6.0 2435190`, force-pushed since the changelog
   was expanded after the first tag/push — moving an already-pushed tag, noted explicitly before
   doing it). Changelog covers everything between v0.5.10 and v0.6.0, not just tonight's NFL work
   (also: MLB EV/CLV fix that had landed earlier, esports card-hide + Make Picks button, schedule
   nav spinner cleanup, em-dash copy cleanup).

4. **Worktree cleanup**: tore down `lp-mlb-ev-clv`, `lp-nfl-adp`, `lp-projections-nfl` (all fully
   merged into `dev`, no unique uncommitted work) via `scripts/hermes-worktree.sh down <task>`.
   Their branches (`feat/mlb-ev-clv`, `feat/nfl-adp`, `feat/projections-nfl`) still exist locally,
   harmless. **Left `lp-prop-repair` and `lp-wc-props` alone** — unrelated to this session, status
   unknown, didn't touch.

## ⚠ REAL INCIDENT THIS SESSION: box OOM'd, not job-related

Running 3-4 parallel `next dev`+`uvicorn` worktree stacks simultaneously (this box has only
5.8GB RAM) exhausted `fs.inotify.max_user_watches` (raised 8192→524288 via `sysctl -w`, runtime
only, resets on reboot — bump again if `ENOSPC: System limit for number of file watchers
reached` recurs) and pushed the box into heavy swapping, which OOM-killed the **Hermes process
itself** mid-session (not a work failure — its in-flight task's commit had already landed safely
before the kill). Micah restarted Hermes himself. Full writeup + a proper runbook:
`legendarypicks/docs/RUNBOOK-parallel-dev-servers-and-hmr.md` and memory
[[reference_parallel_worktree_dev_servers]]. **Key operational lesson: tear down a worktree's
dev-server pair the moment its task is merged — don't leave idle `next dev`/`uvicorn` running
"just in case."** Also: `scripts/hermes-worktree.sh up` hardcodes ports 8096/3096 (same as the
main dev env) — always check `ss -ltnp` for free ports before assuming the script's printed
ports are actually free.

## Current live state (verified at handoff time)

- Main dev backend `:8096` / frontend `:3096` (cloudflared tunnel) — healthy, on `dev` @ `2435190`.
- `dev` pushed to `origin/dev`, tag `v0.6.0` pushed and force-updated to match.
- Hermes tmux pane (`hermes:0.0`) — idle, restarted fresh by Micah after the OOM, ready for new
  dispatch (fresh session, no memory of tonight's tasks — brief it fully if resuming any thread).

## NEXT UP (explicitly deferred, not started)

Per Micah's own sequencing tonight: **season-long ADP/projections shipped first (done, this
session) → weekly rankings per position + post-game weekly performance tracking (ESPN-style) is
next**, explicitly deferred until now. This is the natural continuation of the sit-start/waiver
moat-adjacency framework in `docs/SPEC-nfl-product-direction.md` — season-long Player Rankings
answers "who do I draft," weekly is "who do I start this week" / "what does my guy do after the
whistle." Needs: a weekly (not season-aggregate) projection view, and real post-game box-score
ingestion on some cadence (currently game logs are ingested manually/ad hoc, not on a cron —
same gap flagged in the props-loop DB audit from `docs/SPEC-prop-loop-mlb.md`, likely the same
fix applies to NFL game logs).

## Feedback/pattern notes from tonight worth remembering

- User got frustrated when I spun up a full worktree+dedicated-servers for a task small enough
  to just do directly in the main tree — **match delegation overhead to the actual size of the
  task**, don't reflexively worktree everything. See [[feedback_delegate_means_hermes]] — that's
  for genuinely separable feature work, not a 3-line UI tweak.
- Iterating on a small visual design element (the Training Camp card) by guessing at aesthetic
  fixes without concrete direction burned several round-trips before landing — when a design
  critique is vague ("idk", "it's like AI"), it's worth checking established site patterns
  (grep for the same Tailwind classes elsewhere) before assuming something is generic/wrong, and
  reverting to a known-good state rather than continuing to guess after 2 misses in a row.
