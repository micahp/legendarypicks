# Handoff: branch cleanup, 2026-10-13

Repo `/root/legendarypicks`, branch `dev` (nothing pushed except two branches noted below).
Rules in force: no em dashes, explicit paths only when staging, ask before pushing, deleting
material data or removing a worktree with uncommitted files. The checkout has 23 changed or
untracked files that are not ours (radio and GameCard edits, sim JSONs, docs). Leave them alone.

## How deletion works here

Every deleted branch was first tagged `archive/<branch-name>` at the same commit (verified).
There are 100 archive tags. Restore with `git branch <name> archive/<name>`.
Use `git branch -d`, never `-D`. The user said "dont force". Branches merged into `dev` but not
into their `origin/` copy are refused by `-d`; push them first (normal push), then `-d`.

## Done today

- Merged into `dev`: `feat/nfl-grading-record`, `feat/nfl-playoff-odds`, the NHL ingest fix
  (`b516800`), `docs/agents-md-compact` (AGENTS.md 29 KB to 5.7 KB, full text now in
  `docs/AGENTS-REFERENCE.md`).
- Committed to `dev`: the two EWC docs (`df585d4`) and three MLS docs (`aa0570b`:
  PLAN-rotowire-mls-props-replacement, RESEARCH-MLS-PLAYER-PROP-LINES, ROTOWIRE-PICKS-RELAY)
  before dropping their branches. Em dashes in the MLS docs were replaced.
- Archived and deleted, first group (12): release/v0.9.0, feat/mlb-rotowire-backfill,
  backup/dev-before-version-rewrite, four preserve/stash-* branches, feat/mls-ncaaf-standings,
  backup/ow-pre-rebase-2026-07-02, preserve/mls-residuals-20260808, fix/ewc-title-coverage,
  preserve/ewc-coverage-worktree-20260902.
- Archived and deleted, second group (5, all patch-identical to commits in `dev`):
  feat/dst-and-mock-draft, fix/ewc-page-refresh, fix/ewc-visible-now,
  feat/props-provider-runner, fix/ncaaf-prop-game-dedupe. Two worktrees removed.
- Archived and deleted, third group (4): feat/ncaaf-week-navigation (dev has
  `/api/ncaaf/schedule-weeks`), feat/ewc-official-branding (dev has `_BRAND_SOURCE` and
  `_TITLE_BRAND_ASSETS`), backup-analytics-20260630-084238, preserve/mls-ncaaf-worktree-20260902.
- Archived and deleted, fourth group (62): every branch fully contained in `dev` (ahead 0) that
  had no worktree. Two of them (`fix/kick-viewer-keys`, `scoreboard-outcomes-homepage`) were
  first pushed to origin as plain fast-forwards (`5bee747..f038420`, `a9c70e8..ce9a921`), then
  deleted with `-d`.
- Removed: worktree and branch `fix/nhl-season-ingest-identity` (merged), the `node_modules`
  symlink in `/root/lp-watch-registry`.
- 48 branches remain (including `dev`).

## What is left

### A. Merged into `dev`, still has a worktree (33). Safe to archive and delete once the worktree goes

Worktree removal discards uncommitted files, so check these first. Seven worktrees in this
group, plus three in section B, are dirty (the full dirty list is in the next section).

feat/game-audio-links, feat/league-filter-pills, feat/ncaaf-radio-links, feat/new-leagues,
feat/nfl-grading-record, feat/nfl-playoff-odds, feat/rotowire-mlb-lcup,
feat/sport-first-navigation, feat/story-coverage, feat/tennis-current-spine,
feat/ufc-settlement, feat/ufc-underdog-refresh, feat/ufcstats-history-backfill,
fix/cfbd-logs-resolve-only, fix/club-crosswalk, fix/lcup-bind-only, fix/nhl-tricodes,
fix/props-slate-day-league, fix/props-slate-remove-league-count, fix/props-source-label,
fix/published-roster-resolver, fix/release-audit-blockers, fix/reviewed-name-repair,
fix/scoreboard-second-column, fix/scores-db-primary, fix/scores-past-failures,
fix/soccer-logs-pipeline, fix/tennis-news-combined, fix/tennis-player-search,
fix/transfer-not-conflict, fix/ufc-optimizer-refresh, fix/unique-prop-lines,
fix/v080-release-promotion, hotfix/cod-scoreboard-v0.7.9.
Worktrees are `/root/lp-*`; run `git worktree list` for the mapping.

