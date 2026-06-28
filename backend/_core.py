#!/usr/bin/env python3
"""_core.py — shared infrastructure for the Legendary Picks sports API.

DB connection + schema, ESPN->DB capture/snapshot helpers, market maps, the
per-league stats fetchers, identity resolution, and the Pydantic request models.
Split out of the old 2125-line sports_service.py god-file (see docs/RETRO-2026-06-27.md).
Routers in routers/ import everything they need via `from _core import *`.
"""
import json
import os, sqlite3, datetime as dt
import re, unicodedata
from contextlib import closing
from typing import Optional
from fastapi import HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import espn_client as espn
from analytics import ev as ev_mod, clv as clv_mod, calibration as calib_mod, projections as proj_mod

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")


ALLOWED_ORIGINS = os.environ.get("LP_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:3007").split(",")


def _db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def _init_db():
    with closing(_db()) as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS predictions(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          league TEXT NOT NULL, game_id TEXT NOT NULL, predicted_winner TEXT NOT NULL,
          created_at TEXT NOT NULL, correct INTEGER);
        CREATE TABLE IF NOT EXISTS strength_snap(
          captured_at TEXT NOT NULL, league TEXT NOT NULL, abbrev TEXT NOT NULL,
          win_pct REAL, differential REAL, wins INTEGER, losses INTEGER);
        CREATE TABLE IF NOT EXISTS roster_snap(
          captured_at TEXT NOT NULL, league TEXT NOT NULL, team_abbrev TEXT NOT NULL,
          player_id TEXT NOT NULL, name TEXT, jersey TEXT, position TEXT);
        CREATE TABLE IF NOT EXISTS team_game_stats(
          league TEXT NOT NULL, game_id TEXT NOT NULL, captured_at TEXT NOT NULL,
          team_abbrev TEXT NOT NULL, home_away TEXT NOT NULL,
          fgm_fga TEXT, fg_pct REAL, tpm_tpa TEXT, tp_pct REAL,
          ftm_fta TEXT, ft_pct REAL, rebounds INTEGER, off_rebounds INTEGER,
          def_rebounds INTEGER, assists INTEGER, steals INTEGER, blocks INTEGER,
          turnovers INTEGER, fouls INTEGER, pts_off_to INTEGER,
          fast_break_pts INTEGER, pts_in_paint INTEGER, largest_lead INTEGER,
          lead_changes INTEGER, lead_pct REAL,
          shots INTEGER, blocked_shots INTEGER, hits INTEGER,
          takeaways INTEGER, giveaways INTEGER, faceoffs_won INTEGER,
          faceoff_pct REAL, powerplay_goals INTEGER, powerplay_opps INTEGER,
          powerplay_pct REAL, shorthanded_goals INTEGER,
          penalties INTEGER, penalty_min INTEGER);
        CREATE TABLE IF NOT EXISTS scoring_plays(
          league TEXT NOT NULL, game_id TEXT NOT NULL, play_id TEXT NOT NULL,
          captured_at TEXT NOT NULL, period INTEGER, period_disp TEXT,
          clock TEXT, away_score INTEGER, home_score INTEGER,
          team_abbrev TEXT, scorer_name TEXT, play_text TEXT, play_type TEXT);
        CREATE TABLE IF NOT EXISTS game_context(
          league TEXT NOT NULL, game_id TEXT NOT NULL PRIMARY KEY,
          captured_at TEXT NOT NULL, home_team TEXT, away_team TEXT,
          venue_name TEXT, venue_city TEXT, attendance INTEGER,
          officials TEXT);
        -- Phase 2: prop-outcome data engine
        CREATE TABLE IF NOT EXISTS players(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL, team TEXT, league TEXT NOT NULL,
          espn_id TEXT, mlbam_id INTEGER, nfl_gsis_id TEXT,
          nhl_id INTEGER, nba_id INTEGER,
          active INTEGER DEFAULT 1, position TEXT, updated_at TEXT,
          UNIQUE(espn_id, league));
        CREATE TABLE IF NOT EXISTS prop_games(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          league TEXT NOT NULL, date TEXT NOT NULL,
          home TEXT, away TEXT, espn_event_id TEXT,
          final_home INTEGER, final_away INTEGER);
        CREATE TABLE IF NOT EXISTS props(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          game_id INTEGER REFERENCES prop_games(id),
          player_id INTEGER REFERENCES players(id),
          market TEXT NOT NULL, line REAL NOT NULL, side TEXT NOT NULL,
          source TEXT, captured_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS prop_results(
          prop_id INTEGER PRIMARY KEY REFERENCES props(id),
          actual_value REAL, hit INTEGER, settled_at TEXT);
        CREATE TABLE IF NOT EXISTS player_stats(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          player_name TEXT NOT NULL, league TEXT NOT NULL, team TEXT,
          season INTEGER, games INTEGER,
          pts REAL, reb REAL, ast REAL, stl REAL, blk REAL, tov REAL,
          fgm INTEGER, fga INTEGER, fg3m INTEGER, fg3a INTEGER,
          ftm INTEGER, fta INTEGER, minutes REAL,
          ts_pct REAL, source TEXT,
          UNIQUE(player_name, league, season));
        -- Phase 5: identity resolution queue + alias table
        CREATE TABLE IF NOT EXISTS unresolved_players(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source TEXT NOT NULL, raw_name TEXT NOT NULL,
          league TEXT NOT NULL, team TEXT,
          first_seen TEXT NOT NULL, count INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS name_alias(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          player_id INTEGER NOT NULL REFERENCES players(id),
          alias_norm TEXT NOT NULL);
        """)
        # M6 odds capture: additive schema. CREATE IF NOT EXISTS for the snapshot
        # table, and idempotent ADD COLUMN for props (SQLite has no
        # "ADD COLUMN IF NOT EXISTS", so guard on existing columns).
        con.execute("""
        CREATE TABLE IF NOT EXISTS prop_odds_snapshots(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          prop_id INTEGER NOT NULL REFERENCES props(id),
          side TEXT NOT NULL,
          odds INTEGER NOT NULL,
          odds_opp INTEGER,
          captured_at TEXT NOT NULL,
          is_close INTEGER DEFAULT 0,
          de_vig_status TEXT NOT NULL DEFAULT 'single');
        """)
        existing = {r[1] for r in con.execute("PRAGMA table_info(props)").fetchall()}
        for col, decl in (("odds", "INTEGER"), ("odds_captured_at", "TEXT")):
            if col not in existing:
                con.execute(f"ALTER TABLE props ADD COLUMN {col} {decl}")
        con.commit()


class PredictionIn(BaseModel):
    league: str
    game_id: str
    predicted_winner: str   # team abbreviation, e.g. "MIL"


def _read_game_detail_from_db(lg, game_id, out):
    """Populate out dict with team_stats, scoring_plays, context from DB.
    Returns True if context was populated (game had snapshot data)."""
    with closing(_db()) as con:
        for r in con.execute(
            "SELECT * FROM team_game_stats WHERE league=? AND game_id=? ORDER BY home_away",
            (lg, game_id)
        ).fetchall():
            out["team_stats"].append({
                "team_abbrev": r["team_abbrev"], "home_away": r["home_away"],
                "fgm_fga": r["fgm_fga"], "fg_pct": r["fg_pct"],
                "tpm_tpa": r["tpm_tpa"], "tp_pct": r["tp_pct"],
                "ftm_fta": r["ftm_fta"], "ft_pct": r["ft_pct"],
                "rebounds": r["rebounds"], "off_rebounds": r["off_rebounds"],
                "def_rebounds": r["def_rebounds"], "assists": r["assists"],
                "steals": r["steals"], "blocks": r["blocks"],
                "turnovers": r["turnovers"], "fouls": r["fouls"],
                "fast_break_pts": r["fast_break_pts"], "pts_in_paint": r["pts_in_paint"],
                "largest_lead": r["largest_lead"],
                "shots": r["shots"], "blocked_shots": r["blocked_shots"],
                "hits": r["hits"], "takeaways": r["takeaways"],
                "giveaways": r["giveaways"], "faceoffs_won": r["faceoffs_won"],
                "faceoff_pct": r["faceoff_pct"],
                "powerplay_goals": r["powerplay_goals"], "powerplay_opps": r["powerplay_opps"],
                "penalties": r["penalties"], "penalty_min": r["penalty_min"],
            })
        for r in con.execute(
            "SELECT * FROM scoring_plays WHERE league=? AND game_id=? ORDER BY period, clock",
            (lg, game_id)
        ).fetchall():
            out["scoring_plays"].append({
                "period": r["period"], "period_disp": r["period_disp"],
                "clock": r["clock"], "away_score": r["away_score"],
                "home_score": r["home_score"], "team_abbrev": r["team_abbrev"],
                "play_text": r["play_text"], "play_type": r["play_type"],
            })
        ctx = con.execute(
            "SELECT * FROM game_context WHERE league=? AND game_id=?",
            (lg, game_id)
        ).fetchone()
        if ctx:
            import json
            out["context"] = {
                "venue_name": ctx["venue_name"], "venue_city": ctx["venue_city"],
                "attendance": ctx["attendance"],
                "officials": json.loads(ctx["officials"] or "[]"),
                "home_team": ctx["home_team"], "away_team": ctx["away_team"],
            }
            return True
    return False


_MARKET_STAT_KEY = {
    "mlb": {"total_bases": "TB", "hits": "H", "home_runs": "HR", "walks": "BB",
            "doubles": "2B", "total_doubles": "2B", "triples": "3B", "total_triples": "3B",
            "total_home_runs": "HR", "total_hits": "H", "total_walks": "BB",
            "total_bases_allowed": None,
            # Pitcher markets (ingest_mlb_pitcher_logs.py)
            "strikeouts": "K", "outs": "outs", "hits_allowed": "hits_allowed",
            "pitcher_walks": "BB", "total_pitcher_walks": "BB",
            "earned_runs": "earned_runs"},
    "nba": {"points": "PTS", "rebounds": "REB", "assists": "AST", "threes": "3PM",
            "steals": "STL", "blocks": "BLK", "turnovers": "TO",
            "points_rebounds_assists": "PRA", "pra": "PRA"},
    "nhl": {"goals": "goals", "assists": "assists", "points": "points",
            "shots": "shots", "shots_on_goal": "shots"},
    "nfl": {"passing_yards": "passing_yards", "rushing_yards": "rushing_yards",
            "receiving_yards": "receiving_yards", "receptions": "receptions",
            "passing_tds": "passing_tds", "rushing_tds": "rushing_tds",
            "receiving_tds": "receiving_tds", "interceptions": "interceptions"},
}


def _base_market(m: str) -> str:
    return (m or "").split("___")[0].strip().lower()


def _deepseek_key():
    k = os.environ.get("DEEPSEEK_API_KEY")
    if k:
        return k
    try:  # fall back to the shared .env so the backend works however it was launched
        with open("/root/.hermes/.env") as f:
            for line in f:
                if line.startswith("DEEPSEEK_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"')
    except Exception:
        return None


def _deepseek_chat(system: str, user: str, max_tokens: int = 8000) -> Optional[str]:
    # deepseek-v4-pro is a reasoning model. We let it reason at MAX (reasoning_effort=high)
    # — DeepSeek is cheap, so we never starve the reasoning — and give a big token ceiling
    # so the hidden reasoning + the answer are never truncated (low ceilings → empty content).
    key = _deepseek_key()
    if not key:
        return None
    import urllib.request as _u
    body = json.dumps({
        "model": "deepseek-v4-pro", "temperature": 0.4, "max_tokens": max_tokens,
        "reasoning_effort": "high",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }).encode()
    req = _u.Request("https://api.deepseek.com/v1/chat/completions", data=body,
                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with _u.urlopen(req, timeout=90) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


_OPEN_SNAP = """(SELECT {col} FROM prop_odds_snapshots s
                 WHERE s.prop_id = p.id AND s.side = p.side
                 ORDER BY s.captured_at ASC LIMIT 1)"""


def _analytics_base_sql() -> str:
    return f"""
        SELECT p.id, pl.name AS player_name, pl.id AS player_id, pl.team, pl.league,
               p.market, p.line, p.side, pg.date AS game_date, r.hit,
               {_OPEN_SNAP.format(col='s.odds')} AS odds_open,
               {_OPEN_SNAP.format(col='s.odds_opp')} AS odds_opp_open,
               {_OPEN_SNAP.format(col='s.de_vig_status')} AS status_open,
               p.odds AS prop_odds
        FROM props p
        JOIN players pl ON pl.id = p.player_id
        JOIN prop_games pg ON pg.id = p.game_id
        LEFT JOIN prop_results r ON r.prop_id = p.id
        WHERE 1=1"""


def _ev_inputs(r):
    """Pick the opening-snapshot odds, falling back to props.odds (single)."""
    if r["odds_open"] is not None:
        return r["odds_open"], r["odds_opp_open"], (r["status_open"] or "single")
    if r["prop_odds"] is not None:
        return r["prop_odds"], None, "single"
    return None, None, None


def _normalize_name(name: str) -> str:
    """Normalize player name for matching: lowercase, strip punctuation + suffixes + accents."""
    if not name:
        return ""
    n = name.lower().strip()
    # Strip suffixes
    n = re.sub(r'\b(jr\.?|sr\.?|ii|iii|iv|v)\b', '', n)
    # Strip punctuation
    n = re.sub(r'[^\w\s]', '', n)
    # Strip accents
    n = unicodedata.normalize('NFKD', n).encode('ascii', 'ignore').decode('ascii')
    # Collapse whitespace
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def _get_mlb_stats(player_name: str, player_id: int, statcast_id, now: float):
    """Pull MLB stats from player_stats table (populated by ingest_statcast.py).
    Looks up by player_id first (identity spine), falls back to name_norm for un-backfilled rows."""
    import os, sqlite3 as sq

    try:
        db_path = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
        con = sq.connect(db_path)
        con.row_factory = sq.Row

        # Primary: player_id (identity spine). Fallback: name_norm (un-backfilled rows).
        bat = con.execute(
            "SELECT * FROM player_stats WHERE league='mlb' AND stat_type='batting' AND player_id=? ORDER BY season DESC LIMIT 1",
            (player_id,)
        ).fetchone()
        pit = con.execute(
            "SELECT * FROM player_stats WHERE league='mlb' AND stat_type='pitching' AND player_id=? ORDER BY season DESC LIMIT 1",
            (player_id,)
        ).fetchone()

        # Fallback: name_norm for rows missing player_id (pre-spine data)
        if not bat:
            nname = _normalize_name(player_name)
            bat = con.execute(
                "SELECT * FROM player_stats WHERE league='mlb' AND stat_type='batting' AND name_norm=? ORDER BY season DESC LIMIT 1",
                (nname,)
            ).fetchone()
        if not pit:
            nname = _normalize_name(player_name)
            pit = con.execute(
                "SELECT * FROM player_stats WHERE league='mlb' AND stat_type='pitching' AND name_norm=? ORDER BY season DESC LIMIT 1",
                (nname,)
            ).fetchone()

        if not bat and not pit:
            con.close()
            return {"stats": None, "message": f"No Statcast data for {player_name}. Run ingest_statcast.py to populate."}

        out = {"window": str(bat["season"]) if bat else (str(pit["season"]) if pit else "?"), "batting": None, "pitching": None}

        if bat and bat["avg"] is not None:
            out["batting"] = {
                "avg": bat["avg"], "hr": bat["hr"], "k_pct": bat["k_pct"], "bb_pct": bat["bb_pct"],
                "exit_velo": bat["exit_velo"], "hard_hit_pct": bat["hard_hit_pct"],
                "barrel_pct": bat["barrel_pct"], "launch_angle": bat["launch_angle"],
                "woba": bat["woba"], "xwoba": bat["xwoba"],
            }

        if pit and pit["whiff_pct"] is not None:
            out["pitching"] = {
                "whiff_pct": pit["whiff_pct"], "k_pct": pit["k_pct"],
                "exit_velo_against": pit["exit_velo_against"],
                "barrel_pct_against": pit["barrel_pct_against"],
                "xwoba_against": pit["xwoba_against"],
            }

        con.close()
        return out
    except Exception as e:
        return {"stats": None, "message": f"MLB stats error: {str(e)[:200]}"}


def _get_nfl_stats(player_name: str, player_id: int, now: float):
    """Pull NFL stats from player_stats table (populated by ingest_nfl.py).
    Looks up by player_id first (identity spine), falls back to name_norm for un-backfilled rows."""
    import os, sqlite3 as sq

    try:
        db_path = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
        con = sq.connect(db_path)
        con.row_factory = sq.Row

        # Primary: player_id (identity spine)
        row = con.execute(
            "SELECT * FROM player_stats WHERE league='nfl' AND player_id=? ORDER BY season DESC LIMIT 1",
            (player_id,)
        ).fetchone()

        # Fallback: name_norm for rows missing player_id (pre-spine data)
        if not row:
            nname = _normalize_name(player_name)
            row = con.execute(
                "SELECT * FROM player_stats WHERE league='nfl' AND name_norm=? ORDER BY season DESC LIMIT 1",
                (nname,)
            ).fetchone()

        if not row:
            con.close()
            return {"stats": None, "message": f"No NFL data for {player_name}. Run ingest_nfl.py."}

        out = {
            "window": str(row["season"]),
            "player_name_nfl": row["player_name"],
            "position": row["nfl_position"],
            "team": row["nfl_team"],
            "games": row["games"],
            "source": row["source"] or "nflverse",
            "stats": {
                "passing_yards_pg": row["pass_yds_g"],
                "passing_tds": row["pass_td"],
                "interceptions": row["interceptions"],
                "completions_pg": row["cmp_g"],
                "passing_epa": row["pass_epa"],
                "carries_pg": row["carries_g"],
                "rushing_yards_pg": row["rush_yds_g"],
                "receptions": row["receptions"],
                "receiving_yards_pg": row["rec_yds_g"],
                "targets": row["targets"],
                "fantasy_points_pg": row["fantasy_pts_g"],
                "fantasy_points_ppr_pg": row["fantasy_ppr_g"],
            }
        }
        con.close()
        return out
    except Exception as e:
        return {"stats": None, "message": f"NFL stats error: {str(e)[:200]}"}


def _get_nba_stats(player_name: str, player_id: int, now: float):
    """Pull NBA stats from player_stats table (populated by ingest_hoopR.py).
    Looks up by player_id first (identity spine), falls back to name_norm for un-backfilled rows."""
    import os, sqlite3 as sq

    try:
        db_path = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
        con = sq.connect(db_path)
        con.row_factory = sq.Row

        # Primary: player_id (identity spine)
        row = con.execute(
            "SELECT * FROM player_stats WHERE league='nba' AND player_id=? ORDER BY season DESC LIMIT 1",
            (player_id,)
        ).fetchone()

        # Fallback: name_norm for rows missing player_id (pre-spine data)
        if not row:
            nname = _normalize_name(player_name)
            row = con.execute(
                "SELECT * FROM player_stats WHERE league='nba' AND name_norm=? ORDER BY season DESC LIMIT 1",
                (nname,)
            ).fetchone()

        if not row:
            con.close()
            return {"stats": None, "message": f"Could not find NBA stats for {player_name}. Run ingest_hoopR.py to populate."}

        out = {
            "window": str(row["season"]),
            "player_name_nba": row["player_name"],
            "team": row["team"],
            "games": row["games"],
            "source": row["source"] or "hoopR",
            "stats": {
                "pts": round(float(row["pts"]), 1),
                "reb": round(float(row["reb"]), 1),
                "ast": round(float(row["ast"]), 1),
                "stl": round(float(row["stl"]), 1),
                "blk": round(float(row["blk"]), 1),
                "fg_pct": round(float(row["fgm"]) / float(row["fga"]) * 100, 1) if row["fga"] else 0,
                "fg3_pct": round(float(row["fg3m"]) / float(row["fg3a"]) * 100, 1) if row["fg3a"] else 0,
                "ft_pct": round(float(row["ftm"]) / float(row["fta"]) * 100, 1) if row["fta"] else 0,
                "min_pg": round(float(row["minutes"]), 1) if row["minutes"] else 0,
                "turnovers": round(float(row["tov"]), 1),
                "ts_pct": round(float(row["ts_pct"]), 1),
            }
        }
        con.close()
        return out
    except Exception as e:
        return {"stats": None, "message": f"NBA stats error: {str(e)[:200]}"}


def _get_nhl_stats(player_name: str, player_id: int, now: float):
    """Pull NHL stats from player_stats table (populated by ingest_nhl.py from full rosters).
    Looks up by player_id first (identity spine), falls back to name_norm for un-backfilled rows."""
    import os, sqlite3 as sq

    try:
        db_path = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
        con = sq.connect(db_path)
        con.row_factory = sq.Row

        # Primary: player_id (identity spine)
        row = con.execute(
            "SELECT * FROM player_stats WHERE league='nhl' AND player_id=? ORDER BY season DESC LIMIT 1",
            (player_id,)
        ).fetchone()

        # Fallback: name_norm for rows missing player_id (pre-spine data)
        if not row:
            nname = _normalize_name(player_name)
            row = con.execute(
                "SELECT * FROM player_stats WHERE league='nhl' AND name_norm=? ORDER BY season DESC LIMIT 1",
                (nname,)
            ).fetchone()

        if not row:
            con.close()
            return {"stats": None, "message": f"No NHL data for {player_name}. Run ingest_nhl.py."}

        out = {
            "window": str(row["season"]),
            "player_name_nhl": row["player_name"],
            "position": row["nhl_position"],
            "team": row["nhl_team"],
            "games": row["games"],
            "source": row["source"] or "nhle.com",
            "stats": {
                "goals": row["goals"], "assists": row["assists"], "points": row["points_nhl"],
                "shots": row["shots"], "shooting_pct": row["shooting_pct"],
                "plus_minus": row["plus_minus"], "pim": row["pim"],
                "ppg": row["ppg"], "ppp": row["ppp"], "shg": row["shg"],
                "toi": row["toi"], "faceoff_pct": row["faceoff_pct"],
            }
        }
        con.close()
        return out
    except Exception as e:
        return {"stats": None, "message": f"NHL stats error: {str(e)[:200]}"}


def _resolve_player_for_ingest(con, player_name: str, team: str, league: str, source: str = "props"):
    """Resolve a player name to players.id via the identity spine.

    Resolution order (deterministic, NO silent creates):
    1. Exact name + league (fast path for already-matched players)
    2. Normalized name + team + league (deterministic spine match)
    3. name_alias table (known nicknames/alternate spellings)
    4. If nothing matches → write to unresolved_players, return None

    Returns (player_id, confidence) where confidence is 'high', 'low', or None.
    NEVER inserts a new player — that's the whole point of the spine.
    """
    import re, unicodedata
    from datetime import datetime as _dt, timezone as _tz

    now = _dt.now(_tz.utc).isoformat()
    nname = _normalize_name(player_name)
    nteam = team.strip().upper() if team else ""

    # 1. Fast path: exact name + league (already-matched players)
    row = con.execute(
        "SELECT id FROM players WHERE name=? AND league=?",
        (player_name, league)
    ).fetchone()
    if row:
        return (row["id"], "high")

    # 2. Deterministic: normalized name + team + league
    if nteam:
        row = con.execute(
            "SELECT id FROM players WHERE LOWER(REPLACE(name,'.','')) LIKE ? AND league=? AND UPPER(team)=? LIMIT 1",
            (f"%{nname.replace(' ', '%')}%", league, nteam)
        ).fetchone()
        if row:
            return (row["id"], "high")

    # 3. name_alias lookup
    row = con.execute(
        "SELECT na.player_id FROM name_alias na WHERE na.alias_norm=?",
        (nname,)
    ).fetchone()
    if row:
        # Verify the aliased player is in the right league
        pl = con.execute(
            "SELECT id FROM players WHERE id=? AND league=?",
            (row["player_id"], league)
        ).fetchone()
        if pl:
            return (pl["id"], "high")

    # 4. No match — log to unresolved_players (review queue, never silently drop)
    existing = con.execute(
        "SELECT id, count FROM unresolved_players WHERE raw_name=? AND league=? AND source=?",
        (player_name, league, source)
    ).fetchone()
    if existing:
        con.execute(
            "UPDATE unresolved_players SET count=count+1 WHERE id=?",
            (existing["id"],)
        )
    else:
        con.execute(
            "INSERT INTO unresolved_players(source, raw_name, league, team, first_seen, count) "
            "VALUES (?,?,?,?,?,1)",
            (source, player_name, league, nteam or None, now)
        )

    return (None, None)


class PropIngest(BaseModel):
    league: str
    date: str
    home: str = ""
    away: str = ""
    espn_event_id: str = ""
    props: list  # [{"player_name": str, "team": str, "market": str, "line": float, "side": "over"|"under"}]


class CaptureOddsIn(BaseModel):
    league: str
    props: list


def _evaluate(league, game_id, predicted_winner):
    """True/False vs the REAL final, or None if the game isn't final yet."""
    try:
        res = espn.game_result(league, game_id)
    except ValueError:
        return None
    if res["winner"] is None:
        return None
    return predicted_winner.upper() == res["winner"].upper()


def _final_score_from_db(league: str, game_id: str):
    """Return {home: int, away: int} for a finished game from OUR DB, or None.

    DB-ONLY — never calls ESPN on the request path. Cumulative game scores are
    monotonic non-decreasing, so MAX per side from persisted scoring_plays IS the
    final. The DB is populated by the /boxscore snapshot (backfill / live capture).
    Catching DB gaps against ESPN is an out-of-band job run occasionally — NOT here —
    so serving a page never makes an ESPN round-trip.
    (Do NOT order by `clock`: it is TEXT with mixed formats '8:44' vs '9.4', so a
    string sort picks the wrong play, and the clock counts DOWN anyway.)
    """
    lg = league.lower()
    with closing(_db()) as con:
        row = con.execute(
            "SELECT MAX(home_score) AS home, MAX(away_score) AS away FROM scoring_plays "
            "WHERE league=? AND game_id=?",
            (lg, game_id),
        ).fetchone()
    if row and row["home"] is not None and row["away"] is not None:
        return {"home": int(row["home"]), "away": int(row["away"])}
    return None


def _snapshot_strength(league, rows):
    """Persist a strength snapshot so we accumulate history (the trading side wants the time series)."""
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with closing(_db()) as con:
        con.executemany(
            "INSERT INTO strength_snap(captured_at,league,abbrev,win_pct,differential,wins,losses) "
            "VALUES(?,?,?,?,?,?,?)",
            [(now, league, r["abbrev"], r["win_pct"], r["differential"], r["wins"], r["losses"])
             for r in rows])
        con.commit()


def _parse_int(v):
    try: return int(v)
    except (TypeError, ValueError): return None


def _parse_real(v):
    try: return float(v)
    except (TypeError, ValueError): return None


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _fetch_summary(league, game_id):
    """Raw ESPN summary payload for a single game. Returns the full JSON dict."""
    import json, urllib.request
    _, path = espn._check(league)
    url = f"https://site.api.espn.com/apis/site/v2/sports/{path}/summary?event={game_id}"
    req = urllib.request.Request(url, headers=espn._HDRS)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def _extract_team_stats(league, game_id, summary):
    """Parse boxscore.teams[].statistics[] → list of {team_abbrev, home_away, stats_dict}."""
    bs = summary.get("boxscore", {})
    teams = bs.get("teams", [])
    if not teams:
        # fall back to header
        comp = (summary.get("header", {}).get("competitions") or [{}])[0]
        teams = [{"team": c.get("team", {}),
                   "statistics": [],
                   "_homeAway": c.get("homeAway")}
                  for c in comp.get("competitors", [])]
    out = []
    for t in teams:
        team_info = t.get("team", {})
        abbrev = team_info.get("abbreviation", "")
        home_away = t.get("_homeAway") or t.get("homeAway", "")
        raw = {}
        for s in t.get("statistics", []):
            name = s.get("name")
            if name:
                raw[name] = s.get("displayValue")
        out.append({"team_abbrev": abbrev, "home_away": home_away, "stats": raw})
    return out


def _extract_scoring_plays(league, game_id, summary):
    """Parse plays[] filtered to scoringPlay=true → list of dicts."""
    plays = summary.get("plays", [])
    out = []
    for p in plays:
        if not p.get("scoringPlay"):
            continue
        period = p.get("period", {})
        clock = p.get("clock", {})
        ptype = p.get("type", {})
        # Determine scoring team from text: "[Team] Goal" / "[Player] made..."
        text = p.get("text", "")
        team_abbrev = ""
        scorer = ""
        # Try to extract team from competitors or text pattern
        comp = (summary.get("header", {}).get("competitions") or [{}])[0]
        competitors = comp.get("competitors", [])
        if p.get("homeScore", 0) > p.get("_prev_home", -1) if "_prev_home" in p else (len(out) > 0 and p["homeScore"] > out[-1]["home_score"]):
            # home scored
            for c in competitors:
                if c.get("homeAway") == "home":
                    team_abbrev = c.get("team", {}).get("abbreviation", "")
        elif len(competitors) == 2:
            # away scored (or we guess from context)
            for c in competitors:
                if c.get("homeAway") == "away":
                    team_abbrev = c.get("team", {}).get("abbreviation", "")
        out.append({
            "play_id": str(p.get("id", "")),
            "period": _parse_int(period.get("number")) if period else None,
            "period_disp": period.get("displayValue", "") if period else "",
            "clock": clock.get("displayValue", "") if clock else "",
            "away_score": _parse_int(p.get("awayScore")),
            "home_score": _parse_int(p.get("homeScore")),
            "team_abbrev": team_abbrev,
            "scorer_name": scorer,
            "play_text": text,
            "play_type": ptype.get("text", "") if ptype else "",
        })
    return out


def _extract_game_context(league, game_id, summary):
    """Parse gameInfo + header → {venue_name, venue_city, attendance, officials, home/away}."""
    gi = summary.get("gameInfo", {})
    venue = gi.get("venue", {})
    officials = [o.get("displayName", "") for o in gi.get("officials", [])]
    header = summary.get("header", {})
    comp = (header.get("competitions") or [{}])[0]
    home_team = ""
    away_team = ""
    for c in comp.get("competitors", []):
        ab = c.get("team", {}).get("abbreviation", "")
        if c.get("homeAway") == "home":
            home_team = ab
        else:
            away_team = ab
    import json
    return {
        "venue_name": venue.get("fullName", ""),
        "venue_city": venue.get("address", {}).get("city", ""),
        "attendance": _parse_int(gi.get("attendance")),
        "officials": json.dumps(officials) if officials else "[]",
        "home_team": home_team,
        "away_team": away_team,
    }


def _snapshot_rosters(league, team_abbrev, players):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with closing(_db()) as con:
        con.executemany(
            "INSERT INTO roster_snap(captured_at,league,team_abbrev,player_id,name,jersey,position) "
            "VALUES(?,?,?,?,?,?,?)",
            [(now, league, team_abbrev, p["player_id"], p["name"], p["jersey"], p["position"])
             for p in players])
        con.commit()


def _snapshot_team_game_stats(league, game_id, team_stats_list):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with closing(_db()) as con:
        for t in team_stats_list:
            s = t["stats"]
            con.execute(
                "INSERT OR REPLACE INTO team_game_stats("
                "league,game_id,captured_at,team_abbrev,home_away,"
                "fgm_fga,fg_pct,tpm_tpa,tp_pct,ftm_fta,ft_pct,"
                "rebounds,off_rebounds,def_rebounds,assists,steals,blocks,"
                "turnovers,fouls,pts_off_to,fast_break_pts,pts_in_paint,"
                "largest_lead,lead_changes,lead_pct,"
                "shots,blocked_shots,hits,takeaways,giveaways,faceoffs_won,"
                "faceoff_pct,powerplay_goals,powerplay_opps,powerplay_pct,"
                "shorthanded_goals,penalties,penalty_min"
                ") VALUES(?,?,?,?,?,  ?,?,?,?,?,?,  ?,?,?,?,?,?,  ?,?,?,?,?,  ?,?,?,  ?,?,?,?,?,?,  ?,?,?,?,  ?,?,?)",
                (league, game_id, now, t["team_abbrev"], t["home_away"],
                 s.get("fieldGoalsMade-fieldGoalsAttempted"), _parse_real(s.get("fieldGoalPct")),
                 s.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted"), _parse_real(s.get("threePointFieldGoalPct")),
                 s.get("freeThrowsMade-freeThrowsAttempted"), _parse_real(s.get("freeThrowPct")),
                 _parse_int(s.get("totalRebounds")), _parse_int(s.get("offensiveRebounds")),
                 _parse_int(s.get("defensiveRebounds")), _parse_int(s.get("assists")),
                 _parse_int(s.get("steals")), _parse_int(s.get("blocks")),
                 _parse_int(s.get("turnovers")), _parse_int(s.get("fouls")),
                 _parse_int(s.get("turnoverPoints")), _parse_int(s.get("fastBreakPoints")),
                 _parse_int(s.get("pointsInPaint")), _parse_int(s.get("largestLead")),
                 _parse_int(s.get("leadChanges")), _parse_real(s.get("leadPercentage")),
                 _parse_int(s.get("shotsTotal")), _parse_int(s.get("blockedShots")),
                 _parse_int(s.get("hits")), _parse_int(s.get("takeaways")),
                 _parse_int(s.get("giveaways")), _parse_int(s.get("faceoffsWon")),
                 _parse_real(s.get("faceoffPercent")), _parse_int(s.get("powerPlayGoals")),
                 _parse_int(s.get("powerPlayOpportunities")), _parse_real(s.get("powerPlayPct")),
                 _parse_int(s.get("shortHandedGoals")), _parse_int(s.get("penalties")),
                 _parse_int(s.get("penaltyMinutes"))))
        con.commit()


def _snapshot_scoring_plays(league, game_id, plays):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with closing(_db()) as con:
        con.executemany(
            "INSERT OR IGNORE INTO scoring_plays("
            "league,game_id,play_id,captured_at,period,period_disp,clock,"
            "away_score,home_score,team_abbrev,scorer_name,play_text,play_type"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(league, game_id, p["play_id"], now,
              p["period"], p["period_disp"], p["clock"],
              p["away_score"], p["home_score"], p["team_abbrev"],
              p["scorer_name"], p["play_text"], p["play_type"])
             for p in plays])
        con.commit()


def _snapshot_game_context(league, game_id, ctx):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with closing(_db()) as con:
        con.execute(
            "INSERT OR REPLACE INTO game_context("
            "league,game_id,captured_at,home_team,away_team,"
            "venue_name,venue_city,attendance,officials"
            ") VALUES(?,?,?,?,?,?,?,?,?)",
            (league, game_id, now,
             ctx["home_team"], ctx["away_team"],
             ctx["venue_name"], ctx["venue_city"],
             ctx["attendance"], ctx["officials"]))
        con.commit()


def _snapshot_boxscore_full(league, game_id):
    """One call snapshots team_game_stats + scoring_plays + game_context for a game."""
    try:
        summary = _fetch_summary(league, game_id)
    except Exception:
        return  # game not available yet (pre-game) — silently skip
    team_stats = _extract_team_stats(league, game_id, summary)
    if team_stats:
        _snapshot_team_game_stats(league, game_id, team_stats)
    plays = _extract_scoring_plays(league, game_id, summary)
    if plays:
        _snapshot_scoring_plays(league, game_id, plays)
    ctx = _extract_game_context(league, game_id, summary)
    _snapshot_game_context(league, game_id, ctx)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))


