# HANDOFF 2026-07-26 (pt.2) — prod on v0.6.5, GA4 live, NFL usage mounted; NEXT = design research

**Read this first.** Supersedes `CONTEXT-2026-07-26-HANDOFF.md` (pt.1) for prod state, versioning and
the NFL usage renderer. Pt.1's §5 operational notes still hold. The 07-25 doc's §1 (product direction:
brand-is-the-spec, fantasy-football focus, prop-outcome ledger as the acquisition thesis) is **still
current and not superseded by either.**

---

## 1. FIRST ACTION NEXT SESSION — the design research Micah asked for

**This is where the session stopped, mid-task.** The `frontend-design` skill was loaded and one
FantasyPros search had run when Micah called the context reset. Nothing was designed or written.

**His brief, verbatim in substance:** the player page is showing too much on the game log; fantasy
points should probably be separated somehow; **his instinct is fantasy stats as their own separate
tab**; Recent Games and Usage Trend show *some* of the same data and *some* different data. He asked
for research into **how ESPN, FantasyPros, and others structure this** before proposing anything, and
explicitly said to load the frontend-design skill (do it again — skills don't survive a reset).

Do the research first, then propose. Do **not** start editing components before showing him a plan.

**The concrete redundancy, observed from real screenshots (in `/root/lp-verify/`):**

1. **Recent Games is strictly redundant for NFL.** It lists the same games as Usage Trend but as raw
   strings — `targets 8 rec 7 rec_yds 65 rec_td 0 fpts 6.5 fpts_ppr 13.5` — where Usage Trend has a
   real table with shares. **Precedent already in the codebase:** UFC gets a Recent Fights table
   *instead of* Recent Games (`pages/player/[id].tsx`, gated `p.league === 'ufc'`). NFL wants the
   same swap.
2. **The Projections wall buries everything.** 17–20 rows including `def_pct`, `def_snaps`, `st_pct`,
   `st_snaps` — all zeros for a WR/TE. Usage Trend lands ~1000px down the page. Pre-existing, not
   caused by the mount, but it is why option A "feels buried."
3. **Duplicate identity header.** The page header renders "Trey McBride / ARI · TE · NFL · 2025", then
   `NflUsageTrend` renders its own "Trey McBride TE ARI 2025" because it was built standalone.
4. **Window mismatch** — Usage Trend shows 8 weeks (hook hardcodes `weeks: '8'`), Recent Games shows 15.

**Overlap map (what actually differs), from `NflUsageTrend.tsx` COLUMNS vs the Recent Games row:**
- Both: opponent, targets, rec, rec_yds, rec_td, fpts_ppr
- Usage only: week, snaps, snap%, target share%, aDOT, air-yards share%, WOPR
- Recent Games only: carries / rush_yds / rush_td for RBs (usage table has no rushing columns at all)

That last point matters: a straight swap **loses rushing data for RBs**. Whatever is proposed has to
handle RB usage (carries, route participation) or the swap is a regression for half the position pool.

## 2. Where the NFL usage work stands

- Worktree **`/root/lp-nfl-usage`**, branch **`feat/nfl-usage-renderer`**, now **pushed to origin**
  (was local-only and at risk; that loose end is closed).
- `3317a27` — endpoint + renderer (from pt.1).
- **`cc78729` — option A: mounts `NflUsageTrend` on `pages/player/[id].tsx`, gated `p.league === 'nfl'`,
  placed after Projections.** Season deliberately left unset so the endpoint resolves the player's most
  recent season with logs (the page is reachable in the off-season).
- **NOT merged to `dev`.** Merging is what puts it in the next prod build — that is still Micah's call.
- `usage_trend_viewed` is **still not wired.** Mounting unblocks it; nobody has added the call.

**Verified renderer math (don't re-derive):** WOPR for McBride wk18 = 1.5(0.286) + 0.7(0.189) = 0.561,
matching the 0.6 in the table and the 0.560 average. **Scale tripwire:** `target_share` is 0–1 in the
stats blob but `air_yds_share` is 0–100; the router normalizes before computing WOPR and the component
formats each on its own scale (`fmtPct` vs raw `fmt`). Anyone "fixing" one scale breaks WOPR.

**Data coverage in `picks.dev.db` (shapes what a leaderboard can rank on):**
- `off_pct` (snap share): 10,689 NFL rows — near-full coverage
- `targets`: 9,660 rows
- `air_yds_share` / `adot`: **2,466 rows, only 260 distinct players** (NGS covers real receivers only)
- `wopr`: **0 rows — computed in the router, never stored**

**Test players:** McBride `14572` (full NGS), Ja'Marr Chase `3984`, Rashid Shaheed `19984` (partial NGS,
shows the dash state).

## 3. LIVE PROCESSES — started this session, tear down when done

| what | port / id | notes |
| --- | --- | --- |
| backend for the worktree | `:8098` | `LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db`, `LP_ESPORTS_WARMER_INTERVAL_S=0` |
| `next dev` for the worktree | `:3099` | cwd `/root/lp-nfl-usage`, `API_PROXY_TARGET=http://localhost:8098` |
| cloudflared for the branch | pid 1193442 | **https://crossword-expansys-transition-victorian.trycloudflare.com** |

**Leave alone:** `:3096` + `:8096` = `/root/legendarypicks` @ `dev`, externally managed, and the
2-day-old cloudflared on pid 3928058 (`someone-decorative-wearing-produce.trycloudflare.com` → `:3096`).
`:3095` is still the pre-existing orphan returning 500 from a deleted worktree.

Box was at ~1.2GB available with all of the above running. Kill the three new ones when the design work
is done, or sooner if memory gets tight.

**DNS quirk, cost 10 minutes:** this box's resolver returns **NXDOMAIN** for a freshly-created
trycloudflare hostname while `8.8.8.8`/`1.1.1.1` resolve it fine (`resolvectl flush-caches` does not
help). The tunnel worked from Micah's browser the whole time. To verify from here, pin the IP:
`curl --resolve host:443:<ip>` or Chromium `--host-resolver-rules=MAP host ip` (see
`/root/lp-verify/shot-tunnel.js`). **Check public DNS before concluding a tunnel failed.**

**Also: grepping served HTML for a client-rendered section is a false negative.** `/player/[id]` fetches
the player client-side and gates the section on `p.league === 'nfl'`, so SSR ships only the loading
state. Same trap as the GA4 tag. Verify in a browser.

## 4. Shipped this session

**Prod promoted v0.6.0 → v0.6.5** (`docker compose up -d --build`, ~35s of `next build`, no OOM).
Rollback images `legendarypicks-{frontend,backend}:rollback-pre-v0.6.5`. Verified: all pages 200 direct
on `:3100` and through nginx; esports warmed 0 → 379 matches; `/api/props` 50 rows; no errors in the
backend log. **No DB migration was needed — verified, not assumed** (only `CREATE TABLE IF NOT EXISTS
player_game_logs` + one index in the whole `v0.6.0..v0.6.5` backend diff; prod's columns already
identical). Full detail in the `reference_lp_prod_deploy` memory.

**GA4 is live and browser-verified** on `G-ZZKRW6MMMM`, against both `127.0.0.1:3100` and
`https://legendarypicks.xyz`: correct loader id, `send_page_view:false`, exactly 1 `page_view` on hard
load and exactly 1 more per client-side nav (no dupes ⇒ the enhanced-measurement history toggle is
still off), correct per-route `page_title`. Reusable checker: **`/root/lp-verify/ga-verify.js`**
(stubs `**googletagmanager.com/**` via `page.route`, reads `window.dataLayer`).

**Retroactive release tags.** `v0.6.2` → `bab94eb`, `v0.6.3` → `b9253ca`, `v0.6.4` → `77dec82`, all
pushed. **`v0.6.1` deliberately does not exist** — `package.json` went 0.6.0 → 0.6.2 in a single commit
whose own subject is "v0.6.1 + v0.6.2", and the two scopes are interleaved in the log so no clean cut
point exists. v0.6.2's annotation documents **both** releases' changes. Micah agreed to skip it.
`git describe` on `dev` is unchanged (`v0.6.5-1-g5378a3c`), so the pre-push hook and `scripts/release.sh`
are unaffected.

## 5. Open — the prod data gap (scoped, not executed)

Prod shipped the v0.6.2–v0.6.4 features with **no data behind them**. Micah's framing, confirmed: the
UFC roster is **scoped to whoever is on the next card**, so this is structural, not a one-off.

**UFC — run the ingest, do NOT copy from dev.** Prod's `prop_games` for UFC are all from **2026-07-25**
(13 rows), and its 26 tracked fighters *are* that card. Dev's 21 game-logged fighters are a *previous*
card — different people. There is also no join key: prod's UFC players all have **empty `espn_id`**, and
42 of dev's 49 do too (dev's linkage was made by name at ingest). `ingest_ufc_fight_stats.py:96-103`
resolves by name when `espn_id` is empty, so pointing it at prod is correct by construction:
`LP_DB_PATH=/root/legendarypicks/backend/data/picks.db python3 ingest_ufc_fight_stats.py --dry-run` first.
Cost ≈ 26 fighters × ≤5 fights — minutes, **not** the heavy MLB backfill.
Correction to Micah's phrasing: we *do* have past fights — dev's UFC logs span **2021-01-20 → 2026-07-18**
across 6 seasons. What is card-scoped is *who is in the table*, not how far back their history goes.
**There is no UFC fight-stats timer for either env** (`systemctl list-timers` shows props, props-prod,
nfl-adp(-prod), nfl-transactions(-prod), mlb-capture — nothing UFC). Without one, the fighter page goes
empty again next card. That timer is the real fix.

