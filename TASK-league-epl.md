# TASK league-epl — add the Premier League: split-year seasons and a team set that changes

**Owner: Hermes. Backend + frontend. Depends on `TASK-league-0-coverage-gate.md` and
`TASK-league-mls.md`.** MLS builds the soccer scaffolding (draws, soccer game log,
soccer standings, season-type-driven ingest). This task should be **small** — if it is
not, the MLS work generalised badly and that is the thing to fix.

Read `docs/DATA-COVERAGE-CONTRACT.md` §6 and §7 first.

**Skills — load before coding:**

| skill | when |
|---|---|
| `.claude/skills/published-first/SKILL.md` | before the ingest. Two rung-5 traps here: the season key and the team set. Both are published. Both look derivable. |
| `.claude/skills/honest-data-ui/SKILL.md` | before §3. A relegated team's history is the sharpest version of "absence is a claim about the player, not about us". |
| `.claude/skills/resource-check/SKILL.md` | before the ingest run. |

---

## 1. Shape — measured 2026-08-02

`soccer/leagues/eng.1`, **26 seasons published**.

```
GET seasons/2025  ->  one type, id 1, displayName "2025-26 English Premier League"
                      380 matches, 20 teams
```

Three things EPL adds on top of MLS:

1. **The season spans two calendar years and ESPN keys it by the start year.** Season
   `2025` runs Aug 2025 → May 2026. A match played 2026-01-14 belongs to season **2025**.
   `ingest_wc_logs.py` derived the key as `int(game_date[:4])`; on this league that
   silently files half the season under `2026`, where it will reconcile against the wrong
   published total and read as a gap in one season and a surplus in another. **MLS
   should already have removed that line** — verify it is gone before you start.
   And do not generalise the fix either way: NBA and NHL key by the year the season
   *ends*, NFL and EPL by the year it starts. Read `startDate`/`endDate`.
2. **380 = 20 × 19 × 2, and it is stable** — the one league here with a real constant.
   Use it as a sanity check on the published count, never as a substitute for it.
3. **3 teams relegated and 3 promoted every season.** A team's membership of this league
   is a **season-scoped fact**, not a league-scoped one. Any query shaped
   `WHERE league='epl'` and joined to a current team list will silently drop a relegated
   team's history — the miss will not raise, exactly like the `LAR`/`LA` join key
   (`reference_lp_team_code_vocabularies`). Team sets come from
   `seasons/<year>/types/1/teams`, per season.

---

## 2. Backend — files you may touch

**`backend/espn_leagues.py`** — add `epl: {"path": "soccer/leagues/eng.1", ...}`.

**`backend/ingest_soccer_logs.py`** (created by TASK-league-mls) — add EPL. If this needs
more than a registry entry and a season-key argument, stop and fix the generalisation
rather than branching on `league == 'epl'`.

**`backend/reconcile_totals.py`** — EPL checks. The season-scoped team set is the
important one: assert our distinct teams for `epl <season>` equals the published
`types/1/teams` count for **that** season, not a league-wide list.

**Team-code vocabulary** — normalise to ESPN's at the ingest boundary and nowhere else.
Do not add a hand-maintained EPL abbreviation map; ESPN publishes `abbreviation` per team
per season, including for teams that were in the Championship last year.

**Do not touch:** `ingest_nfl_*.py`, `ingest_ncaaf_logs.py`, `ingest_wc_logs.py`,
`backfill_team_parity.py` beyond what MLS already changed, `/etc`, systemd, cron.

---

## 3. Frontend — files you may touch

Most of it should already work from MLS. EPL-specific:

- **Season labels.** Every picker and header shows ESPN's `displayName`
  — *"2025-26 English Premier League"* — not `2025` and not a composed `2025-26`. A
  season the user sees as "2025-26" keyed internally as `2025` is a live footgun; label
  from the published string everywhere.
  Files: `components/Leagues/StatsTab.tsx`, `pages/stats.tsx`,
  `components/Leagues/StandingsTab.tsx`, `components/Leagues/ScheduleTab.tsx`.
- **`components/Leagues/PlayerDetailOverlay.tsx` and `PlayerGameLog.tsx`** — a player at
  a relegated club has a genuine hole in his EPL record: he was playing, in another
  competition, and we have no rows. That is **`unknown`, not `missed`** (contract §2).
  This is the case that proves the third state is doing real work; if it renders amber,
  the state machine is wrong. **Find such a player and screenshot him.**
- **`components/Leagues/presentation.ts`** — `LEAGUE_NAMES.epl = 'Premier League'`,
  `LEAGUE_EMOJIS.epl = '⚽'`.

**Do not touch:** `components/MockDraft/*`, any `Nfl*.tsx`.

---

## 4. Done means

1. Coverage row for `epl 2025` = `complete`, written by
   `reconcile_totals.py --write-coverage`; `expected_games` reads **380**.
2. `reconcile_totals.py --league epl --season 2025` exits 0; output and exit code pasted.
3. A match played in **January 2026** confirmed by query to carry `season = 2025`. One
   SQL statement, in the PR body. This is the defect most likely to ship unnoticed.
4. The distinct-teams check passes for **two different seasons** whose team sets differ —
   proving membership is season-scoped and not a league-wide list.
5. The relegated-player screenshot from §3, next to a player with a genuine missed match.
   **If they look the same, the work is not done.**
6. `git diff --stat` matches the file list above.
