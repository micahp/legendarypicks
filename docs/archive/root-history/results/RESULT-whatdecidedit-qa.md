# RESULT — QA: "What decided it" panel (`leaders` on `/api/game/{league}/{game_id}/props`)

- **Date:** 2026-08-11
- **Base URL verified:** `https://resume-stress-education-pros.trycloudflare.com` (confirmed the
  props endpoint contains the `leaders` key before starting; did NOT use
  `coat-develop-rooms-prague.trycloudflare.com`)
- **Type:** READ-ONLY QA. No code edited, no server restarted, no DB written.

## 1. Games checked

**106 games total, all `mlb`** (MLB has the settled props; the `nfl`, `nhl`, and `nba`
scoreboards returned empty lists on every date probed in 2026-07-20..2026-08-10 — those leagues
have no games in that window).

By state:
- `post` (final): **96** games — sampled 8 per date across **12 dates**
  (2026-07-20, 07-22, 07-24, 07-26, 07-28, 07-30, 08-01, 08-03, 08-05, 08-07, 08-09, 08-10).
  Of these, 82 had `len(leaders) > 0` and 14 had no settled props (`leaders == []`,
  `settled_lines == 0`).
- `pre` (not started): **10** games (2026-08-11 slate) — all returned `leaders == []` and
  `settled_lines == 0`. No `in` games were present in the sampled windows.

Requirement check: ≥25 post games across ≥3 dates (96 across 12 dates ✓), ≥5 non-final games
(10 pre ✓).

## 2. Failed assertions

**None.** All 11 assertions passed on all 106 games:

| Assertion | Result |
|---|---|
| A1 leaders present and a list | PASS |
| A2 len(leaders) <= 3 | PASS (max observed 3) |
| A3 no settled props / not-started -> empty | PASS (14 no-settled post games -> `[]`/`0`; 10 pre games -> `[]`/`0`) |
| A4 sorted by margin descending | PASS |
| A5 margin == abs(actual - line) within 0.001 | PASS |
| A6 cashed exactly over/under | PASS |
| A7 cashed agrees with actual vs line | PASS |
| A8 leader corresponds to real settled prop in same response | PASS (every leader found in `players` with matching player_id/market/line and non-null result) |
| A9 no blank name/team | PASS |
| A10 unique on (player_id, market, line) | PASS |
| A11 settled_lines >= len(leaders) | PASS |

No failed assertion table needed — the table is empty by construction.

## 3. Evidence — raw `leaders` JSON for 3 different games

**Game 1: mlb 401816457 (WSH vs BOS area) — settled_lines 48**

```json
[
  {"player_id": 28860, "name": "Abimelec Ortiz", "team": "WSH", "market": "total_bases", "line": 1.5, "actual": 5.0, "cashed": "over", "margin": 3.5},
  {"player_id": 33, "name": "Keibert Ruiz", "team": "WSH", "market": "total_hits,_runs_and_rbis", "line": 1.5, "actual": 5.0, "cashed": "over", "margin": 3.5},
  {"player_id": 28860, "name": "Abimelec Ortiz", "team": "WSH", "market": "total_hits,_runs_and_rbis", "line": 1.5, "actual": 4.0, "cashed": "over", "margin": 2.5}
]
```

**Game 2: mlb 401816188 — settled_lines 35**

```json
[
  {"player_id": 29872, "name": "Petey Halpin", "team": "CLE", "market": "total_hits,_runs_and_rbis", "line": 0.5, "actual": 9.0, "cashed": "over", "margin": 8.5},
  {"player_id": 29871, "name": "Patrick Bailey", "team": "CLE", "market": "total_hits,_runs_and_rbis", "line": 0.5, "actual": 8.0, "cashed": "over", "margin": 7.5},
  {"player_id": 28110, "name": "Joe Ryan", "team": "MIN", "market": "hits_allowed", "line": 4.5, "actual": 10.0, "cashed": "over", "margin": 5.5}
]
```

**Game 3: mlb 401901849 — settled_lines 0 (no settled props)**

```json
[]
```

## 4. Sports-fan review (leaders that looked wrong even though assertions passed)

None that were obviously wrong. Spot checks across 10 additional games (401816187, 401816189,
401816191, 401816186, 401816195, 401816196, 401816190, 401816465, 401816469, 401816461) all
produced leaders that match what a fan would call "what decided it": e.g. Mookie Betts 10 total
bases (line 1.5), Trea Turner 10 total bases, Braxton Ashcraft 9 outs vs 17.5 line, Jazz
Chisholm 9 HR+RBIs+R runs. Pitcher lines (outs, hits allowed, strikeouts) are the furthest-margin
lines in some games, which is a legitimate reading of "finished furthest from their own number"
— the panel's stated contract — even if a fan might instead expect a batter highlight. That is a
design interpretation, not a data defect.

One data-quality note (not an assertion failure, and not this panel's bug): the prop `name`
field mixes casing (`"jazz chisholm"`, `"willson contreras"`, `"ian happ"` vs `"Mookie Betts"`,
`"Trea Turner"`) — cosmetic inconsistency coming from the upstream prop data, not from the
`leaders` computation. A8 confirms the leaders themselves match real players.

## 5. Environment note

The scoreboard endpoint (`/api/{league}/games?date=...`) returned intermittent HTTP 500s during
the sweep (both through the tunnel and directly on the local dev backend); retries with backoff
recovered every date. The props endpoint (the subject of this QA) was consistently healthy.
