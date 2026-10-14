# HANDOFF: tennis data, Kalshi poller, US Open points (2026-10-13)

Written at the end of a long session so a fresh one can continue safely. Read this first, then
`docs/CONTEXT-2026-10-13.md` (section "Later on 2026-10-13: tennis data") and
`docs/TENNIS-DATA-2026-10-13.md`.

Nothing here is pushed. Nothing has been written to prod (`picks.db`).

## 0. NEXT: finish the Kalshi tennis points bridge (decided 2026-10-14, approved by Micah)

This section replaces the architecture in `docs/PLAN-tennis-points-scoreboard-2026-10-13.md`
where they disagree. Micah approved both changes below on 2026-10-14 around 01:00 UTC.

### What changed from the plan, and why
1. **No copy job into the dev DB.** The API reads `KALSHI_LIVE_STATE.json` directly. The box
   has all 4 GB of swap in use and 1.8 GB RAM free, and the dev DB is 1.8 GB; a writer every
   10 seconds adds lock contention and a timer to keep alive. Drop plan tasks 3 and 5 (the
   `tennis_live_state` table and the 10-second ingest).
2. **Ship a standalone panel first, without ESPN matching.** Measured 2026-10-14: none of
   Kalshi's three match ids (`5437919`, `20261013B786F4B2`, `sr:sport_event:75373642`) appear
   in any `scoreboard_snapshots` WTA payload (0 rows each). Only player names match (2 rows for
   "Pohankova"). So no key links a Kalshi match to an ESPN game. Phase 1 shows Kalshi live
   matches as their own panel. Phase 2 (ESPN matching) waits.

### Facts checked on 2026-10-14, 01:05 UTC
- The poller handed over on its own. The 01:00 UTC run has the new code and writes
  `/root/prediction-market-trading/data/orderflow/KALSHI_LIVE_STATE.json`. At 01:05 it held
  `{"generated_at": ..., "poll_s": 4, "matches": []}` (no live matches at that hour).
- The poller's log times are UTC. `ps` start times are local (UTC-5). Runs last 55 minutes
  (`RUN_MINUTES = 55`) and cron starts one every 5 minutes; extra runs exit on the lock.
- With no milestones the loop sleeps 60 seconds, so `generated_at` can be up to ~64 seconds old
  while the poller is healthy. A match whose live_data call fails is LEFT OUT of that round's
  `matches` (the loop does `continue`), so a missing match means "no fresh reading".
- Current per-match fields (in `main()`, the `snap.append` call): `milestone_id`, `title`,
  `tour`, `status`, `finished`, `game_score_p1`, `game_score_p2`, `advantage`, `server`,
  `sets_p1`, `sets_p2`, `points_won_p1`, `points_won_p2`, `polled_at`.
- `server` is a Kalshi competitor id, but the file does not carry `competitor1_id` or
  `competitor2_id`, so the reader cannot tell which side serves. There is no tournament name
  and no `schema_version`.

### Step 1. Poller: add the missing fields (prediction-market-trading, branch `main`)
- Edit `kalshi_live_points.py` only. In the `snap.append({...})` dict add:
  `"competitor1_id": cur["c1"], "competitor2_id": cur["c2"]`,
  `"server_side"`: `"1"` if `cur["server"] == cur["c1"]`, `"2"` if it equals `cur["c2"]`, else
  `""` (compare as strings),
  `"sets_won_p1": cur["sw1"], "sets_won_p2": cur["sw2"]`,
  `"tournament"`: the same value the point rows use for `_tournament` (read `row()` to find it),
  `"p1"`, `"p2"`: from `names(m.get("title"))` (display only, never a key).
- In `write_state`, add `"schema_version": 2` to `body`.
- Do NOT change the point rows (`row()`), the lock, the poll loop, or the failure handling.
- Add tests to `test_kalshi_live_state.py`: `schema_version` is 2; `server_side` is "1", "2" and
  "" for the three cases. Run `cd /root/prediction-market-trading && python3 -m pytest -q
  test_kalshi_live_state.py`.
