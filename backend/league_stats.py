#!/usr/bin/env python3
"""Canonical persistence policy for league-level player statistics.

``player_stats`` is a published display table, not a raw multi-source lake.
Every row has one canonical player owner, one league-specific statistic type,
and one approved publisher. Raw source snapshots belong outside this table.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from typing import Mapping


class LeagueStatContractError(ValueError):
    """A writer attempted to publish outside the canonical stats contract."""


_SEASON_STAT_LEAGUES = frozenset(("nba", "nfl", "nhl", "ncaaf", "mls"))
_DERIVED_ROLLUP_LEAGUES = frozenset()

PLAYER_STATS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS player_stats(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  player_name TEXT NOT NULL,
  name_norm TEXT,
  league TEXT NOT NULL,
  team TEXT,
  stat_type TEXT NOT NULL,
  season INTEGER NOT NULL,
  games INTEGER,
  pts REAL,
  reb REAL,
  ast REAL,
  stl REAL,
  blk REAL,
  tov REAL,
  fgm INTEGER,
  fga INTEGER,
  fg3m INTEGER,
  fg3a INTEGER,
  ftm INTEGER,
  fta INTEGER,
  minutes REAL,
  ts_pct REAL,
  avg REAL,
  hr INTEGER,
  k_pct REAL,
  bb_pct REAL,
  exit_velo REAL,
  hard_hit_pct REAL,
  barrel_pct REAL,
  launch_angle REAL,
  woba REAL,
  xwoba REAL,
  whiff_pct REAL,
  exit_velo_against REAL,
  barrel_pct_against REAL,
  xwoba_against REAL,
  pass_yds_g REAL,
  pass_td INTEGER,
  interceptions INTEGER,
  cmp_g REAL,
  pass_epa REAL,
  carries_g REAL,
  rush_yds_g REAL,
  receptions INTEGER,
  rec_yds_g REAL,
  targets INTEGER,
  fantasy_pts_g REAL,
  fantasy_ppr_g REAL,
  nfl_position TEXT,
  nfl_team TEXT,
  goals INTEGER,
  assists INTEGER,
  points_nhl INTEGER,
  shots INTEGER,
  shooting_pct REAL,
  plus_minus INTEGER,
  pim INTEGER,
  ppg INTEGER,
  ppp INTEGER,
  shg INTEGER,
  toi TEXT,
  faceoff_pct REAL,
  -- Hockey has three player types and nhle.com publishes a separate report
  -- for each: forwards and defencemen come from `skater/summary`, defencemen
  -- also need `skater/realtime` (blocks and hits are the whole job), and
  -- goalies come from `goalie/summary`. Everything above this comment is
  -- forward-shaped, which is why a goalie row read 0 goals, 0 assists, 0
  -- shots and nothing else -- a goaltender described entirely by things
  -- goaltenders do not do.
  blocked_shots INTEGER,
  hits INTEGER,
  takeaways INTEGER,
  giveaways INTEGER,
  saves INTEGER,
  shots_against INTEGER,
  goals_against INTEGER,
  save_pct REAL,
  gaa REAL,
  shutouts INTEGER,
  wins INTEGER,
  losses INTEGER,
  ot_losses INTEGER,
  games_started INTEGER,
  nhl_position TEXT,
  nhl_team TEXT,
  source TEXT NOT NULL,
  player_id INTEGER NOT NULL REFERENCES players(id),
  UNIQUE(player_id,league,season,stat_type)
)
""".strip()


