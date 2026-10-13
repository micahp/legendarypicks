# LP handoff — 2026-07-27 pt.4 (supersedes pt.3)

**Work queue: `/root/legendarypicks/docs/ROADMAP.md`.** This file is session state and
decisions only.

**v0.6.9 shipped** — `2ac347f` on `origin/dev`, tag `v0.6.9` pushed. Working tree clean.

---

## 1. pt.3's four asks — all closed, but two of them were closed by finding it wrong

1. **Skill rename: reverted, do not redo.** Renamed to `rams-krug-data-ui`, Micah reversed
   the call the same day while it was unpushed. Commit dropped. **`honest-data-ui` is the
   settled name** — the memory pointer now says so.
2. **Two servers killed.** But not the two the port table named. `/root/lp-ufc-fight-stats`
   had been **deleted from disk** while its `next dev` (`:3095`) and uvicorn (`:8095`) kept
   running out of the deleted directory for ~3.8 days — `readlink /proc/PID/cwd` showed
   `(deleted)`, and `:3095` served 500 the whole time. Survivors are `:3096` → `:8096`.
3. **The tunnel was never broken.** pt.3's "→:3096 is the culprit" is wrong: `:3096` is the
   *correct* frontend, proxying to `:8096` via `.env.local` (which is why `/proc/PID/environ`
   looked empty — `next.config.js` logs the resolved target at startup, grep the dev log).
   `https://someone-decorative-wearing-produce.trycloudflare.com` was live throughout.
   **Deliberately not refreshed** — restarting mints a new URL and breaks a working one.
4. **`b0b659f` pushed**, verified against the remote.

Also fixed: all 16 `../CONTEXT-*.md` links in `MEMORY.md` pointed at a directory that does
not exist; now absolute `/root/legendarypicks/docs/CONTEXT-*.md`. Two memory files existed but were unindexed.

## 2. What shipped in v0.6.9

The board Micah asked for **already existed**, ranking on `fantasy_ppr_g` — points per game
*played*, an average conditioned on the exact thing a drafter is predicting.

- **Availability is the headline**, games played / 17. Denominator is a **constant**,
  verified as 32 teams × exactly 17 games in both seasons. This sidesteps B1/B2/B3 entirely
  — deriving it from `team_game_results` is what made Flacco read 13/34. He now reads 13/17.
- **Postseason (weeks 19–22) excluded**, or a deep run reports 21/17.
- **Both averages always together.** Burrow 2025: 16.8 per game played, 7.9 per team game.
- **xFP ingested** from ffverse/ffopportunity (published, not derived). Measured 2024→2025:
  xFP/g beats actual PPR/g at predicting next season, widest at thin samples (r=0.424 vs
  0.374 at ≤4 games; 0.778 vs 0.775 at 10+). **Say it honestly — that is "less misleading",
  not "reliable".**
- **target_share** was already published by nflverse at 100% coverage: a one-line `_MAP`
  addition, not a derivation. **2026 depth chart** ingested for current role.
- **Rookies read "No NFL sample", never zero.** Jeremiyah Love (ADP 17.5, 98% owned, ARI
  RB1) was invisible under v1's `games>0` filter, along with 147 other ADP-ranked players.
- **Accent colour marks absence.** Strip = one cell per game the team played (17, not 18 —
  a bye is not an absence).
- Suite 249 passed/4 failed → **256 passed/1 failed** (ROADMAP B4 closed; the survivor is
  the unrelated MLB contract, B5).

## 3. The news-feed question: answered NO, with evidence

Micah asked whether we need player news from fantasy apps to fill the no-signal gap.

- **The gap is 7 players.** ESPN parks undrafted players at a sentinel: 1,392 of 2,511 ADP
  rows sit at exactly **170.0**. Only **248** carry a real ADP. Of those, only 7 QB/RB/WR/TE
  have zero NFL games — and all 7 are in the published depth chart with a rank.
- **The factual layer of "news" is free.** Injury *status* comes from the official NFL
  injury report (teams file Wed/Thu/Fri); nflverse republishes it as `injuries` 2009–2025.
  The prose blurbs are licensed from Rotowire/RotoBaller/Sportradar — and that paid half is
  exactly the half Micah said not to trust for injury truth.
- **Decision: took `depth_charts` now, deferred `injuries` to in-season.** No scraper.

## 4. UI verified live on the tunnel, and visually reviewed

Confirmed live through `https://someone-decorative-wearing-produce.trycloudflare.com`:
the API returns `nfl-draft-board-v2`, and the served bundle
(`_next/static/chunks/pages/leagues/[league].js`) contains `/ team game`,
`No NFL sample` and `bg-amber-500` while `Season Proj` and `games_assumed` are **gone** —
so v1 is replaced, not shadowed.

Screenshotted with Playwright (chromium is installed; `~/.cache/ms-playwright`) at 1600px
and 820px. **No horizontal page overflow at either** — the table scrolls inside its own
container. The signature rule reads as intended: Rashee Rice 8/17 shows amber across the
front of his season (his 6-game suspension, rendering correctly without being special-cased)
with 18.8 → 8.8 beside it; 17/17 players render entirely quiet. Jeremiyah Love sits at rank
15 with "No NFL sample", em dashes, and his ADP intact.

Still not measured: the `docs/DEV-STANDARDS.md` payload rule for this board.

## 5. Things worth not repeating

- **A port table is not evidence of which checkout a server belongs to.** Check
  `/proc/PID/cwd` for `(deleted)`. A 200 on `/health` proves a process is alive, not that
  its code still exists.
- **A handoff's named cause is a hypothesis.** pt.3 asserted the tunnel was stale and
  `:3096` was wrong; both were false, and "fixing" it would have broken a working URL.
- **I broke 5 tests** adding `target_share` to `_MAP` (fixtures build a synthetic artifact
  and `_NEEDED` fails loud on a missing column). Caught and fixed same turn. If you add to
  `_MAP`, update `test_ingest_nfl_weekly_stats.py`'s `_artifact_row`.
- **Check whether the value is published before deriving it** — paid off three times today:
  `target_share` (published), xFP (published), depth charts (published). I nearly computed
  target share from ffopportunity's `rec_attempt / rec_attempt_team`.

## 6. State

- `origin/dev` = `2ac347f`, tag `v0.6.9`. Tracked tree clean.
- Untracked and unreviewed, carried over from pt.3: `backend/run_wc_prop_history_ingest.py`
  + its test (Codex's, never reviewed), `docs/TASK-*.md`, various logs.
- **Prod is on v0.6.7** and still serves pre-swap NFL numbers. Deploy still deferred (R6).
- Dev: `:3096` → `:8096`, tunnel URL in §1. **`:8096` runs `--reload` at 67% CPU**
  (ROADMAP O3) — O1 did *not* make this moot, it is now the surviving dev backend.
- Codex out of quota until Aug 1.
- Cached artifacts (reuse, don't refetch): this session's scratchpad holds
  `ep_weekly_2024/2025.parquet` and `depth_charts_2026.parquet`.

## 7. The lesson

pt.3's was *check what a component is for before feeding it data.* Today's is one level up
again: **check whether the thing you were told is broken is actually broken.** Two of the
four asks dissolved on inspection — the tunnel was fine, and the servers to kill were not
the ones named. The draft board was the same shape: the work was never "build it", it was
"find out what's already there, and whether the premise holds."
