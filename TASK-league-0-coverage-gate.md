# TASK league-0 — make the coverage registry capable of saying no

> **STATUS 2026-08-02: DONE, by Claude, not Hermes.** Kept as the record of what was
> found and what the gates are. Two things turned up that were not in the original
> spec and matter to the three league tasks:
>
> 1. **A second silent game-loss**, unrelated to the transaction bug: a POSTPONED game
>    is `state="post"` with a score of **`0`, not null**, so it passed both of
>    `enumerate_games()`'s filters and would have been written as a played 0–0 result.
>    The filter now reads `completed`. §9 of the contract has it. **Any new league's
>    ingest must filter on `completed`.**
> 2. **`published_real_games()` was replaced by `explain_gap()`**, which diffs the
>    published event-id set against ours and classifies only the difference — cost
>    scales with the size of the gap, not the season. New leagues get gap
>    classification for free; do not write a per-league variant.

**Owner: Hermes. Backend + frontend. This blocks NCAAF, MLS and EPL — do it first.**

Read `docs/DATA-COVERAGE-CONTRACT.md` §4 and §9 before writing a line. §9 is the
measurement this task exists to answer; everything below is reproducible from it.

**Skills — load before coding, not after:**

| skill | when |
|---|---|
| `.claude/skills/published-first/SKILL.md` | before touching the coverage writer. §6 is the whole mechanism; rung 1 ("does this value need to exist") is why you extend `team_stats_coverage` instead of building a second registry. |
| `.claude/skills/honest-data-ui/SKILL.md` | before §4 of this task. The registry decides what the UI is allowed to offer; §4 of that skill (LP-specific bans) governs how a suppressed league reads. |
| `.claude/skills/resource-check/SKILL.md` | before the re-run in §3. It is 1,231 NBA + 1,312 NHL summary fetches against a rate-limiting host on a box with a live dev server. |

---

## 1. The finding

Three defects, one cause. `backend/backfill_team_parity.py:run_league()` ends with:

```python
status = "complete" if fetched_teams == expected else "partial"
...
fetched_teams, games_written, games_written, games_written, games_written,
0,
```

1. **`expected_games` is `games_written`.** So are `fetched_games`, `paired_games` and
   `paired_stat_games`. Four columns, one variable — the expectation is a restatement of
   the result and cannot disagree with it.
2. **`failure_count` is the literal `0`**, written by the same function that had just
   inserted four failure rows into `team_stats_ingestion_failures` for that run_id.
3. **`status` is a claim about teams.** 30 of 30 appeared, so `complete` — while four
   games were missing.

The four missing NBA games (and one NHL game) are in the failures table with an exact
reason, dated `2026-07-14`:

```
write: cannot start a transaction within a transaction
```

`run_league()` calls `con.execute("BEGIN")` on a connection in sqlite3's default implicit
transaction mode. When a prior statement already opened one, `BEGIN` raises, the `except`
records the failure, and the loop continues. 4 of 1,231 — sporadic enough to look like
nothing.

**Reproduce before you start:**

```bash
sqlite3 backend/data/picks.dev.db "
  SELECT run_id, game_id, reason FROM team_stats_ingestion_failures;
  SELECT league, status, expected_games, fetched_games, failure_count
    FROM team_stats_coverage;"
```

You should see 5 failure rows and 3 rows claiming `failure_count=0`.

---

## 2. Backend — files you may touch

**`backend/backfill_team_parity.py`**

- Open the connection with `isolation_level=None` and keep the explicit
  `BEGIN`/`ROLLBACK`, **or** drop both and rely on the context manager. Either is fine;
  what is not fine is the current mix. Add a regression test that writes two games
  through the same connection with a statement already in flight.
- Delete the coverage `INSERT` entirely. It moves to `reconcile_totals.py` (§3). This
  script's job is to write game rows and record its failures — it is not in a position to
  judge its own completeness, which is the whole lesson of §9.

**`backend/reconcile_totals.py`** — becomes the only writer of `team_stats_coverage`.

- New `--write-coverage` flag. Default off; the script stays read-only unless asked.
- `expected_games` from `published_count()`, one request. `fetched_games`,
  `paired_games`, `paired_stat_games` each from their own `SELECT`.
- `failure_count` from
  `SELECT COUNT(*) FROM team_stats_ingestion_failures WHERE run_id=?`.
- `status`:
  - `complete` — every count equals its published total, `failure_count = 0`, and no
    check hit `OracleUnreachable`.
  - `partial` — a count disagrees, or failures were recorded.
  - `unverified` — any oracle was unreachable. **Never infer `complete` from a missing
    oracle.** No row at all also means `unverified`; that is the frontend's default.
- Add the columns §4 of the contract calls for: `expected_players`, `fetched_players`,
  `null_key_rows` (rows with NULL `game_type`, `team` or `game_id`). Migration goes in
  `backend/team_stats_schema.py`, which already owns this table's DDL.