def normalize_player_name(value: str | None) -> str:
    """Normalize a display name for denormalized storage, never for identity."""
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", str(value))
    normalized = normalized.encode("ascii", "ignore").decode("ascii").casefold()
    normalized = re.sub(r"\b(jr\.?|sr\.?|ii|iii|iv|v)\b", "", normalized)
    normalized = re.sub(r"[^a-z0-9\s]", "", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def canonical_stat_type(league: str, stat_type: str | None) -> str:
    """Return the only display-stat type accepted for a league."""
    normalized_league = str(league or "").strip().lower()
    normalized_type = str(stat_type or "").strip().lower()
    if normalized_league == "mlb":
        if normalized_type not in ("batting", "pitching"):
            raise LeagueStatContractError(
                "MLB player stats require stat_type batting or pitching"
            )
        return normalized_type
    if normalized_league in _SEASON_STAT_LEAGUES:
        return "season"
    raise LeagueStatContractError(
        f"unsupported player-stats league: {league!r}"
    )


def source_owns_stats(
    league: str, stat_type: str | None, season: int, source: str
) -> bool:
    """Whether SOURCE owns the published row for this league/season/type."""
    normalized_league = str(league or "").strip().lower()
    normalized_source = str(source or "").strip()
    try:
        canonical_stat_type(normalized_league, stat_type)
    except LeagueStatContractError:
        return False

    if normalized_league == "mlb":
        # Two publishers, two halves of one row. Statcast publishes exit
        # velocity, barrel rate and xwOBA; statsapi publishes the counting
        # line -- PA, hits, RBI, ERA, innings -- and neither will ever carry
        # the other's. `statsapi` became an owner when the identity rebuild
        # landed: the rebuild archives every current-season aggregate for
        # regeneration (an average computed over half a split identity is
        # wrong, not merely misfiled), and something has to be allowed to
        # CREATE the replacement rows.
        #
        # Order matters and is not enforceable here: publishing is
        # delete-then-insert per (player_id, league, season, stat_type), so
        # whichever of the two runs last owns the row and the other's columns
        # are gone. `ingest_mlb_counting_stats.py` is idempotent, cheap (two
        # requests) and preserves Statcast's columns when it finds them, so
        # the rule is: run it AFTER any Statcast refresh, never before.
        return normalized_source in ("statcast", "statsapi")
    if normalized_league == "nhl":
        return normalized_source == "nhle.com"
    if normalized_league == "nba":
        # hoopR used to own <=2023. Those 525 rows were deleted 2026-08-05: its
        # parquet mirror dead-ends at 2023, so they were a dead pipeline's
        # residue sitting in the same season selector as ESPN's -- two
        # publishers' definitions presented as one comparable series, with
        # nothing on the page saying so. ESPN publishes 2025 and 2026 (2024 is
        # refused by the 80% spine-reach floor, which is a coverage gap, not a
        # publisher gap). One publisher owns this league now.
        # ESPN owns NBA, and publishes it from two endpoints.
        # `espn_core` is sports.core.api, one request PER ATHLETE -- 643 of
        # them, which is what tripped ESPN's rate block and left this league
        # serving 2023 for years. `espn_web` is site.web.api's byathlete
        # report: the same publisher, the same season, 578 athletes in 6
        # requests. Both are accepted so the row can record which endpoint it
        # actually came from instead of one lying about the other.
        return normalized_source in ("espn_core", "espn_web")
    if normalized_league == "nfl":
        return normalized_source == "nflverse_regular_season"
    if normalized_league == "ncaaf":
        # NCAAF season stats are the CFBD per-game values we already hold,
        # summed per player by ingest_ncaaf_season_stats.py. CFBD athlete ids
        # ARE spine espn_ids (direct join), so one publisher owns the row.
        return normalized_source == "cfbd"
    if normalized_league == "mls":
        # MLS season stats are the ESPN per-game values ingest_soccer_logs
        # writes (goals/assists/shots/sot, zero-filled), summed per player by
        # ingest_mls_season_stats.py. The logs are source 'espn', so espn owns
        # the row.
        return normalized_source == "espn"
    return False


def supports_derived_stats(league: str) -> bool:
    """Whether the compatibility rollup job owns this league."""
    return str(league or "").strip().lower() in _DERIVED_ROLLUP_LEAGUES


def canonical_population_sql(
    league: str, stat_type: str | None, *, alias: str = ""
) -> tuple[str, list[object]]:
    """Return a parameterized SQL predicate for published display rows."""
    normalized_league = str(league or "").strip().lower()
    normalized_type = canonical_stat_type(normalized_league, stat_type)
    prefix = f"{alias}." if alias else ""
    clause = f"{prefix}stat_type=?"
    params: list[object] = [normalized_type]
    if normalized_league == "mlb":
        clause += f" AND {prefix}source='statcast'"
    elif normalized_league == "nhl":
        clause += f" AND {prefix}source='nhle.com'"
    elif normalized_league == "nfl":
        clause += f" AND {prefix}source='nflverse_regular_season'"
    elif normalized_league == "nba":
        # Post-2023 is `espn_web`, not `espn_core`. `ingest_nba_season_stats.py`
        # exists *because* the per-athlete `espn_core` path tripped ESPN's block
        # and published zero rows ever; it was replaced by the bulk
        # `site.web.api` report, which writes `espn_web` -- and this filter was
        # never moved with it. The mismatch does not raise, it MISSES: on
        # 2026-08-05 prod held 565 correct 2026 rows and the leaderboard served
        # 2023, because `available_seasons` is derived through this predicate.
        # Only `espn_core` fixtures in the tests kept it looking healthy.
        # The <=2023 hoopR branch was dropped with those rows on 2026-08-05 --
        # see `source_owns_stats`. One publisher, every season.
        clause += f" AND {prefix}source='espn_web'"
    elif normalized_league == "ncaaf":
        clause += f" AND {prefix}source='cfbd'"
    elif normalized_league == "mls":
        clause += f" AND {prefix}source='espn'"
    return clause, params


def canonical_player_stats_row(
    connection: sqlite3.Connection,
    *,
    player_id: int,
    league: str,
    stat_type: str | None,
):
    """Read the latest canonical row, failing closed on duplicate ownership."""
    predicate, predicate_params = canonical_population_sql(
        league, stat_type
    )
    season_row = connection.execute(
        f"""SELECT MAX(season) FROM player_stats
            WHERE player_id=? AND league=? AND {predicate}""",
        [
            int(player_id), str(league or "").strip().lower(),
            *predicate_params,
        ],
    ).fetchone()
    season = season_row[0] if season_row else None
    if season is None:
        return None
    rows = connection.execute(
        f"""SELECT * FROM player_stats
            WHERE player_id=? AND league=? AND season=? AND {predicate}
            ORDER BY id LIMIT 2""",
        [
            int(player_id), str(league or "").strip().lower(), season,
            *predicate_params,
        ],
    ).fetchall()
    if len(rows) > 1:
        raise LeagueStatContractError(
            "multiple canonical player_stats rows for "
            f"player_id={player_id}, league={league}, "
            f"season={season}, stat_type="
            f"{canonical_stat_type(league, stat_type)}"
        )
    if not rows:
        return None
    player = connection.execute(
        "SELECT name FROM players WHERE id=?",
        (int(player_id),),
    ).fetchone()
    if player is None or rows[0]["player_name"] != player["name"]:
        raise LeagueStatContractError(
            "canonical player_stats display identity disagrees with "
            f"players.id={player_id}"
        )
    return rows[0]


def _table_columns(
    connection: sqlite3.Connection, table: str
) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table})")
    }