- Do not restart the poller. The next run after the current one ends (the :00 UTC launch after
  the :55 exit) loads the new code. Confirm with `head -c 600` on the state file after that.
- The repo has about 26 uncommitted files from other work. Commit only these two files, by name.

### Step 2. LP reader and API (legendarypicks, new worktree)
- `git worktree add /root/lp-tennis-points -b feat/tennis-points dev`. Work only there.
- New module `backend/kalshi_live_state.py`:
  - Path from env `LP_KALSHI_LIVE_STATE`, default the PMT path above.
  - Read the file, cache on its mtime. Never open, flock or stat
    `_kalshi_live_points.lock`.
  - Missing file, bad JSON, or `schema_version != 2`: return
    `{"available": false, "reason": "<exact reason>"}` and log it. Never an empty list that
    looks like "no matches".
  - File staleness: `now - generated_at > 90s` means `available: false, reason: "poller stale
    since <time>"` (90s covers the 60-second idle sleep).
  - Per match: `age_s = now - polled_at`. 0 to 15s fresh, 15 to 60s aging, over 60s drop the
    match. Drop `finished: true` matches.
  - Filter by tour: `atp` gets `tour == "ATP"`, `wta` gets `tour == "WTA"` (check the real
    values in the file first; do not guess the case).
- New endpoint `GET /api/{league}/kalshi-live` (atp and wta only, 404 otherwise) in
  `backend/routers/games/scoreboard.py`, returning `{available, reason, generated_at,
  matches: [...]}` with the fields from step 1 plus `age_s` and `freshness`.
- Score values are passed through as Kalshi publishes them. An unexpected value (tiebreak
  counts, retirement, walkover are not verified) is shown as-is, never coerced to 0.
- Tests with fixture files: fresh file, 2-minute-old file, zero-match file, torn JSON, missing
  file, schema_version 1, one match aged 30s, one aged 120s, one finished.
- Verify: `curl -s 127.0.0.1:8096/api/wta/kalshi-live | jq` on dev only. Do not restart any dev
  server you did not start (memory: never restart an externally-managed dev server). If the
  route needs a restart to appear, stop and tell Micah.

### Step 3. Panel on the ATP and WTA scores pages
- Load `.claude/skills/honest-data-ui` and `.claude/skills/fail-loudly` first.
- A "Live points (Kalshi)" panel above the ESPN cards on the ATP and WTA scores views. Find
  where the scores page renders `components/Scores/GameCard.tsx`; add a new component next to
  it, do not change GameCard.
- One hairline row per match (memory: one panel per group, hairline rows, no box per item):
  p1 and p2, set games per set, current point score, a dot on the serving side, and a muted age
  label ("Kalshi, 6s ago"); the label turns to the warning tone from 15 to 60s.
- `available: false`: show one muted line "Point scores unavailable: <reason>". No live
  matches: "No live Kalshi matches". Never show a frozen score.
- Poll the endpoint every 5 seconds only while the panel is on screen and the day is today.
- Tests next to the component (jest), covering fresh, aging, unavailable and empty. Run
  `/root/legendarypicks/node_modules/.bin/jest components/Scores`.
- Headless check of `/scores?league=WTA` and `?league=ATP` with zero page errors.

### Step 4. History loader for the point rows (Micah wants them in the DB)
- New `backend/ingest_kalshi_tennis_points.py`, modelled on `backend/ingest_usopen_points.py`.
  Reads `KALSHI_POINTS_*.jsonl` into a dev table `kalshi_tennis_points`. Dedupe key:
  (`_match_id`, `PointNumber`, `EpochTimeEnd`). Keep every field (store the raw JSON too).
- Back up the dev DB first (rule in section 6). Check `uptime` and `free -h` first.
- Report rows read, inserted, skipped as duplicates, and rejected, per file. Zero inserted from
  a non-empty file is a failure (fail-loudly).
