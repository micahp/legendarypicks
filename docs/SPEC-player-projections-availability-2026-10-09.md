# SPEC B: availability-aware player shares, player stat projections, and "without player X" prop history

Author intent (Micah, 2026-10-09): player shares and props must be injury and availability aware.
Copy props.cash's filter: prop history without a given player. Replace the values we copied from
ESPN with our own projections, keeping ESPN's as a benchmark. Player projections feed team
projections (SPEC A), which feed playoff odds. Everything graded in public.

Companion: `docs/SPEC-nfl-team-ratings-playoff-odds-2026-10-09.md` (SPEC A). Method reference:
`docs/PROJECTIONS-METHODOLOGY.md` (the 8-step pipeline: baseline, regression per stat, aging,
volume model, efficiency, matchup, distribution, derived fantasy). Section 0 of SPEC A (rules for
whoever builds this) applies here word for word: load `.claude/skills/` first, dev DB only, own
worktree (`git worktree add ../lp-player-proj -b feat/player-projections-availability dev`), one
commit per slice, published-first, unknown is never guessed, paste raw output.

NFL first. Every table carries a `league` column so NBA (minutes) and NHL (TOI) follow the same
shape.

2026-10-10 product direction: [the forecasting north star](STRATEGY-forecasting-north-star-2026-10-10.md)
connects these player forecasts to the game's shared score simulation and the
season forecast in Spec A. Full Spec B means B0–B8, including the prop filter,
our own player probabilities, injury scenarios and public grading. The B1–B3
candidate is isolated pending review fixes as of this note.

---

## 1. What exists today (measured 2026-10-09)

