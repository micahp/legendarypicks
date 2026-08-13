# REPORT — MLS draw rendering (task item [4]) — FOLLOW-UP fixes applied

Date: 2026-08-13 (v2, after Micah's follow-up review)
Branch: feat/league-mls-ncaaf @ /root/lp-league-mls-ncaaf
Scope-lock respected: touched ONLY the backend /api/mls/standings handler
(backend/routers/games.py) and the frontend standings table component
(components/Leagues/StandingsTab.tsx). NOT committed, NOT landed to main dev.

## 1. Backend — /api/mls/standings now emits draws + GF + GA + GD + Pts

Replaced the old mls branch (which called live ESPN `espn.group_standings`)
with `_mls_standings_from_db(season)`: a pure aggregation of the published
per-game rows in `team_game_results` for ONE explicit season, restricted to
status='completed'. No live ESPN call — DB-first, zero requests per pageview.

- P  = COUNT(*) of the publisher's own rows per team
- W/D/L = COUNT of result='W'/'D'/'L' (the publisher's own result values)
- GF/GA = SUM(score_for)/SUM(score_against) (the publisher's own scores)
- GD  = GF - GA
- Pts = 3*W + D (MLS's published 3/1/0 rule applied to published results)
- Conference membership + team display names are RECORDED VOCABULARY from
  ESPN's published /standings payload (measured 2026-08-12, site.web.api.espn.com)
  — team_game_results has no conference/name columns, and this is the
  espn-request-budget §7 recorded-vocabulary pattern (stable, publisher-measured,
  used at zero requests). Comment in code states the source and date.
- Sort: points desc, then wins, then GD, then GF (standard MLS tiebreakers);
  rank = row position in that order.

### Follow-up fix (1) — season + status filters, season as a parameter

The SQL now reads `WHERE league='mls' AND season = ? AND status = 'completed'`.
The season is NOT a magic literal: `_mls_standings_season()` derives it from
the canonical coverage record (`team_stats_coverage` mls/2025 complete),
falling back to `MAX(season)` in team_game_results. The handler 503s if the
DB has no mls rows at all. The query now does exactly what the docstring
claims, rather than "whatever happens to be in the table".

### Follow-up fix (2) — conference coverage assertion (fail loud both ways)

Before building rows, the handler compares the set of distinct mls teams in
the DB for that season/status against the union of the recorded conference
frozensets. Any difference raises a 503 NAMING the abbrevs:

- unmapped in DB (a team in neither frozenset) -> "unmapped abbrevs [ZZZ]"
- mapped but missing from DB (a conference team with no rows) -> "no rows for [PHI]"

Never a partial table with a 200. Both directions were exercised in a temp-DB
test (PASS 503 for unmapped; PASS 503 for missing). The old
`by_abbrev.get(team) -> continue` silent skip is gone — after the assertion
passes, every mapped team is guaranteed present, so the lookup is direct.

## 2. Reconciliation — the two numbers

- Draw rows in team_game_results: 256 (result='D')
- Total team-game rows: 1020 (510 games × 2 teams)
- 256 / 1020 = 25.1% of team-game rows are draws; 128 drawn matches (each
  draw match contributes 2 D rows).
- Every one of the 30 teams has P == W+D+L (34 == 34 for all). The handler
  raises 503 naming the team if this ever breaks — it never silently
  normalizes. Verified against the live endpoint: P != W+D+L teams: NONE.

## 3. Follow-up fix (3) — ONE-TIME reconcile against ESPN published standings

Probe: `https://site.web.api.espn.com/apis/v2/sports/soccer/usa.1/standings?season=2025`
(2 requests, one for shape + one for the payload, cached). Note: the bare
/standings endpoint serves the CURRENT 2026 in-progress season (CHI played=17);
the ?season=2025 variant serves the completed season we hold — that is the
apples-to-apples comparison.

Comparison (per team, all of P/W/D/L/GF/GA/GD/Pts AND rank):
- AGREE: 30 of 30 teams (all fields + per-conference rank identical)
- DISAGREE: none
- Our numbers were NOT adjusted to match; they already matched. If any team had
  disagreed, the disagreement would be reported here and our numbers left as-is.

Full agree list: ATL ATX CHI CIN CLB CLT COL DAL DC HOU LA LAFC MIA MIN MTL
NE NSH NYC ORL PHI POR RBNY RSL SD SEA SJ SKC STL TOR VAN.

### Evidence provenance (falsifiable)

- **Raw publisher payload (unmodified):** `render-evidence/espn-mls-2025-standings-raw.json`
  - Exact URL: `https://site.web.api.espn.com/apis/v2/sports/soccer/usa.1/standings?season=2025`
  - Fetch timestamp: 2026-08-13T23:12:48Z
  - Byte size: 134,794 bytes (HTTP 200)
  - Contains the publisher's own vocabulary (`gamesPlayed`, `ties`,
    `pointsFor`, `pointsAgainst`, `pointDifferential`, `points`) — it is the
    response body as received, not normalised into our row shape.
- **Reconcile result:** `render-evidence/mls-reconcile-result.json` — the
  agree/disagree list keyed by abbrev (30 agree, 0 disagree), produced by
  diffing the raw payload against our `/api/mls/standings` output.
- **Normalised derivatives (labelled as such, NOT publisher payloads):**
  - `render-evidence/espn-mls-2025-standings-normalised-derivative.json` —
    ESPN 2025 rows re-shaped into our {rank, abbrev, played, wins, draws, ...}
    row object (what the comparison code consumed).
  - `render-evidence/mls-standings-raw-normalised-derivative.json` — our
    endpoint's output for the same season (the DB-derived side of the diff).
- To reproduce: fetch the URL above (curl -A Mozilla), re-derive the
  comparison, and diff against render-evidence/mls-reconcile-result.json.

## 4. Frontend — isSoccer branch, not mls-in-isWorldCup

StandingsTab.tsx now derives `const isSoccer = league === 'mls'` and renders
the soccer P W D L GF GA GD Pts table via that branch. The World Cup keeps
its own branch (knockout bracket / group tables). MLS is NOT bolted onto the
isWorldCup condition; a future soccer league (EPL) extends isSoccer without
touching the WC path.

## 5. result=D migration

Already present on the worktree DB (/root/lp-league-mls-ncaaf/backend/data/
picks.dev.db): team_game_results has the `result TEXT CHECK (IN ('W','D','L'))`
column populated — 256 D, 382 W, 382 L. Nothing to migrate; stated per task.

## 6. Evidence

Raw /api/mls/standings JSON (one team with a draw — Philadelphia Union,
D=6):
```
{"rank":1,"abbrev":"PHI","name":"Philadelphia Union","played":34,"wins":20,
 "draws":6,"losses":8,"gf":57,"ga":35,"gd":22,"points":66}
```
Full payload saved: render-evidence/mls-standings-raw.json (10.8 KB).

Browser renders (branch frontend :3098 -> branch backend :8098, both against
the worktree DB copy; backend restarted AFTER the follow-up edits so the live
endpoint reflects the filtered + asserted code):
- 1440px: render-evidence/mls-standings-1440px.png — re-shot at a GENUINE
  1440px viewport (verified PNG size 1440x900, iframe frameWidth=1440,
  scrollW=1425 < frame so no truncation). Eastern + Western tables, D column
  populated (PHI 6, CIN 5, MIA 8, CLB 12, ...), GD color-coded, PTS visible.
  (The v1 PNG was 1265px wide — the headless browser's default 1280 viewport
  minus scrollbar; replaced, not relabeled.)
- 375px: render-evidence/mls-standings-375px.png — true mobile viewport via a
  375x812 iframe (headless browser cannot resize its own viewport; iframe
  verified at getBoundingClientRect width=375, left=0, top=0; PNG cropped to
  the iframe region = 375x812). Both conference tables render; D column
  populated (PHI W=20 D=6 verified from the DOM); table scrolls horizontally
  inside its overflow-x-auto container (never degrades to key-value pairs —
  documented mobile behavior; GD/PTS sit beyond the 375px fold, scrollable).

## 7. Tests

- backend/test_leagues_hub_assertions.py — ALL ASSERTIONS PASSED (mls
  standings shape: 2 groups Eastern/Western, all 11 row keys present).
- test_coverage_gate.py + test_audit_league_stats.py + test_ingest_mlb_
  counting_stats.py + test_ingest_nba_season_stats.py — 72 passed.
- jest components/Leagues (InjuryTag, presentation) — 10 passed.
- git diff --check — clean.
- Temp-DB fail-loud tests: PASS 503 unmapped [ZZZ]; PASS 503 missing [PHI].
- Regression: /api/nba/standings still flat team_strength list (30 rows,
  no group key) — untouched path.

## 8. What I did NOT do (per instructions)

- No commit, no push, no landing to main dev.
- Did not touch audit_league_stats.py, host config, canonical dev DB
  (/root/legendarypicks/backend/data/picks.dev.db is untouched; worktree DB
  copy is a real file, not a symlink).
- Only the two scoped files changed: backend/routers/games.py (mls standings
  hunk only; pre-existing EWC hunks in that file were already uncommitted
  before this task), components/Leagues/StandingsTab.tsx.

## 9. Still red / pre-existing (NOT part of this task)

- mls C/vocabulary[position] — two levels in one column (AM under M, ...);
  needs the position_group split pattern (same class as ncaaf C/vocab).
- mls B/position-content[GK] — no GK game logs (keeper saves/minutes unmapped).
- mls E/qualifier[season], mls G/published-identity — pre-existing manifest items.
- The game-log and momentum draw surfaces were not in scope (task item [4]
  scope-lock: standings handler + standings table component only).
- Soccer-native team stat columns (shots_on_target, possession, corners) —
  no schema column yet (documented gap, unchanged).

## 10. Servers left running (branch preview)

- backend: 127.0.0.1:8098 (LP_DB_PATH -> worktree DB copy; running the
  post-fix code)
- frontend: 127.0.0.1:3098 (API_PROXY_TARGET -> :8098)
- URL: http://127.0.0.1:3098/leagues/mls (Standings tab)
