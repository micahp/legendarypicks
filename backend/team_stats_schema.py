"""Explicit schema for the team-stats proof database.

Tables: schema_migrations, team_game_results, team_game_stats,
team_stats_coverage, team_stats_team_inventory, team_stats_ingestion_failures.

No legacy migration or deduplication claims.  This is the canonical schema
for a fresh proof database.
"""
from __future__ import annotations

SCHEMA_VERSION = 1

DDL = """
CREATE TABLE schema_migrations (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE team_game_results (
    league         TEXT NOT NULL,
    game_id        TEXT NOT NULL,
    team           TEXT NOT NULL,
    game_date      TEXT NOT NULL,
    opponent       TEXT NOT NULL,
    score_for      REAL NOT NULL,
    score_against  REAL NOT NULL,
    win            INTEGER NOT NULL,
    -- Three-valued outcome ('W'/'D'/'L') for leagues with draws (soccer).
    -- `win` above is kept as a 0/1 compat flag for readers that predate
    -- this column: 1 for W, 0 for D and L. `result` is the honest source —
    -- a draw must never be storable as a loss.
    result         TEXT CHECK (result IN ('W','D','L')),
    season         INTEGER,
    status         TEXT,
    home_away      TEXT,
    PRIMARY KEY (league, game_id, team)
);

CREATE TABLE team_game_stats (
    league         TEXT NOT NULL,
    game_id        TEXT NOT NULL,
    captured_at    TEXT NOT NULL,
    team_abbrev    TEXT NOT NULL,
    home_away      TEXT NOT NULL,
    run_id         TEXT NOT NULL,
    -- NBA
    fgm_fga        TEXT,
    tpm_tpa        TEXT,
    ftm_fta        TEXT,
    rebounds       INTEGER,
    off_rebounds   INTEGER,
    def_rebounds   INTEGER,
    assists        INTEGER,
    steals         INTEGER,
    blocks         INTEGER,
    turnovers      INTEGER,
    -- NHL
    shots               INTEGER,
    blocked_shots       INTEGER,
    hits                INTEGER,
    takeaways           INTEGER,
    giveaways           INTEGER,
    faceoff_pct         REAL,
    powerplay_goals     INTEGER,
    powerplay_opps      INTEGER,
    shorthanded_goals   INTEGER,
    penalty_min         REAL,
    -- NFL
    first_downs                INTEGER,
    total_offensive_plays      INTEGER,
    total_yards                INTEGER,
    net_passing_yards          INTEGER,
    rushing_yards              INTEGER,
    defensive_special_teams_tds INTEGER,
    -- The columns above are FROZEN: no new league adds one. Per-game stats now
    -- live here as a JSON object keyed by the same names, exactly as
    -- player_game_logs.stats does. See LEAGUE_STAT_KEYS below.
    stats          TEXT,
    UNIQUE (league, game_id, team_abbrev)
);

CREATE TABLE team_stats_coverage (
    run_id            TEXT PRIMARY KEY,
    league            TEXT NOT NULL,
    season            INTEGER NOT NULL,
    season_start      TEXT NOT NULL,
    season_end        TEXT NOT NULL,
    status            TEXT NOT NULL,
    expected_teams    INTEGER NOT NULL,
    fetched_teams     INTEGER NOT NULL,
    expected_games    INTEGER,
    fetched_games     INTEGER,
    paired_games      INTEGER,
    paired_stat_games INTEGER,
    failure_count     INTEGER NOT NULL DEFAULT 0,
    completed_at      TEXT,
    source            TEXT NOT NULL,
    -- The date the row's claim actually reaches: every published game from
    -- season_start through here is present and paired. NULL for rows written
    -- before the column existed. This is what lets a live season be offered
    -- without the offer blinking off every time a night's games are played and
    -- not yet ingested -- the claim is a window, not a timestamp.
    checked_through   TEXT
);

CREATE TABLE team_stats_team_inventory (
    run_id       TEXT NOT NULL,
    team_id      TEXT NOT NULL,
    team_abbrev  TEXT,
    PRIMARY KEY (run_id, team_id)
);

CREATE TABLE team_stats_ingestion_failures (
    run_id      TEXT NOT NULL,
    game_id     TEXT,
    team        TEXT,
    reason      TEXT NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_ingestion_failures_run
    ON team_stats_ingestion_failures(run_id);
"""


