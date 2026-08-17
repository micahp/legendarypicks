#!/usr/bin/env python3
"""Retroactive manifest of the 20 hand-run migration scripts.

Each legacy script is one entry. ``probe(con, league_hint=None)`` inspects a
database read-only and returns a status:

- ``applied``        -- evidence the script's effect is present
- ``unknown``        -- cannot be determined from the database alone
- ``not_applicable`` -- the script by design does not target this database
                       (e.g. a dev->prod copy on the dev side)

An unknown recorded is worth more than an assumption: the ledger row says
``unknown`` and the note says why, so the next operator does not have to guess
whether "ready but not applied" was ever applied.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent  # manifest lives in backend/, scripts are repo-root-relative


@dataclass(frozen=True)
class LegacyMigration:
    migration_id: str
    script: str
    description: str
    probe: Callable[[sqlite3.Connection], str]
    note: str
    applies_to: str = "both"  # "both" | "prod" (dev->prod copy scripts target prod only)


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(con, table):
        return set()
    return {str(row[1]) for row in con.execute(f'PRAGMA table_info("{table}")')}


def _count(con: sqlite3.Connection, sql: str, params: Iterable = ()) -> int:
    return int(con.execute(sql, tuple(params)).fetchone()[0])


def _has_columns(con: sqlite3.Connection, table: str, required: Iterable[str]) -> str:
    missing = [c for c in required if c not in _columns(con, table)]
    if missing:
        return f"unknown: {table} lacks columns {missing} -- script may not have run"
    return "applied"


def _no_rows(con: sqlite3.Connection, sql: str, params: Iterable = ()) -> str:
    n = _count(con, sql, params)
    if n == 0:
        return "applied"
    return f"not_applied: {n} rows still carry the legacy value"


def _no_rows_unknown(con: sqlite3.Connection, sql: str, params: Iterable = ()) -> str:
    """Version for migrations whose absence of the legacy value proves
    nothing (the value may never have existed)."""
    n = _count(con, sql, params)
    if n == 0:
        return "applied"
    return f"unknown: {n} rows still carry the legacy value"


# --- per-script probes -------------------------------------------------------

def _probe_mlb_counting_stats(con: sqlite3.Connection) -> str:
    return _has_columns(
        con, "player_stats",
        ("pa", "ab", "mlb_hits", "runs", "rbi", "era", "innings", "whip"),
    )


def _probe_mlb_position_vocabulary(con: sqlite3.Connection) -> str:
    return _has_columns(con, "players", ("position_group", "pitcher_role"))


def _probe_nfl_position_spellings(con: sqlite3.Connection) -> str:
    return _no_rows(
        con,
        "SELECT COUNT(*) FROM players WHERE league='nfl' AND position IN ('K','SAF')",
    )

def _probe_nfl_td_columns(con: sqlite3.Connection) -> str:
    return _has_columns(con, "player_stats", ("rush_td", "rec_td", "attempts"))


def _probe_nfl_team_vocabulary(con: sqlite3.Connection) -> str:
    return _no_rows(
        con,
        "SELECT COUNT(*) FROM players WHERE league='nfl' AND team IN ('STL','SD','LA','AZ')",
    )


def _probe_nhl_goalie_columns(con: sqlite3.Connection) -> str:
    return _has_columns(
        con, "player_stats",
        (
            "saves", "shots_against", "goals_against", "save_pct", "gaa",
            "shutouts", "wins", "losses", "ot_losses", "games_started",
            "blocked_shots", "hits", "takeaways", "giveaways",
        ),
    )


def _probe_nhl_season_keys(con: sqlite3.Connection) -> str:
    return _no_rows(
        con,
        "SELECT COUNT(*) FROM player_game_logs WHERE league='nhl' "
        "AND CAST(season AS TEXT) LIKE '______'",
    )


def _probe_league_position_groups(con: sqlite3.Connection) -> str:
    """NFL/NBA position_group is applied when active person rows carry it."""
    return _no_rows(
        con,
        "SELECT COUNT(*) FROM players WHERE league IN ('nfl','nba') AND active=1 "
        "AND COALESCE(entity_type,'player')='player' "
        "AND (position_group IS NULL OR TRIM(position_group)='')",
    )

def _probe_player_entity_type(con: sqlite3.Connection) -> str:
    """Applied means the constructs are CLASSIFIED, not merely non-null.

    This probe used to count `entity_type IS NULL` only. On 2026-08-17 all 96
    NFL constructs sat at 'unknown' -- populated, so the probe read "applied"
    for the whole outage while `ingest_nfl_adp.py` aborted every run on
    `def_to_pid has 0 entries`. A column being filled in is a claim about the
    column; ask the question the readers actually ask.
    """
    applied = _has_columns(con, "players", ("entity_type",))
    if applied != "applied":
        return applied
    n = _count(
        con,
        "SELECT COUNT(*) FROM players WHERE league='nfl' AND entity_type IS NULL",
    )
    if n >= 100:
        return f"unknown: {n} NFL rows have no entity_type"
    # Only ask about D/ST on a database that actually holds the constructs. A
    # fixture with no NFL spine has nothing to classify; the broken state this
    # guards against is the opposite -- the rows PRESENT and sitting at
    # 'unknown' -- so this cannot hide it.
    constructs = _count(
        con,
        "SELECT COUNT(*) FROM players WHERE league='nfl' "
        "AND CAST(espn_id AS INTEGER) < 0",
    )
    if constructs == 0:
        return "applied"
    # The 32 team defences are the ones `ingest_nfl_adp.py` builds its map from.
    defences = _count(
        con,
        "SELECT COUNT(*) FROM players WHERE league='nfl' "
        "AND entity_type='team_defense'",
    )
    if defences != 32:
        return (f"unknown: {defences} of {constructs} negative-id NFL rows "
                f"classified team_defense, expected 32 "
                f"-- ingest_nfl_adp.py's D/ST preflight will abort")
    return "applied"


def _probe_player_fantasy_positions(con: sqlite3.Connection) -> str:
    n = _count(
        con,
        "SELECT COUNT(*) FROM players WHERE league='nfl' "
        "AND entity_type IN ('team_defense','team_qb','coach') "
        "AND position IS NOT NULL",
    )
    return "applied" if n == 0 else f"unknown: {n} construct rows still carry position"


def _probe_player_injury_columns(con: sqlite3.Connection) -> str:
    return _has_columns(con, "players", ("injury_status", "last_news_date"))


def _probe_prop_games_start_time(con: sqlite3.Connection) -> str:
    return _has_columns(con, "prop_games", ("start_time",))


def _probe_ufc_rankings(con: sqlite3.Connection) -> str:
    if not _table_exists(con, "ufc_rankings"):
        return "unknown: ufc_rankings table absent"
    n = _count(con, "SELECT COUNT(*) FROM ufc_rankings")
    return "applied" if n > 0 else "unknown: ufc_rankings empty"


def _probe_team_stats_from_dev(con: sqlite3.Connection) -> str:
    # Target side: approved league/season windows present. Source side: the
    # script does not write dev, so it is not applicable there.
    if not _table_exists(con, "team_stats_coverage"):
        return "unknown: team_stats_coverage absent"
    n = _count(con, "SELECT COUNT(*) FROM team_stats_coverage")
    return "applied" if n > 0 else "unknown: coverage manifest empty"


def _probe_team_stats_proof(con: sqlite3.Connection) -> str:
    # migrate_team_stats.py builds a fresh proof DB in /tmp by design; it
    # never targets picks.db / picks.dev.db (PROTECTED_SUBSTRINGS).
    return "not_applicable"


def _probe_logs_to_prod(con: sqlite3.Connection) -> str:
    # Target side: player_game_logs populated. Source side: not applicable.
    if not _table_exists(con, "player_game_logs"):
        return "unknown: player_game_logs absent"
    n = _count(con, "SELECT COUNT(*) FROM player_game_logs")
    return "applied" if n > 0 else "unknown: player_game_logs empty"


def _probe_nfl_stats_to_prod(con: sqlite3.Connection) -> str:
    # Merges NFL per-game stat keys into existing prod logs. Applied when
    # snap/NGS keys are present in stored NFL stats JSON.
    if not _table_exists(con, "player_game_logs"):
        return "unknown: player_game_logs absent"
    n = _count(
        con,
        "SELECT COUNT(*) FROM player_game_logs "
        "WHERE league='nfl' AND stats LIKE '%off_snaps%'",
    )
    return "applied" if n > 0 else "unknown: no NFL log carries off_snaps"


def _probe_registered(con: sqlite3.Connection, migration_id: str) -> str:
    if not _table_exists(con, "app_schema_migrations"):
        return "unknown: registry absent"
    row = con.execute(
        "SELECT 1 FROM app_schema_migrations WHERE migration_id=?",
        (migration_id,),
    ).fetchone()
    return "applied" if row else "unknown: registry row missing"


def _make_registered(migration_id: str) -> Callable[[sqlite3.Connection], str]:
    return lambda con: _probe_registered(con, migration_id)


LEGACY_MIGRATIONS: tuple[LegacyMigration, ...] = (
    LegacyMigration(
        migration_id="legacy_migrate_schema",
        script="backend/migrate_schema.py",
        description="versioned SQLite schema migrations (runner itself)",
        probe=_make_registered("20260728_001_player_game_logs_game_type"),
        note="the schema runner; its own numbered migrations are registered",
    ),
    LegacyMigration(
        migration_id="legacy_migrate_player_stats",
        script="backend/migrate_player_stats.py",
        description="canonical player_stats identity key",
        probe=_make_registered("20260729_001_canonical_player_stats"),
        note="self-registers; probe checks the registry row",
    ),
    LegacyMigration(
        migration_id="legacy_migrate_roster_snapshots",
        script="backend/migrate_roster_snapshots.py",
        description="canonical roster snapshots",
        probe=_make_registered("20260729_002_canonical_roster_snapshots"),
        note="self-registers; probe checks the registry row",
    ),
    LegacyMigration(
        migration_id="legacy_migrate_mlb_counting_stats",
        script="backend/migrate_mlb_counting_stats.py",
        description="MLB counting-stat columns on player_stats",
        probe=_probe_mlb_counting_stats,
        note="columns pa/ab/mlb_hits/runs/rbi/era/innings/whip",
    ),
    LegacyMigration(
        migration_id="legacy_migrate_mlb_position_vocabulary",
        script="backend/migrate_mlb_position_vocabulary.py",
        description="MLB position_group + pitcher_role columns",
        probe=_probe_mlb_position_vocabulary,
        note="three-level MLB position vocabulary",
    ),
    LegacyMigration(
        migration_id="legacy_migrate_nfl_position_spellings",
        script="backend/migrate_nfl_position_spellings.py",
        description="K->PK, SAF->S",
        probe=_probe_nfl_position_spellings,
        note="0 legacy K/SAF rows means applied",
    ),
    LegacyMigration(
        migration_id="legacy_migrate_nfl_td_columns",
        script="backend/migrate_nfl_td_columns.py",
        description="NFL rush_td/rec_td/attempts columns",
        probe=_probe_nfl_td_columns,
        note="v0.7.3 headline feature; was 0 rows in prod through 3 releases",
    ),
    LegacyMigration(
        migration_id="legacy_migrate_nfl_team_vocabulary",
        script="backend/migrate_nfl_team_vocabulary.py",
        description="nflverse team codes -> ESPN",
        probe=_probe_nfl_team_vocabulary,
        note="prod was measured with 869 STL/SD/LA/AZ rows on 2026-08-05",
    ),
    LegacyMigration(
        migration_id="legacy_migrate_league_position_groups",
        script="backend/migrate_league_position_groups.py",
        description="NFL/NBA position_group category column (FB->Offense, PF->Forward)",
        probe=_probe_league_position_groups,
        note="applied to both DBs 2026-08-05; clears C/vocabulary[position]",
    ),
    LegacyMigration(
        migration_id="legacy_migrate_nhl_goalie_columns",
        script="backend/migrate_nhl_goalie_columns.py",
        description="NHL goalie/defence columns",
        probe=_probe_nhl_goalie_columns,
        note="saves/shots_against/goals_against/save_pct/gaa/shutouts/...",
    ),
    LegacyMigration(
        migration_id="legacy_migrate_nhl_season_keys",
        script="backend/migrate_nhl_season_keys.py",
        description="NHL 8-digit season keys -> ESPN 4-digit",
        probe=_probe_nhl_season_keys,
        note="prod had 48,017 rows on 20252026; 0 8-digit keys means applied",
    ),
    LegacyMigration(
        migration_id="legacy_migrate_player_entity_type",
        script="backend/migrate_player_entity_type.py",
        description="players.entity_type (person vs fantasy construct)",
        probe=_probe_player_entity_type,
        note="team_defense/team_qb/coach classified from ESPN negative ids",
    ),
    LegacyMigration(
        migration_id="legacy_migrate_player_fantasy_positions",
        script="backend/migrate_player_fantasy_positions.py",
        description="NULL position on fantasy construct rows",
        probe=_probe_player_fantasy_positions,
        note="96 construct rows expected; 0 with position means applied",
    ),
    LegacyMigration(
        migration_id="legacy_migrate_player_injury_columns",
        script="backend/migrate_player_injury_columns.py",
        description="players.injury_status + last_news_date",
        probe=_probe_player_injury_columns,
        note="was added to dev by hand; prod served 0 injury_status on 08-05",
    ),
    LegacyMigration(
        migration_id="legacy_migrate_prop_games_start_time",
        script="backend/migrate_prop_games_start_time_to_prod.py",
        description="prop_games.start_time column",
        probe=_probe_prop_games_start_time,
        note="prod props ingest failed 'no such column: start_time' pre-fix",
    ),
    LegacyMigration(
        migration_id="legacy_migrate_ufc_rankings",
        script="backend/migrate_ufc_rankings_to_prod.py",
        description="UFC rankings dev -> prod",
        probe=_probe_ufc_rankings,
        note="dev is the source; the script only writes the prod target",
        applies_to="prod",
    ),
    LegacyMigration(
        migration_id="legacy_migrate_team_stats_from_dev",
        script="backend/migrate_team_stats_from_dev.py",
        description="approved team-stats windows dev -> target",
        probe=_probe_team_stats_from_dev,
        note="dev is the source; the script only writes the prod target",
        applies_to="prod",
    ),
    LegacyMigration(
        migration_id="legacy_migrate_team_stats",
        script="backend/migrate_team_stats.py",
        description="fresh proof DB builder (never targets picks.db)",
        probe=_probe_team_stats_proof,
        note="creates disposable proof DBs in /tmp; not applicable to live DBs",
    ),
    LegacyMigration(
        migration_id="legacy_migrate_logs_to_prod",
        script="backend/migrate_logs_to_prod.py",
        description="copy missing player-game logs dev -> target",
        probe=_probe_logs_to_prod,
        note="dev is the source; the script only writes the prod target",
        applies_to="prod",
    ),
    LegacyMigration(
        migration_id="legacy_migrate_nfl_stats_to_prod",
        script="backend/migrate_nfl_stats_to_prod.py",
        description="merge NFL stat keys into prod logs",
        probe=_probe_nfl_stats_to_prod,
        note="dev is the source; the script only writes the prod target",
        applies_to="prod",
    ),
    LegacyMigration(
        migration_id="legacy_merge_nba_identities",
        script="backend/scripts/merge_nba_identities.py",
        description="merge split NBA espn_id/nba_id rows",
        probe=_make_registered("20260805_001_merge_nba_identities"),
        note="269 split athletes fixed on prod 2026-08-05; dev was already clean",
    ),
)


def script_checksum(script: str) -> str:
    path = REPO_ROOT / script
    return hashlib.sha256(path.read_bytes()).hexdigest()


def all_scripts() -> tuple[str, ...]:
    return tuple(m.script for m in LEGACY_MIGRATIONS)
