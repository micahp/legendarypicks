# Changelog

All notable changes to Legendary Picks are documented here.

Versioning follows [Semantic Versioning](https://semver.org): `vMAJOR.MINOR.PATCH`.
- **MAJOR** — breaking changes / major product milestones (still `0` pre-launch).
- **MINOR** — new features, backwards-compatible.
- **PATCH** — bug fixes, backwards-compatible.

Each released version corresponds to a git tag and a production deploy. The version
in `package.json` tracks the next (in-development) release.

> Note: a stray `package.json` version of `0.3.1` predated this scheme and was never a
> real release. Disciplined versioning starts here, with the current production state
> tagged `v0.1.0`.

## [Unreleased] — targeting v0.2.0

The analytics-backbone branch — built, not yet deployed.

### Added
- **Per-game player logs** (`player_game_logs`) across all four leagues — 111k+ logs,
  spine-resolved. The stats foundation projections/fantasy run on, no sportsbook data needed.
  Ingests: NFL weekly 2024 + NFL play-by-play 2025 (EPA/CPOE/air-yards), MLB Statcast,
  NHL nhle.com game-log, NBA ESPN box scores.
- **Player projections** — `/api/projections/player/{id}` + the **Model tab**: recency-weighted
  expected value, floor/median/ceiling, P(over a line), and projected fantasy points.
- **roster_sync** — current ESPN rosters populate `espn_id` and a meaningful `active` flag.
- **World Cup standings** consolidated into the Stats tab as a league option.

### Changed
- **NFL identity dedupe** — removed 380 id-less orphan player rows that shadowed real players
  (distinct same-name players preserved).
- **Standings** page removed; folded into Stats.

### Fixed
- `/api/player/{id}/stats` raised `NameError('now')` on every call — the Performance tab's
  advanced-stats panel was dead for all leagues.
- World Cup / COD live badges (match clock + game number display).
- World Cup winner dimming (winner flag now reaches the frontend; draws no longer dim both sides).

## [0.1.0] — 2026-06-26 — production baseline

First tagged release. Snapshot of what was live on prod:
- backend `dee1133` (COD/breakingpoint scoreboard fix)
- frontend `b4ae8f9` (~2 commits behind backend on the `dev` line — a known deploy drift)

Includes the ESPN-based sports backend, scores/standings/predict/props/stats/analytics pages,
settlement pipeline, odds capture, and EV/CLV/calibration analytics (M1–M7).
