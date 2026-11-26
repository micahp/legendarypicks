# HANDOFF 2026-07-26 (pt.3) — design research done, NFL player page restructured, prod data gap sent to Codex

**Read this first.** Supersedes pt.2 for the NFL player page and the design question. Pt.2 §3
(live processes), §4 (prod v0.6.5 / GA4 / tags) and §5 (prod data gap detail) still hold.
The 07-25 doc's §1 product direction is still current.

---

## 1. WHAT IS IN FLIGHT RIGHT NOW — check this first

**Codex (tmux `codex:0.0`) is executing `/root/TASK-prod-data-gap.md` against the PRODUCTION
database.** Sent at the very end of the session; it was ~5s in when context ran out. Nobody has seen
its output.

- The spec has a **mandatory stop-for-approval gate** after the UFC dry run. It should be waiting
  there, or asking. **Check the pane before doing anything else** — `tmux capture-pane -p -t codex:0.0`.
- It writes to `/root/legendarypicks/backend/data/picks.db`. Guardrails in the spec: back up first
  with integrity check, single short transaction (prod is `journal_mode=delete`, a slow loop holds an
  exclusive lock and blocks the live site), no `rm`/`DROP`, no host config, no `npm run build` in
  `/root/legendarypicks`.
- **The MLB trap it must not fall into:** 51 rows where prod holds a *pitching* line and dev a
  *batting* line under the same natural key. The merge must be a JSON key union with prod winning
  every collision, and it must report the skipped count — **exactly 51, or stop.** A blind
  `UPDATE stats = dev.stats` silently swaps them.
- Micah accepted the risk of an agent holding prod write access after it was flagged.

## 2. Design research — DONE, and it changed the plan twice

Full research: **`/root/lp-verify/design-research-nfl-usage.md`**. Spec: **`/root/lp-verify/spec-nfl-usage-surfaces.md`**
(§0b records the decisions; the old "Fantasy tab" section is marked SUPERSEDED, kept for the trail).

Scraped live with headless Chromium. **ESPN and Pro-Football-Reference 403 this box** (CloudFront
datacenter-IP block) — **the Wayback Machine works, use it**, that is how ESPN/PFR were obtained.

| site | type | fantasy lives | usage lives |
|---|---|---|---|
| ESPN | reference | Overview card only; **zero fantasy columns in any stat table** | Splits tab |
| PFR | reference | own `Fantasy` section | own `Snap Counts` section |
| FantasyPros | fantasy | trailing column on every table | separate league-wide reports |
| PlayerProfiler | fantasy | 1 of 3 headline charts | `Advanced Stats & Metrics` |