- **`published_real_games()` currently assumes exhibitions live in the postseason type**
  — true for the NFL Pro Bowl, false for NBA All-Star, which ESPN files under type 2.
  Stop passing the type id in; classify from the event's
  `competitions[].type.abbreviation == "ALLSTAR"`, which is where the answer already is,
  and call it on every type whose headline count disagrees.
- Keep the `?limit=1` pacing and cache. ESPN 403s a burst with no `Retry-After`.

**`backend/routers/games.py`** — one new route, `GET /api/coverage`:

```json
[{ "league": "nba", "season": 2026, "status": "complete",
   "display_name": "2025-26 NBA", "season_start": "...", "season_end": "...",
   "expected_games": 1231, "fetched_games": 1231 }]
```

Return **every** row including `partial` and `unverified` — the client needs to know a
league exists and is not offerable, which is different from not existing. `display_name`
is ESPN's published `displayName`, stored at ingest, never composed client-side.

**Do not touch:** `backend/_core.py`, `espn_client.py`, `sports_service.py`, any
`ingest_*.py`, anything under `/etc`, systemd, or cron.

---

## 3. Prove it on the case that produced it

```bash
# resource-check first — this is ~2,500 paced HTTP calls
LP_DB_PATH=backend/data/picks.dev.db python3 backend/backfill_team_parity.py --league nba
LP_DB_PATH=backend/data/picks.dev.db python3 backend/reconcile_totals.py \
    --league nba --season 2026 --write-coverage
```

Expected values — **write these into a test before you run it**, per
`feedback_fix_gates_before_the_code`:

- `team_game_results` for `nba 2026` = **1231** distinct game_ids (1227 + the 4 in §9).
- Per-team counts: **82 for 28 teams, 83 for NY and SA** (the NBA Cup finalists; the
  final is played but does not count toward 82). Zero teams at 80 or 81.
- `team_stats_ingestion_failures` for the new run_id = **0 rows**.
- The coverage row reads `expected_games=1231, fetched_games=1231, failure_count=0,
  status='complete'`.
- NHL 2026: `team_game_results` and `player_game_logs` agree at **1312**.

`reconcile_totals.py --league nba` must still reconcile 1,239 published against 1,231
ours **and pass**, because 4 All-Star events and 4 postponed shells are definitional —
see the arithmetic in §9. If it reports a mismatch, the exhibition-classification change
is wrong, not the data.

---

## 4. Frontend — the registry becomes the whitelist

Today `components/Leagues/presentation.ts` hardcodes the league list:

```ts
export const LEAGUE_SWITCHER = ['mlb', 'nba', 'nhl', 'nfl', 'wc', 'ufc'] as const
```

and `components/Leagues/hooks/useLeagueRouteState.ts:15` hardcodes
`supportsTeamStats = ['mlb','nba','nhl','nfl']`. Every league added after this task would
mean editing both by hand and hoping they agree with the data. **They become derived.**

- New `components/Leagues/hooks/useCoverage.ts` — fetches `/api/coverage` once, caches.
- `LEAGUE_SWITCHER` is built from rows with `status='complete'`. `LEAGUE_NAMES` and
  `LEAGUE_EMOJIS` stay as the presentation layer (an emoji is not published), but a
  league with no entry there falls back to its uppercased slug rather than vanishing.
- `supportsTeamStats` = "has a `team_stats_coverage` row for the active season" — the
  literal array goes.
- `pages/leagues/[league].tsx` — a league that is `partial`/`unverified`/absent renders a
  quiet "not available yet" state. **Quiet.** Per `honest-data-ui` §4, our gap is not
  information about the sport and must not carry the amber accent, which belongs to the
  player-availability thesis.
- A season that is not `complete` is **never the default** in any season picker.

**Do not touch:** `components/Leagues/PlayerGameLog.tsx`, `StatsTab.tsx`,
`StandingsTab.tsx` or anything under `components/MockDraft/`. The three-state row work is
a separate task; this one only decides what is *offered*.

---

## 5. Done means

1. `python3 -m pytest backend/test_team_stats_contract.py backend/test_migrate_team_stats.py`
   green, plus the new regression tests.
2. The §3 expected values reproduced from a fresh run, pasted into the PR body as
   command + output, exit codes included.
3. `npm run build` clean, and the league hub opened **in a browser** on `nba` and on a
   league with no coverage row — screenshot both. A 200 is not a render
   (`feedback_a_green_gate_is_a_claim_about_its_surface`).
4. `git status` clean of stray files; one commit per logical slice
   (`feedback_separate_commits_per_slice`).
5. `git diff --stat` reviewed against the file list above. Anything outside it is out of
   scope and gets reverted.