- Run it by hand once. A schedule (hourly, OnCalendar, never a monotonic timer) needs Micah's
  go.

### Step 5. Live check (when Shanghai or Wuhan is in play, roughly 03:00 to 14:00 UTC)
- `generated_at` advances every ~4 to 6 seconds; the match appears; `polled_at` advances.
- The panel's score equals the state file at the same moment, and the next point row's
  before-point score equals the last score the panel showed.
- For 10 points, the side whose score moves in the panel is `PointWinner` in the point rows.
- Copy the state file, freeze it 2 minutes old, point `LP_KALSHI_LIVE_STATE` at the copy in a
  test run: the panel must say unavailable.

### Phase 2 (not now): attach to ESPN cards
- Table `tennis_player_source_ids` pairing Kalshi competitor id with ESPN athlete id. A script
  proposes pairs by name within the same tournament and UTC date; Micah confirms them. A match
  binds only when both players are confirmed. Never bind on names alone (memory: trust lists
  never keyed on name alone). Unverified: whether Kalshi competitor ids are stable across
  tournaments; check in the state files once step 1 is live.

### Stop and ask Micah before
- Pushing anything, touching `picks.db`, restarting the poller or any server, or adding a
  timer or cron entry.

## 1. Where things live

Two repos are involved. Do not mix them up.

| What | Repo or path |
| --- | --- |
| LP app, dev DB (`backend/data/picks.dev.db`), all tennis tables | `/root/legendarypicks` (branch `dev`) |
| Trade desk: Kalshi poller, US Open capture, point files | `/root/prediction-market-trading` (branch `main`) |
| Handoff and context docs | `/root/legendarypicks/docs/` |
| US Open point files (clean) | `/root/prediction-market-trading/data/orderflow/USOPEN_POINTS_dedup_20260902_20260921.jsonl` |
| Kalshi point files | `/root/prediction-market-trading/data/orderflow/KALSHI_POINTS_YYYYMMDD.jsonl` |

Do not look for these docs in the trade desk repo. Do not check the root `picks.dev.db`, which is a
different file and does not have the new tables.

## 2. Done and committed

- `5994de6`, `4964eb8`: MLS radio play button merged; MLS station-page code removed.
- `3683b25`, `9d17f47`: skill and handoff edits, four docs.
- `4964eb8` and `5994de6` are on `dev`. `feat/game-audio-links` is deleted.
- `b0935f2`: `backend/ingest_usopen_points.py`, the US Open point loader.
- `e8dc17a`: `docs/TENNIS-DATA-2026-10-13.md` and the later context section.
- `efed4ef` (prediction-market-trading, branch `feat/kalshi-live-state`, also fast-forwarded into
  `main`): the Kalshi poller writes `KALSHI_LIVE_STATE.json` after every poll. Three tests in
  `test_kalshi_live_state.py` pass.

## 3. Done in the dev DB (not in git)

- `tennis_atp_*` tables from the GitHub mirror: 988,216 singles matches, 26,399 doubles,
  3,420,595 ranking rows, 66,912 players. Backup: `backend/data/backups-tennis-20261013/`.
  Taken before the load finished, so it can undo the whole load but not a single fix.
- `usopen_points`: 107,132 rows (84,173 capture, 22,959 official history), 699 matches. Backup:
  `backend/data/backups-usopen-20261013/picks.dev.db.pre-usopen-points-20261013.bak`.
- Full integrity check of the dev DB: `ok`, 185 seconds.

## 4. Pending, and what NOT to do

### The Kalshi poller (trade desk, live)
- It is the only live point source for Shanghai and Wuhan. Do not kill or restart it by hand.
- Update 2026-10-14 01:05 UTC: the lock handed over and the new code is running. The state
  file exists (see section 0).