### Dirty worktrees (10), measured today, nothing changed

| Worktree | Uncommitted content | Verdict |
|---|---|---|
| lp-v080-release | migration tooling: `scripts/sqlite_fingerprint.py`, its test, `promote_team_stat_windows.py`, edits to `migrate_schema.py` (+169) and `migrate_logs_to_prod.py` (+111), none in dev | **Possibly unique. Save first** (commit to an archive ref) |
| lp-prod-tabs-hotfix | staged test renames into `__tests__/`; `soccer` and `tennis` ones are not in dev | check, small |
| lp-unique-prop-lines | edits to MarketSlateBoard.tsx and SlatePlayerOffers.tsx (about 14 lines), `lineOptions.ts` is already in dev | probably older drafts, diff against dev |
| lp-new-leagues | one-line edit to `esports_team_logos.json`, 280 MB `preview.db` | junk |
| lp-sport-first-nav | about 200 MB caches and a 380 MB db clone | junk |
| lp-nfl-allday | task doc already in dev, venv symlink | junk (branch itself has 4 unique commits, NFL) |
| lp-story-coverage, lp-ufc-settlement | TASK files, venv symlink | junk |
| lp-release-v097 | venv symlink only | junk (branch is a prod line, keep) |
| lp-tennis-spine | `TASK-tennis-spine.md`, codex's brief | keep for now |

### B. Branches with commits not in `dev` (13)

- Keep, NFL work in flight: feat/nfl-model-foundation (+20), feat/player-projections-availability
  (+30), scratch/spec-b-rebase (+30), feat/nfl-epa-efficiency (+2), feat/nfl-allday (+4),
  codex/nfl-v1 (+4).
- Keep, prod lines: release/v0.9.6 (+5), release/v0.9.7 (+11).
- Keep, in progress: feat/tennis-spine (+1) and feat/watch-stream-registry (+3).
- **Undecided, the user has not approved dropping them:** feat/prop-repair (+1, superseded by
  `core_markets.py` and `backfill_market_keys.py`), codex/nba-v1 (+1), codex/nhl-v1 (+2). They
  conflict with `dev` in 19 files. My recommendation was to drop; it rests on judgment, not
  measurement. Ask first.

## Open threads that are not cleanup

- **Tennis player coverage (hand-off to the codex pane, tmux `codex:0.0`, pane `%26`).**
  `feat/tennis-spine` builds the ATP/WTA player list from ESPN, which is banned (Micah,
  2026-09-09). On `dev`, `players` has 164 atp and 167 wta rows (from the scoreboard ingest),
  while `unresolved_players` holds 353 atp and 217 wta names (reason `source_id_not_in_spine`,
  Underdog 227 and 83, Bovada 126 and 134). Props for them are discarded. Codex was given the
  task and an addendum listing sources we already use: Underdog source ids
  (`player_source_ids`, 102 atp and 80 wta bound today), the US Open feed used by
  `ingest_usopen_tennis_logs.py`, Bovada (names only, never create players from it). Codex had
  found the official WTA ranked-players API (api.wtatennis.com, about 1,545 rows) and listed
  Sackmann CSVs and Kalshi as candidates; ATP still needs a source. Do not archive
  `feat/tennis-spine` until coverage is measured and good.
  Codex hit a usage limit earlier that resets at 3:53 PM; check it is still running.
- **Watch registry.** `feat/watch-stream-registry` has `dev` merged in (`57496c6`, one conflict
  in `backend/sports_service.py` resolved by keeping both routers). 6 backend tests and the
  2 `WatchPage` jest tests pass; `tsc` shows no errors in Watch files. Not merged to `dev`,
  not pushed. Broadcasts are a hand-maintained list; the scheduled collector does not exist.
- **NFL (unchanged).** Ingest 2026 week 5 play-by-play, then `build_player_game_shares.py
  --season 2026`. Before Thu 10-15 rerun the Spec B week 6 job and
  `capture_espn_weekly_projections.py --season 2026 --weeks 6`. Nothing is pushed, no timers
  installed. The playoff-odds job refuses while swap is full.
- Scratchpad holds a roughly 1.2 GB `dev-copy.db` that can be deleted.
