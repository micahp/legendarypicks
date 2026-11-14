# Finalized NFL game-day rosters, 2026 Weeks 2–9

## Deliverables

- `finalized-game-day-rosters.csv`: one row per player per game, with the gamebook's active or inactive designation and roster role.
- `finalized-roster-coverage.json`: per-game/team counts and source/identity coverage.
- `official-gamebooks-source-manifest.csv`: source URL, byte size, and SHA-256 for all 120 official gamebooks.
- `nflverse-vs-gamebook-status-conflicts.csv`: all player rows where the weekly ACT/INA label differs from the gamebook.
- `source-roster_weekly_2026.parquet`: pinned nflverse roster used only for GSIS player identity and status comparison.
- `backend/recover_finalized_nfl_game_rosters.py`: deterministic extractor and identity join.

## Source and roster meaning

The roster status comes from page 1 of the official NFL GSIS gamebook for each
scheduled regular-season game. The parser reads Lineups, Substitutions, Did Not
Play, and Not Active. Lineups, Substitutions, and Did Not Play count as active
game-day roster players; Not Active counts as inactive. Thus `ACTIVE` means
eligible on the game-day roster, not that the player entered the game. NFL
gamebooks are official postgame records ([NFL Game Books](https://support.nfl.com/hc/en-us/articles/35869678028180-Game-Books)).

The join uses the pinned nflverse weekly roster's GSIS ID, week, team, jersey,
and name. nflverse ACT/INA is retained as a comparison field only: six rows
disagree with the gamebook, so its status does not override the official
gamebook. Status values are defined in the [nflreadr roster status dictionary](https://nflreadr.nflverse.com/articles/dictionary_roster_status.html).

There are 120 games, 240 team-games, and 13,033 roster player-game rows:
11,516 active and 1,517 inactive. All 120 PDFs match the manifest hashes and
all player identities resolve uniquely. Active roster sizes are 47 (5 teams),
48 (234 teams), and 49 (one team). The 49-player row is Baltimore in Week 8;
its 49th active player is emergency third quarterback Joe Fagnano. NFL permits
an emergency third quarterback as the 49th player ([NFL rule explanation](https://www.nfl.com/_amp/nfl-emergency-third-quarterback-rule-questions-and-answers)).

## Backtest boundary

This is finalized, postgame roster truth for evaluating 2026 outcomes. It does
not establish that the final status was available at a model's forecast cutoff.
Do not feed these labels into a pregame model as if they were observed inputs;
use them as realized roster outcomes or evaluation labels. The injury-report
archive above separately records that historic report observation timestamps
were not recovered.

## Rebuild

Run from the repository root with the project Python environment and
`pdftotext` installed. Keep the 120 PDFs named by `game_id` in a local
directory; obtain them at the manifest URLs and verify each file against its
recorded SHA-256 before extraction.

```sh
backend/venv/bin/python backend/recover_finalized_nfl_game_rosters.py \
  --schedule-csv docs/research/nfl-injury-history-2026-weeks2-9/source-games.csv \
  --weekly-roster docs/research/nfl-injury-history-2026-weeks2-9/source-roster_weekly_2026.parquet \
  --gamebook-manifest docs/research/nfl-injury-history-2026-weeks2-9/official-gamebooks-source-manifest.csv \
  --gamebooks-dir /path/to/gamebooks \
  --out-dir docs/research/nfl-injury-history-2026-weeks2-9
```