def load_unique_source_id_map(
    connection: sqlite3.Connection, *, league: str, id_column: str
) -> tuple[dict[str, int], set[str]]:
    """Load an unambiguous source-ID crosswalk and identify duplicate keys."""
    player_columns = _table_columns(connection, "players")
    if id_column not in player_columns:
        raise LeagueStatContractError(
            f"players is missing source ID column {id_column!r}"
        )
    resolved: dict[str, int] = {}
    ambiguous: set[str] = set()
    rows = connection.execute(
        f"""SELECT id,{id_column} FROM players
            WHERE league=? AND {id_column} IS NOT NULL
              AND CAST({id_column} AS TEXT)!=''
              AND CAST({id_column} AS TEXT)!='0'
            ORDER BY id""",
        (str(league or "").strip().lower(),),
    )
    for row in rows:
        source_key = str(row[id_column])
        if source_key in resolved:
            ambiguous.add(source_key)
        else:
            resolved[source_key] = int(row["id"])
    for source_key in ambiguous:
        resolved.pop(source_key, None)
    return resolved, ambiguous


def queue_unresolved_player(
    connection: sqlite3.Connection,
    *,
    source: str,
    raw_name: str,
    league: str,
    team: str | None,
    source_player_key: str | int | None,
    reason: str,
) -> None:
    """Record an unresolved stable identity without creating a player row."""
    connection.execute(
        """CREATE TABLE IF NOT EXISTS unresolved_players(
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             source TEXT NOT NULL,
             raw_name TEXT NOT NULL,
             league TEXT NOT NULL,
             team TEXT,
             first_seen TEXT NOT NULL,
             count INTEGER DEFAULT 1,
             source_player_key TEXT,
             reason TEXT
           )"""
    )
    columns = _table_columns(connection, "unresolved_players")
    for column in ("source_player_key", "reason"):
        if column not in columns:
            connection.execute(
                f"ALTER TABLE unresolved_players ADD COLUMN {column} TEXT"
            )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS idx_unresolved_players_source_key
           ON unresolved_players(source, league, source_player_key)"""
    )
    normalized_key = (
        str(source_player_key) if source_player_key is not None else None
    )
    existing = connection.execute(
        """SELECT id FROM unresolved_players
           WHERE source=? AND league=?
             AND (
               source_player_key=?
               OR (source_player_key IS NULL AND ? IS NULL)
             )
           ORDER BY id LIMIT 1""",
        (source, league, normalized_key, normalized_key),
    ).fetchone()
    if existing:
        connection.execute(
            """UPDATE unresolved_players
               SET count=count+1,raw_name=?,team=?,reason=?
               WHERE id=?""",
            (raw_name, team, reason, existing["id"]),
        )
        return
    connection.execute(
        """INSERT INTO unresolved_players(
             source,raw_name,league,team,first_seen,count,
             source_player_key,reason
           ) VALUES(?,?,?,?,?,1,?,?)""",
        (
            source, raw_name, league, team,
            datetime.now(timezone.utc).isoformat(),
            normalized_key, reason,
        ),
    )


def publish_player_stats(
    connection: sqlite3.Connection,
    *,
    player_id: int,
    league: str,
    season: int,
    stat_type: str | None,
    source: str,
    games: int | None,
    values: Mapping[str, object],
) -> None:
    """Replace one canonical display row using its stable player identity.

    This deliberately uses delete-then-insert instead of the legacy
    ``INSERT OR REPLACE`` name key. It works before and after the explicit
    canonical-key migration and removes stale competing types for non-MLB
    leagues during their next authoritative refresh.
    """
    normalized_league = str(league or "").strip().lower()
    normalized_type = canonical_stat_type(normalized_league, stat_type)
    normalized_season = int(season)
    if not source_owns_stats(
        normalized_league, normalized_type, normalized_season, source
    ):
        raise LeagueStatContractError(
            f"source {source!r} does not own "
            f"{normalized_league}/{normalized_type}/{normalized_season}"
        )

    player_columns = _table_columns(connection, "players")
    team_expression = "team" if "team" in player_columns else "NULL AS team"
    player = connection.execute(
        f"SELECT id,name,{team_expression},league FROM players WHERE id=?",
        (int(player_id),),
    ).fetchone()
    if player is None:
        raise LeagueStatContractError(
            f"canonical player {player_id} does not exist"
        )
    player_league = str(player["league"]).strip().lower()
    if player_league != normalized_league:
        raise LeagueStatContractError(
            f"canonical player {player_id} belongs to {player_league}, "
            f"not {normalized_league}"
        )

    table_columns = _table_columns(connection, "player_stats")
    required = {
        "player_id", "player_name", "league", "season",
        "stat_type", "source",
    }
    missing = sorted(required - table_columns)
    if missing:
        raise LeagueStatContractError(
            "player_stats is missing canonical columns: "
            + ", ".join(missing)
        )

    protected = {
        "id", "player_id", "player_name", "name_norm", "league",
        "team", "season", "stat_type", "source", "games",
    }
    unknown = sorted(
        key for key in values
        if key in protected or key not in table_columns
    )
    if unknown:
        raise LeagueStatContractError(
            "invalid player_stats values: " + ", ".join(unknown)
        )

    if normalized_league == "mlb":
        connection.execute(
            """DELETE FROM player_stats
               WHERE player_id=? AND league=? AND season=?
                 AND stat_type=?""",
            (
                int(player_id), normalized_league,
                normalized_season, normalized_type,
            ),
        )
    else:
        connection.execute(
            """DELETE FROM player_stats
               WHERE player_id=? AND league=? AND season=?""",
            (int(player_id), normalized_league, normalized_season),
        )

    row = {
        "player_id": int(player_id),
        "player_name": player["name"],
        "league": normalized_league,
        "season": normalized_season,
        "stat_type": normalized_type,
        "source": source,
    }
    if "name_norm" in table_columns:
        row["name_norm"] = normalize_player_name(player["name"])
    if "team" in table_columns:
        row["team"] = player["team"]
    if "games" in table_columns:
        row["games"] = games
    row.update(values)

    columns = list(row)
    placeholders = ",".join("?" for _ in columns)
    connection.execute(
        f"INSERT INTO player_stats ({','.join(columns)}) "
        f"VALUES ({placeholders})",
        [row[column] for column in columns],
    )