**Reference sites separate fantasy; fantasy sites inline it.** My first conclusion ("nobody separates
fantasy") was drawn from two fantasy sites and was wrong — Micah caught the sampling flaw. All four
separate **usage from box score**, which is positioning-independent and is what the work is built on.

**Two decisions Micah made, both against my initial spec:**
1. **No Fantasy tab.** Fantasy stays inline where it already renders (`fpts_ppr` as the trailing
   column of `NflUsageTrend`, `fpts`/`fpts_ppr` as projection rows). "Save the click." He will judge
   it in the running UI.
2. **Projections belong on an Overview tab, not a Fantasy tab** — they are league-neutral by
   construction (`players.py` projects *every numeric blob key*), so MLB gets `H/TB/HR/K/outs`, NHL
   `goals/assists/shots`. An NFL-only tab would be wrong for five of six leagues.

**Scope narrowed to NFL only.** Every other league keeps the flat stack, untouched.

**Still open: the positioning call** (§0 of the spec). LP is neither a reference site nor a fantasy
tool suite; proposed axis is "should I make this pick" (usage) vs "did it hit" (box score + fantasy).
Not decided.

## 3. Shipped — branch `feat/nfl-usage-renderer` in `/root/lp-nfl-usage`, NOT pushed, NOT merged

- **`e463c40`** — curate projections. `/api/player/{id}` was projecting every numeric blob key →
  17–20 rows including `cushion`, `separation`, `off_pct`, all-zero `def_*`/`st_*`. Now an NFL
  allowlist (`_NFL_PROJECTION_STATS`) + drop-all-zero. **McBride 17 → 6 rows.**
  NFL key normalization was *required*, not cosmetic: 2024 rows are legacy-keyed (`receptions`),
  2025 canonical (`rec`), no season mixes them, so a 2024 player would have missed the allowlist and
  lost every projection. Verified on Elliott.
- **`6b8276c`** — tab strip **Overview │ Usage │ Game Log**, NFL only. `show()` is unconditionally
  true off NFL — verified MLB has no tab strip and all four sections. `NflUsageTrend` gained
  `showHeader` (default true) to kill the duplicate identity line.
- **`37c0384`** — real game-log table with ESPN-style phase bands, replacing the raw strings
  (`targets 8 rec 7 rec_yds 65 …`). Bands with no data are dropped (deviates from ESPN deliberately).
  Verified: **QB → Passing+Rushing, RB → Rushing+Receiving, TE → Receiving.** The RB regression the
  pt.2 handoff warned about does not happen.
  Also fixed real misinformation: `game_date` and `home_away` are **NULL on all 5,377 NFL rows**, so
  `{g.home ? 'vs' : '@'}` printed "@ OPP" for every game, asserting away for home games. Week
  (`game_no`) is now in the payload and the opponent stands alone.

**SLICE 4 IS HALF-DONE — `backend/routers/nfl_usage.py` is MODIFIED AND UNCOMMITTED.**
Backend now returns `carries`, `carry_share`, `rush_yds`, `rush_td`; `_fetch_team_target_sums` was
generalized to `_fetch_team_stat_sums(con, keys, stat_key)` with a `_TEAM_SUM_STATS` whitelist, and a
team carry-sum query was added so carry share works. **Tests: 10 passed** — but only with
`LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db` set; without it 3 real-DB tests fail with
"Player not found" and that is an env artifact, not a regression.
**Not done: the frontend columns.** `NflUsageTrend`'s `COLUMNS` is still a flat receiving-only list.
Next step is banding it (`Snaps │ Receiving │ Rushing │ Fantasy`) and dropping empty bands, mirroring
the game log. **Why it matters:** verified Elliott wk16 renders `3 snaps, 5%, 0 targets, 6.1 PPR` —
six of ten columns dead and the fantasy points look like they came from nowhere.

## 4. Live processes — unchanged from pt.2, still need teardown

| what | port / id | notes |
| --- | --- | --- |
| worktree backend | `:8098` | restarted twice this session; **no `--reload`, restart it manually after any Python edit** |
| worktree `next dev` | `:3099` | cwd `/root/lp-nfl-usage`, hot-reloads |
| cloudflared | pid 1193442 | **https://crossword-expansys-transition-victorian.trycloudflare.com** → `:3099`, verified working |

Restart line for `:8098` (GRID_API_KEY is not needed with the warmer off):
```
cd /root/lp-nfl-usage/backend && LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
  LP_ESPORTS_WARMER_INTERVAL_S=0 /root/legendarypicks/backend/venv/bin/python venv/bin/uvicorn sports_service:app --port 8098
```

**Leave alone:** `:3096`/`:8096` = `/root/legendarypicks` @ `dev`, externally managed. `:3095` orphan.

**Gotcha that cost real time:** shipping a frontend change that reads a new API field *before*
restarting the backend makes the field render as `—` for everyone. Micah saw exactly that ("week is
all dashes"). Restart the backend in the same breath as the edit.

## 5. Open

1. **Codex's prod run** (§1) — highest priority, unsupervised and mid-flight.
2. **Slice 4 frontend** (§3) — uncommitted backend work is stranded without it.
3. **Season Stats has the same zero wall** the projections had — `Pass Yds/G 0`, `Pass TDs 0`,
   `INTs 0`, `Comp/G 0`, `Pass EPA 0`, `Carries/G 0`, `Rush Yds/G 0` on a TE. Different code path
   (`_season_stats_for_profile`). Offered as "slice 1b", Micah never answered.
4. **Push the branch** — `e463c40`/`6b8276c`/`37c0384` are local only, same at-risk state pt.2
   flagged. Merge-to-`dev` still Micah's call; `cc78729` (option A) is superseded by this restructure.
5. **The hub / option B** — week matrix, metric switcher, default Snap% (10,689 rows). WOPR/aDOT stay
   off the default: 2,466 rows / **260 distinct players** would render a board that is 90% dashes.
   Deliberately deferred until the player page settles.
6. `usage_trend_viewed` still unwired.
7. Untouched from pt.2 §6: no NFL pick surface, GitHub Action for the version guard, prod visitor
   figure, `/strength` gate, `streams.py` decapi wobble, Underdog fighter identity gap.

## 6. Artifacts

`/root/lp-verify/` — `design-research-nfl-usage.md`, `spec-nfl-usage-surfaces.md`,
`mcbride-slice1.png`, `slice2-nfl-{overview,usage,gamelog}.png`, `slice2-mlb-control.png`,
`gamelog-{josh-allen-qb,elliott-rb,mcbride-te}.png`, plus pt.2's `ga-verify.js` / `shot*.js`.
`/root/TASK-prod-data-gap.md` — the Codex spec.