# ── the per-league stat vocabularies, and why they are a registry now ──────────
#
# The DDL above still carries `-- NBA`, `-- NHL`, `-- NFL` comment blocks. That is
# the defect written down: team_game_stats is one wide table whose columns encode
# the first three leagues' idea of a game, so every sport after them either widens
# the table or goes NULL. Measured 2026-08-11 on dev: NCAAF fills 5 of ~45 columns
# (first_downs, total_yards, net_passing_yards, rushing_yards, turnovers — all
# 1776/1776) and is NULL in the other ~40. Two football columns that DO exist,
# total_offensive_plays and defensive_special_teams_tds, are 0% filled.
#
# player_game_logs solved exactly this by storing per-game stats as a JSON blob.
# Its 56,577 NCAAF rows carry 18 real football keys, no collisions, no DDL change.
# team_game_stats now follows it (Micah, 2026-08-11).
#
# The vocabulary is NOT redefined here. `team_stats_contract.STAT_FIELDS` already
# declares what each league holds, each entry measured against a real published
# boxscore and dated in a comment. A second registry beside it would be the very
# drift this change exists to remove, so the JSON keys ARE those keys — the same
# names as the columns they replace, relocated and not renamed. Changing storage
# and vocabulary in one step would mean a wrong key reads as absence rather than
# raising, on every league at once.
#
# Identity/provenance columns stay REAL COLUMNS: they are joined on, deduplicated
# on, and stamped by the parity runs. Only the stats move.
IDENTITY_COLUMNS: tuple[str, ...] = (
    "league", "game_id", "captured_at", "team_abbrev", "home_away",
    "run_id", "source",
)


def stat_keys_for(league: str) -> tuple[str, ...]:
    """Stat keys this league declares, or () for a league with no manifest.

    Imported lazily: team_stats_contract imports team_codes and is the heavier
    module, and nothing here needs it until a caller asks about a league.

    Returns () rather than guessing. A league nobody wrote a vocabulary for must
    read as UNVERIFIED, never as a league that passed with zero stats.
    """
    from team_stats_contract import STAT_FIELDS
    return tuple(STAT_FIELDS.get((league or "").lower(), ()))


def all_stat_keys() -> tuple[str, ...]:
    """Every stat key any league declares, deduplicated, declaration order."""
    from team_stats_contract import STAT_FIELDS
    return tuple(dict.fromkeys(k for keys in STAT_FIELDS.values() for k in keys))


def expected_tables() -> set[str]:
    """Return the set of table names this schema creates."""
    return {
        "schema_migrations",
        "team_game_results",
        "team_game_stats",
        "team_stats_coverage",
        "team_stats_team_inventory",
        "team_stats_ingestion_failures",
    }


def required_coverage_columns() -> set[str]:
    """Columns the contract's build_team_aggregates requires on team_stats_coverage."""
    return {
        "league", "season", "season_start", "season_end", "status",
        "expected_teams", "fetched_teams", "expected_games", "fetched_games",
        "source", "completed_at",
    }


def required_result_columns() -> set[str]:
    """Columns the contract's build_team_aggregates requires on team_game_results."""
    return {"league", "game_id", "team", "game_date", "opponent",
            "score_for", "score_against", "win"}


def required_stat_columns() -> set[str]:
    """Columns the contract's build_team_aggregates requires on team_game_stats
    (identity + NBA metrics)."""
    return {
        "league", "game_id", "team_abbrev", "home_away", "captured_at",
        "fgm_fga", "tpm_tpa", "ftm_fta", "rebounds", "off_rebounds",
        "def_rebounds", "assists", "steals", "blocks", "turnovers",
    }
