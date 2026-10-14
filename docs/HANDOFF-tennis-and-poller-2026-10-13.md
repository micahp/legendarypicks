# HANDOFF: tennis data, Kalshi poller, US Open points (2026-10-13)

Written at the end of a long session so a fresh one can continue safely. Read this first, then
`docs/CONTEXT-2026-10-13.md` (section "Later on 2026-10-13: tennis data") and
`docs/TENNIS-DATA-2026-10-13.md`.

Nothing here is pushed. Nothing has been written to prod (`picks.db`).

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
- It was running the OLD code at last check (pid 1346465, started 19:00). It has no
  `KALSHI_LIVE_STATE.json` yet.
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