def generate_game_story(lg: str, game_id: str, refresh: bool = False,
                        home: str = None, away: str = None) -> dict:
    """Generate (or fetch cached) the AI matchup blurb for one game, grounded ONLY in
    our records/streaks/form. Shared by the /story endpoint (lazy, on view) and the
    pregenerate_game_stories job (eager, when a game is first discovered).

    home/away (team abbrevs) let the pre-game path work: a scheduled game has no
    `scores` yet, so the team abbrevs come from the scoreboard instead."""
    lg = lg.lower()
    with closing(_db()) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS game_story(
            league TEXT, game_id TEXT, story TEXT, generated_at TEXT,
            PRIMARY KEY(league, game_id))""")
        if not refresh:
            r = con.execute("SELECT story FROM game_story WHERE league=? AND game_id=?", (lg, game_id)).fetchone()
            if r:
                return {"league": lg, "game_id": game_id, "story": r["story"], "cached": True}

    try:
        gr = espn.game_result(lg, game_id)
        teams = list((gr.get("scores") or {}).keys())
    except Exception:
        gr, teams = {}, []
    # Pre-game fallback: a scheduled game has no scores yet — use the scoreboard's
    # home/away abbrevs so we can still write the preview when the game is discovered.
    if len(teams) != 2 and away and home:
        teams = [away, home]
    if len(teams) != 2:
        return {"league": lg, "game_id": game_id, "story": None}
    smap = espn.team_strength_map(lg)

    def facts(ab):
        s = smap.get(ab) or {}
        return (f"{s.get('name', ab)} ({ab}): {s.get('wins')}-{s.get('losses')}, "
                f"{s.get('win_pct')} win%, streak {s.get('streak')}, last-10 {s.get('last10')}, "
                f"differential {s.get('differential')}")
    grounding = (f"Matchup: {teams[0]} vs {teams[1]}. Game state: {gr.get('state')}.\n"
                 f"{facts(teams[0])}\n{facts(teams[1])}")

    form_lines, seen = [], set()
    with closing(_db()) as con:
        prs = con.execute(
            """SELECT pl.id, pl.name, p.market, COUNT(*) c FROM props p
               JOIN prop_games g ON g.id = p.game_id JOIN players pl ON pl.id = p.player_id
               WHERE g.espn_event_id = ? GROUP BY pl.id, p.market ORDER BY c DESC""",
            (str(game_id),)).fetchall()
        for r in prs:
            if r["id"] in seen or len(form_lines) >= 8:
                continue
            sk = _MARKET_STAT_KEY.get(lg, {}).get(_base_market(r["market"]))
            if not sk:
                continue
            logs = con.execute(
                """SELECT stats FROM player_game_logs WHERE player_id=?
                   ORDER BY COALESCE(game_date,'') DESC, CAST(game_no AS INTEGER) DESC LIMIT 5""",
                (r["id"],)).fetchall()
            vals = [json.loads(x["stats"]).get(sk) for x in logs]
            vals = [v for v in vals if v is not None]
            if len(vals) >= 3:
                form_lines.append(f"{r['name']} — last 5 {_base_market(r['market'])}: {vals}")
                seen.add(r["id"])
    if form_lines:
        grounding += "\nRecent player form (most recent first):\n" + "\n".join(form_lines)

    system = ("You are a sharp sports writer. In 2-4 sentences, set up this matchup using ONLY the "
              "facts given. Lead with the most interesting thing — a team streak/record/differential, "
              "OR a player on a clear hot or cold run from the form data. Be specific with numbers. "
              "Do NOT invent injuries, trades, lineup news, or anything not in the facts. No clichés, "
              "no hype, plain confident tone.")
    story = _deepseek_chat(system, grounding)
    if story:
        with closing(_db()) as con:
            con.execute("""CREATE TABLE IF NOT EXISTS game_story(
                league TEXT, game_id TEXT, story TEXT, generated_at TEXT,
                PRIMARY KEY(league, game_id))""")
            con.execute("INSERT OR REPLACE INTO game_story(league, game_id, story, generated_at) "
                        "VALUES (?,?,?,datetime('now'))", (lg, game_id, story))
            con.commit()
    return {"league": lg, "game_id": game_id, "story": story, "cached": False}


import threading as _threading
_story_inflight: set = set()
_story_lock = _threading.Lock()
_story_sema = _threading.Semaphore(3)  # cap concurrent DeepSeek generations

def kick_game_stories(lg: str, games: list):
    """Fire-and-forget: when a league scoreboard is fetched, warm the preview cache
    for any games we don't have a story for yet. Each generation runs in a daemon
    thread (bounded by a semaphore) so the /games response returns immediately and the
    preview is ready — or generating — by the time the user opens the game.

    This is the 'write the preview whenever we find out about the game' hook: games are
    lazy-loaded via /api/{league}/games, so that fetch is exactly when we find out."""
    lg = lg.lower()
    ids = [(str(g.get("game_id")), (g.get("home") or {}).get("abbrev"), (g.get("away") or {}).get("abbrev"))
           for g in (games or []) if g.get("game_id")]
    if not ids:
        return
    gid_list = [i[0] for i in ids]
    try:
        with closing(_db()) as con:
            con.execute("""CREATE TABLE IF NOT EXISTS game_story(
                league TEXT, game_id TEXT, story TEXT, generated_at TEXT,
                PRIMARY KEY(league, game_id))""")
            qs = ",".join("?" * len(gid_list))
            cached = {r[0] for r in con.execute(
                f"SELECT game_id FROM game_story WHERE league=? AND game_id IN ({qs})",
                [lg] + gid_list)}
    except Exception:
        cached = set()
    for gid, home, away in ids:
        if gid in cached:
            continue
        with _story_lock:
            if gid in _story_inflight:
                continue
            _story_inflight.add(gid)
        def _run(gid=gid, home=home, away=away):
            try:
                with _story_sema:
                    generate_game_story(lg, gid, home=home, away=away)
            except Exception as e:
                print(f"[story] bg gen failed {lg} {gid}: {e}")
            finally:
                with _story_lock:
                    _story_inflight.discard(gid)
        _threading.Thread(target=_run, daemon=True).start()


# Build the DB on import so any router that imports _core has the schema ready.
_init_db()

# Export underscore-prefixed helpers too: an explicit __all__ defeats the default
# `import *` hiding of _names, so routers get the verbatim helper bodies under the
# same bare names their route handlers already call.
__all__ = [n for n in dir() if not n.startswith("__")]