**MLB — copy from dev, additive-merge only.** Natural key is `UNIQUE(league, source_player_key, season,
game_no)`. All **40,151** prod MLB rows have a dev counterpart. **32,065** rows gain exactly `R` + `RBI`
and nothing else. **4,773** dev-only rows to insert (2026-06-26 → 07-24); 2,016 of 2,019 player keys
resolve to prod `players.mlbam_id`.
**The trap — 51 rows genuinely conflict**: prod holds a *pitching* line where dev holds a *batting* line
under the same key (e.g. prod `{"K":0,"outs":3,"hits_allowed":0,...}` vs dev `{"H":1,...,"K":2,"RBI":2}`).
Two-way players or a `game_no` collision, unresolved. **Rule: only add keys absent from prod's blob,
never overwrite an existing key's value.** A blind `UPDATE stats = dev.stats` silently swaps 51 pitching
lines for batting lines.
**Prod is `journal_mode=delete`, not WAL** (dev is WAL) — a writer takes an exclusive lock, so do it as
one short transaction, not a slow loop. Back up to `picks.db.bak-premigrate-mlb-rbi-<ts>` first.
Verify through the **real endpoint** (`/api/props/history?player_id=…&market=total_hits,_runs_and_rbis`
on `:8100`), not a DB read — a hand-typed API param passed once while the real market string never fired.

## 6. Other open loose ends

- **No NFL pick surface exists.** Picks are esports + UFC only. Fantasy football is the stated focus and
  "made a pick in week N, came back in week N+1" is the activation metric — it **cannot measure NFL**.
  Still the most important unresolved product gap.
- `usage_trend_viewed` unwired (§2); merge-to-`dev` decision unmade.
- GitHub Action for the version guard — the pre-push hook is local to this box only; the repo has no CI
  at all. Offered, never built.
- Prod visitor figure "0–19 unique app-route visitors/day" is inherited from 07-25 and still not
  re-derived. GA4 will now answer this directly — check Realtime/Reports in a day or two.
- Still open and untouched from 07-25: `/strength` quality gate broken, `streams.py` decapi wobble,
  unexplained `state=live` with future start time, unexplored embed sources, Underdog fighter identity
  gap, Micah's unanswered Codex prompt.

## 7. Artifacts preserved from this session

`/root/lp-verify/` (copied out of the session scratchpad, which does not survive a reset):
`ga-verify.js` (GA4 dataLayer checker), `shot.js` (local screenshots), `shot-tunnel.js` (screenshot
through a tunnel with pinned DNS), `usage-mcbride.png`, `usage-shaheed.png`, `tunnel-mcbride.png`.