- A cron job runs it every 5 minutes, and each new run exits because the old one holds the lock.
  When the old process ends, the next run loads the new code. Let the lock hand over.
  (This cron schedule was reported by a read-only check. Confirm it before relying on it.)
- Restarting by hand during live matches leaves a gap of up to 5 minutes. Those points cannot be
  recovered.

### Scoreboard integration (not built)
- The copy job (state file into the dev DB, every 10 seconds) is not built. Concern: 10-second
  writes to the 1.8 GB dev DB could contend for SQLite's write lock. Options: a separate small
  DB for live state, or a longer interval.
- The API change and the tennis card are not built.
- Player ID linking between Kalshi and ESPN is not built. Kalshi and ESPN share no IDs. Nothing
  attaches a point score to a scoreboard game until this is solved.
- Plan: `docs/PLAN-tennis-points-scoreboard-2026-10-13.md` (untracked, Opus, plan only).

### US Open capture fix (trade desk, uncommitted)
- `usopen_points.py` and `test_usopen_points_seen.py` in prediction-market-trading are fixed and
  tested, but uncommitted. The repo has 26 other uncommitted files that belong to other work.
  Commit only these two, by name.
- The capture job is stopped. Keep it stopped until the fix is committed.
- The root cause: the seen list was capped at 60,000 keys, so old points were re-written after
  each poll. Fixed by removing the cap and making a corrupt or unwritable list raise.

### ATP data fixes (Codex)
- Plan: `docs/PLAN-atp-data-fixes-2026-10-13.md` (untracked). Scope: singles only.
- Codex works in `/root/lp-atp-data-issues`, branch `fix/atp-data-issues`, from `e8dc17a`. At last
  check it had no commits and three untracked files (ATP Sackmann ingest, its test, its manifest).
  It may still be working. Do not run `git add -A` there.
- Decisions D1 to D8 in the plan belong to Micah. Codex stops and asks.

### WTA
- Next after ATP. Same method: backup first, new `tennis_wta_*` tables, singles only. Waiting for
  Codex's ATP template and a go from Micah.

### Shanghai and Wuhan point sources
- Shanghai official feed: the live-matches endpoint works but was empty when checked. The match-stats
  endpoint has per-set totals only. No point list was found.
- Wuhan (WTA): the match page embeds the match state, with blank point fields for a finished match.
  Checked the page HTML and its JavaScript bundles. No point endpoint found.
- Decision taken: use Kalshi (via the poller), not the official sites, for Shanghai and Wuhan.

### Missing data that is known and not loaded
- US Open doubles, qualifying, junior and wheelchair events.
- Grand Slam history 2011 to 2024 in the mirror's `slam_pointbypoint/` folder (166 files).
- 284 match IDs in the US Open points that are missing from the match index.

## 5. Decisions waiting for Micah

1. Commit the two untracked plan documents (`PLAN-atp-data-fixes`, `PLAN-tennis-points-scoreboard`).
2. Commit the US Open capture fix in prediction-market-trading.
3. Scoreboard: state-file route or DB route; which ID system; copy-job interval.
4. Go-ahead for the WTA load after Codex's ATP work is reviewed.
5. Whether to add the 284 unindexed match IDs to the index.
6. Whether to download the Grand Slam history.
7. Whether to push `dev`. It is about 25 commits ahead of `origin/dev`.
8. Whether to merge `docs/tennis-prediction-brief` (branch, commit `bfc3536`) into `dev`.

## 6. Rules that still apply

- Dev DB only for writes. Never touch `backend/data/picks.db`.
- Stage named files only. Never `git add -A` or `git add .`.
- No em dashes in code, docs, or commits.
- Back up a database before writing to it.
- Check `uptime` and `free -h` before a heavy job. RAM is tight.
- Opus is for planning only. Implementation goes to Sonnet, Haiku or Codex.
- The US Open API works through the trade desk's client (urllib, the script's User-Agent). `curl`
  to the same URLs fails. Use the script's client.
- tennistemple.com returns 403. Do not try to get around it.