| Thing | State |
|---|---|
| `player_game_logs` NFL | 2025: 19,399 rows (nflverse weekly). 2026: 4,445 rows, 64 games, weeks 1-4, **`game_date` empty on all 4,445**. |
| `player_team_shares` NFL 2026 | Through week 4. Metrics: targets 366 rows, air_yards 355, carries 194, scrimmage_td 180, rec_td 128, rush_td 62. Season-to-date sums (`backend/build_player_shares.py`); no per-game shares, no availability. |
| `nfl_snap_counts` (`ingest_nfl_snap_counts.py`) | **2025 only (20,627 rows). 2026 never ingested.** |
| Injury reports | **No table.** `players.injury_status` holds only the current ESPN status (OUT 54, DOUBTFUL 11, QUESTIONABLE 355, IR 240, ...), no history. |
| `nfl_depth_chart` | 945 rows, 2026, nflverse, snapshot 10-05. |
| `nfl_player_projections` | 11,515 rows: ESPN season-long projections (`scoring_period_id = 0`), from `ingest_nfl_projections.py`. Not ours. |
| Our engine | `backend/analytics/projections.py` ("Marcel-lite": recency-weighted mean of the player's own logs + percentiles + P(over)); API `GET /api/projections/player/{player_id}`. No volume model, no team constraint, never graded. |
| Props | `props` 499,039 rows, `prop_results` 392,381 settled. History routes: `GET /api/props/player/{player_id}/history` and `GET /api/props/history` (`backend/routers/props.py`). |

**Rule from experience (`reference_lp_game_logs_are_touches_not_presence`):** a game log row means
the player recorded a stat, not that he played. A blocking tight end with zero catches has no row.
Presence comes from snap counts, never from logs.

---

## 2. Availability layer (build first)

### B0. Data fixes
1. **Fill `game_date` on 2026 NFL logs.** Join on the published schedule (`nfl_schedule`, by season,
   week and team/opponent; or by `game_id` if the log carries the nflverse game id). No date may be
   inferred another way. Reconcile: 4,445 rows before, 4,445 after, 0 empty dates. Fix the ingest so
   new rows arrive with dates (find why they are empty; do not just backfill).
2. **Ingest 2026 snap counts** with the existing `ingest_nfl_snap_counts.py` (nflverse `snap_counts`,
   published from PFR). Reconcile row count against the publisher's file for 2026. Weekly timer
   (`OnCalendar`, Tuesday 09:30 America/Chicago, after the schedule ingest).
3. **Ingest injury reports:** new `ingest_nfl_injuries.py` from the nflverse `injuries` release
   (weekly report: practice status by day, final `report_status` Out / Doubtful / Questionable,
   `report_primary_injury`). Table `injury_reports(league, season, week, team, player_id, gsis_id,
   report_status, practice_status, primary_injury, date_modified, source, ingested_at)`. Resolve
   players by id through the identity spine (`docs/SPEC-player-identity-spine.md`), never by name.
   Unresolved rows go to `unresolved_players` and are counted in the report.

### B1. `player_game_availability` (the presence fact)
One row per (team game, rostered player who appears in snaps, logs or the injury report):

    player_game_availability(league, season, week, game_id, team, player_id,
        played,            -- 1 = any offensive, defensive or special-teams snap; 0 = no snaps
                           --   and the game is final; NULL = unknown
        off_snaps, off_pct, def_snaps, def_pct, st_snaps,
        report_status,     -- final injury report status, NULL if not on the report
        reason,            -- 'injury_out', 'inactive_no_report', 'played', 'unknown'
        source, built_at)

- `played` comes from snap counts only. A player on the roster with no snap row in a final game is
  `played = 0` only if the snap file for that game is complete (row count for the game matches the
  publisher); otherwise `NULL`.
- Pregame (future games): `played` is NULL; `report_status` carries the final injury report.
  Out = expected out. Doubtful = expected out for projections (flag it). Questionable = unknown,
  projected both ways (section 4.4). ESPN `players.injury_status` is a live overlay for news after
  the Friday report, recorded with its timestamp, never overwriting the report.

### B2. Per-game shares (published-first)
nflverse weekly publishes `target_share` and `air_yards_share` per player per game. **Copy them**;
compute carry share per game from published carries over published team carries only if no
published per-game carry share exists (check first, say which in the report). Table
`player_game_shares(league, season, week, game_id, team, player_id, metric, share, player_value,
team_value, source)`. The existing season table `player_team_shares` stays; it is rebuilt from the
per-game table so the two cannot disagree.

### B3. With/without splits
For a player P and a teammate X: P's per-game shares and stats split into games where X
`played = 1` and games where X `played = 0`. Games where X is `NULL` are excluded from both and
counted. API function `splits(player_id, without=[x...], with=[...], season=None)` returning per-game
rows plus the counts excluded as unknown. This one function serves both the projection engine
(section 4.3) and the prop filter (section 3).

---

## 3. "Without player X" prop history (the props.cash feature)

### 3.1 Backend
- Add `without` (comma-separated player ids, teammates) and `with` to both history routes:
  `GET /api/props/player/{player_id}/history?market=&without=123,456` and
  `GET /api/props/history?...&without=123`.
- Filtering: keep only props whose game is one where every `without` player had `played = 0`
  (from `player_game_availability`), and every `with` player had `played = 1`. Games with unknown
  availability for a filter player are excluded and counted.
- Response adds: `filter: {without: [...], with: [...]}`, `n_games`, `n_excluded_unknown`, and the
  hit rates recomputed on the filtered set: last 5, last 10, last 20 settled, season. Existing fields
  keep their meaning when no filter is passed (existing tests must pass unchanged).
- Reuse `splits()` from B3; no second implementation of "did X play".

### 3.2 Frontend
- In the props player panel (`pages/props.tsx` and `components/Props/*`; `PropChart.tsx` shows the
  per-game history): a "Without" control listing the player's teammates who missed at least one game
  this season (from availability), as chips. Selecting one refilters the chart and hit rates.
- Show the sample on the control: "Without Mike Evans: 3 games". Under 5 games, say so in plain
  text ("small sample"). Excluded-unknown games are stated, not hidden.
- Follow the league-card design language and `honest-data-ui`. The URL carries the filter
  (`?without=123`) so a view can be shared.

### 3.3 Acceptance
- A test with a fixture team: player P, teammate X missed weeks 2 and 4; `without=X` returns exactly
  P's week 2 and 4 props with recomputed hit rates; an unknown week is excluded and counted.
- On real data: pick one 2025 case where a WR1 missed games; paste the API output with and without
  the filter and the games it kept.

---

## 4. Player projections, version 2 (replaces Marcel-lite for NFL)

Volume times efficiency, constrained to the team (`PROJECTIONS-METHODOLOGY.md` step 4: volume is
about 70% of the signal).

### 4.1 Team volume (from SPEC A, or a stub until SPEC A ships)
For each team-game: projected offensive plays and pass rate. Version 1: plays = blend of the two
teams' season plays per game (team's own offense and opponent's defense allowed), regressed to the
league mean; pass rate = team neutral-situation pass rate regressed to league. When SPEC A ships,
adjust plays and pass rate by projected game script (projected margin from SPEC A: favourites run
more). Projected team pass attempts and rush attempts follow.

### 4.2 Player volume
- Target share, carry share, red-zone share per player: recency-weighted per-game shares (B2),
  **only over games the player played** (B1), regressed toward the player's role prior (depth-chart
  rank from `nfl_depth_chart` and last season's share).
- **Constraint:** within each team and metric, projected shares of available players sum to 1.0
  minus a small "other" bucket fitted from history. Normalize after redistribution.

### 4.3 Availability: redistribution when a player is out
When a player is projected out (B1 pregame rules), his share is removed and redistributed:
1. If the remaining players have at least 3 games together without him this season or last (B3),
   use their observed shares in those games.
2. Otherwise, redistribute proportionally to remaining same-position-group players' shares, with
   the depth-chart next-man-up taking the larger part (fit the split from 2024-2025 cases where a
   starter missed games; report the fitted rule).
This is Micah's "scoring concentration x absence" idea as an explicit term
(`project_scoring_concentration_x_absence`): the touchdowns of an absent receiver go somewhere, and
the model says where.

### 4.4 Questionable players
Project both ways (plays / does not play) and publish both, plus a blended line weighted by a
fitted P(plays | questionable) from 2024-2025 injury reports and snap counts. Report the fitted
rate.

### 4.5 Efficiency and distributions
- Per player per stat: yards per target, catch rate, yards per carry, TD per opportunity. Regress
  each toward the position mean with stabilization constants fitted from 2024-2025 (efficiency stats
  regress hard, volume barely; report each constant).
- Stat line = volume x efficiency. Distribution: simulate (negative binomial for counts, empirical
  residuals for yards) to give mean, median, 10th/90th percentiles and P(over line) for any line.
- Fantasy points derived from the stat line, never projected directly.

### 4.6 Team consistency (feeds SPEC A version 2)
Sum of projected player receiving and rushing yards and touchdowns per team must be consistent with
the team's projected points (SPEC A). Report the gap per team per week; do not force it in version
2, measure it first.

---

## 5. Grading (public)

Weekly, after each week's games are final:
- Per stat (pass yds, rush yds, rec yds, receptions, TDs, fantasy points): mean absolute error and
  bias of our projection, and of **ESPN's projection for the same player-week** (benchmark). Extend
  `ingest_nfl_projections.py` to also capture ESPN's weekly projections (`scoring_period_id = week`)
  before kickoff, respecting the `espn-request-budget` skill; store them as `source = espn` beside
  ours. Season-long ESPN rows stay as they are.
- Props: for every settled prop with a line, our P(over) graded by Brier and calibration bins, and
  the hit rate of "our side" when our probability differs from the implied odds by more than 5 points.
- Page: a "Projection record" panel next to SPEC A's model record: our error vs ESPN's per stat, per
  week, losses included.

Gate (falsify-before-merge): on a 2025 walk-forward backtest (weeks 3-18), our version 2 must have
lower mean absolute error than Marcel-lite on receiving yards and receptions, and the report must
show ours versus ESPN's where ESPN weekly 2025 projections are available. If ESPN's are not
retrievable for 2025, say so and grade against ESPN from 2026 week 6 onward.

---

## 6. Storage, jobs, API

- Migration `backend/migrate_player_projection_tables.py` (idempotent): `injury_reports`,
  `player_game_availability`, `player_game_shares`, `player_projections(run_id, league, season,
  week, game_id, player_id, team, stat, mean, median, p10, p90, scenario, model_version, as_of)`
  (`scenario` = 'base', 'if_plays', 'if_out'), `player_projection_grades`. Reuse `model_runs` from
  SPEC A (same migration must not create it twice: SPEC A's migration owns `model_runs`; this one
  only reads it).
- Weekly job `backend/jobs/nfl_player_projections.py`: after SPEC A's job on Tuesday, and re-run
  Friday 16:00 and Sunday 10:00 America/Chicago after injury reports and inactives news. A projection
  is locked at the last run before kickoff for grading.
- API: `GET /api/projections/player/{player_id}` returns the version 2 projection for the coming game
  (scenario rows when questionable), with ESPN's beside it; Marcel-lite stays reachable as
  `?model=marcel` until version 2 passes its gate. `GET /api/nfl/projections?week=` for the slate.

---

## 7. Slices and acceptance

| Slice | Owner suggestion | Done when (paste the evidence) |
|---|---|---|
| B0.1 fill 2026 log dates + fix the ingest | Codex | 4,445 rows, 0 empty dates; cause of the empty dates named. |
| B0.2 2026 snap counts + timer | Codex | Row count reconciled with publisher; `OnCalendar` timer listed. |
| B0.3 injury reports ingest | Codex | Rows per week 2024-2026; unresolved count; spot check of 3 known Out players. |
| B1 availability table | Codex | Fixture tests; real counts of played/0/NULL per week 2026. |
| B2 per-game shares | Codex | Season table rebuilt from per-game, diff vs old season table = 0 on overlapping metrics. |
| B3 splits() | Codex | Fixture test + one real 2025 WR1-out example. |
| B4 "without" filter, backend | Codex | Section 3.3 tests pass; existing props tests unchanged. |
| B5 "without" filter, frontend | pi | Screenshots phone/desktop; shared URL reproduces the view. |
| B6 projection engine v2 + redistribution + questionable scenarios | Codex | Backtest table vs Marcel-lite and ESPN; fitted constants listed. |
| B7 weekly job, grading, ESPN weekly benchmark capture | Codex | One full week graded; ESPN weekly rows stored; request budget respected. |
| B8 API + projection record panel | pi | Endpoint outputs; screenshot of the record panel with real rows. |

Order: B0 and B1 first (they also unblock SPEC A version 2), then B4/B5 (the props.cash feature is
user-visible early), then B6-B8.
