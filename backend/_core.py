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
from typing import Optional, Tuple
from fastapi import HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import espn_client as espn
from analytics import ev as ev_mod, clv as clv_mod, calibration as calib_mod, projections as proj_mod
from league_stats import PLAYER_STATS_TABLE_SQL, canonical_player_stats_row
from team_stats_json import stats_to_json
# Extracted from this file, re-exported below so `from _core import *` callers
# are unaffected. _core is the aggregator; these are where the code lives now.
from core_markets import *          # noqa: F401,F403  market -> stat-key maps
from core_player_stats import *     # noqa: F401,F403  per-league stat fetchers
from core_snapshots import *        # noqa: F401,F403  ESPN summary -> our tables
from core_stories import *          # noqa: F401,F403  game previews and recaps

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
          start_time TEXT,
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
        -- Phase 5: identity resolution queue + alias table
        CREATE TABLE IF NOT EXISTS unresolved_players(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source TEXT NOT NULL, raw_name TEXT NOT NULL,
          league TEXT NOT NULL, team TEXT,
          first_seen TEXT NOT NULL, count INTEGER DEFAULT 1,
          source_player_key TEXT, reason TEXT);
        CREATE TABLE IF NOT EXISTS name_alias(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          player_id INTEGER NOT NULL REFERENCES players(id),
          alias_norm TEXT NOT NULL);
        -- v0.6.13: ESPN-published 2026 season projections + board ranks.
        -- One row per (player, season); raw ESPN stat map kept for auditability;
        -- lp_ppr_projected_points computed by the explicit LP PPR formula.
        CREATE TABLE IF NOT EXISTS nfl_player_projections(
          player_id INTEGER NOT NULL,
          espn_id INTEGER NOT NULL,
          season INTEGER NOT NULL,
          scoring_period_id INTEGER NOT NULL DEFAULT 0,
          stat_source_id INTEGER NOT NULL DEFAULT 1,
          stat_split_type_id INTEGER NOT NULL DEFAULT 0,
          raw_projection_json TEXT NOT NULL,
          projected_games INTEGER,
          pass_att REAL, pass_cmp REAL,
          pass_yds REAL, pass_td REAL,
          interceptions REAL,
          rush_att REAL, rush_yds REAL, rush_td REAL,
          receptions REAL, targets REAL,
          rec_yds REAL, rec_td REAL,
          fumbles REAL, fumbles_lost REAL,
          fg_att REAL, fg_made REAL,
          xp_att REAL, xp_made REAL,
          def_td REAL, def_int REAL, def_sack REAL, def_fumble_rec REAL,
          def_points_allowed REAL, def_yds_allowed REAL,
          lp_ppr_projected_points REAL,
          season_outlook TEXT,
          outlook_source TEXT,
          actual_season INTEGER,
          raw_actual_json TEXT,
          actual_qbr REAL,
          actual_passer_rating REAL,
          actual_adj_qbr REAL,
          qbr_source TEXT,
          qbr_payload_checksum TEXT,
          fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
          payload_checksum TEXT,
          PRIMARY KEY (player_id, season));
        """)
        con.execute(PLAYER_STATS_TABLE_SQL)
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
        unresolved_columns = {
            r[1] for r in con.execute("PRAGMA table_info(unresolved_players)").fetchall()
        }
        for col in ("source_player_key", "reason"):
            if col not in unresolved_columns:
                con.execute(f"ALTER TABLE unresolved_players ADD COLUMN {col} TEXT")
        player_stats_columns = {
            r[1] for r in con.execute("PRAGMA table_info(player_stats)").fetchall()
        }
        if "player_id" not in player_stats_columns:
            con.execute("ALTER TABLE player_stats ADD COLUMN player_id INTEGER")
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_unresolved_players_source_key "
            "ON unresolved_players(source, league, source_player_key)"
        )
        # Player search/profile checks data availability on these foreign keys.
        # Without the indexes, a two-letter search can repeatedly scan the full
        # props/stats tables for thousands of historical roster identities.
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_props_player ON props(player_id)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_player_stats_player "
            "ON player_stats(player_id, season)"
        )
        # League news engine: collected out-of-band by ingest_league_news.py,
        # served by routers/news.py. url is the dedupe key (idempotent upsert).
        con.execute("""
        CREATE TABLE IF NOT EXISTS news_items(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          league TEXT NOT NULL,
          layer TEXT NOT NULL,
          source TEXT NOT NULL,
          headline TEXT NOT NULL,
          body TEXT NOT NULL DEFAULT '',
          url TEXT NOT NULL UNIQUE,
          published TEXT NOT NULL DEFAULT '',
          key_player TEXT,
          conv_id TEXT,
          first_seen TEXT NOT NULL DEFAULT (datetime('now')));
        """)
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_news_league_layer "
            "ON news_items(league, layer, published)"
        )
        # AI-generated league conversations (LinkedIn-trending style): one row
        # per CONVERSATION (not per league — each narrative gets to breathe,
        # Micah 2026-08-07), produced by ingest_league_narratives.py from the
        # chatter. `paragraph` is the card's prose — leads with the news anchor
        # and carries the fan voice WITH attribution (\"Fans argue…\", \"Supporters
        # point to…\") so the site never sounds like it is making the fan's claim
        # itself (Micah, 2026-08-07). `narrative`/`fan_voice` stay as structured
        # fields for the future league-summary pass.
        con.execute("""
        CREATE TABLE IF NOT EXISTS news_narratives(
          conv_id TEXT PRIMARY KEY,
          league TEXT NOT NULL,
          title TEXT NOT NULL DEFAULT '',
          narrative TEXT NOT NULL,
          fan_voice TEXT NOT NULL DEFAULT '',
          paragraph TEXT NOT NULL DEFAULT '',
          sources TEXT NOT NULL DEFAULT '[]',
          source_count INTEGER NOT NULL DEFAULT 0,
          generated_at TEXT NOT NULL DEFAULT (datetime('now')));
        """)
        # Run history: EVERY generation is appended here (never overwritten)
        # so versions can be compared and rolled back (Micah, 2026-08-07:
        # "i hope you are saving every single run so we can compare").
        con.execute("""
        CREATE TABLE IF NOT EXISTS news_narratives_runs(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          conv_id TEXT NOT NULL,
          league TEXT NOT NULL,
          title TEXT NOT NULL DEFAULT '',
          narrative TEXT NOT NULL,
          fan_voice TEXT NOT NULL DEFAULT '',
          paragraph TEXT NOT NULL DEFAULT '',
          sources TEXT NOT NULL DEFAULT '[]',
          source_count INTEGER NOT NULL DEFAULT 0,
          generated_at TEXT NOT NULL DEFAULT (datetime('now')));
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_nnruns_conv ON news_narratives_runs(conv_id, generated_at)")
        # Card feedback (audit trail of the user's verdicts on a specific run;
        # Micah 2026-08-09: "i need a way to give it feedback as we go"). A
        # verdict on a run DERIVES labels for the run's cited sources (good ->
        # positives, tangent/bad -> negatives) — see news_feedback.py.
        con.execute("""
        CREATE TABLE IF NOT EXISTS news_card_feedback(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id INTEGER NOT NULL,
          conv_id TEXT NOT NULL,
          verdict TEXT NOT NULL,
          note TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT (datetime('now')));
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_ncfb_run ON news_card_feedback(run_id)")
        # Conversations live in the DB, not in a Python list (Micah 2026-08-10:
        # a topic must not need a code edit). `origin` records where the topic
        # came from — 'dictated' is Micah naming it, and those rows are the
        # POSITIVE exemplars the discovery pass learns "what counts as an
        # important conversation" from. See discover_topics.py.
        con.execute("""
        CREATE TABLE IF NOT EXISTS news_conversations(
          id TEXT PRIMARY KEY,
          league TEXT NOT NULL,
          title TEXT NOT NULL,
          seed TEXT NOT NULL,
          origin TEXT NOT NULL DEFAULT 'dictated',
          active INTEGER NOT NULL DEFAULT 1,
          note TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT (datetime('now')));
        """)
        # Discovered topic candidates awaiting a verdict. A rejected candidate
        # is a NEGATIVE exemplar and is kept forever for exactly that reason —
        # the selector learns the boundary from the contrast, the same way the
        # card feedback loop does.
        con.execute("""
        CREATE TABLE IF NOT EXISTS news_topic_candidates(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          key TEXT NOT NULL,
          league TEXT NOT NULL,
          title TEXT NOT NULL DEFAULT '',
          seed TEXT NOT NULL DEFAULT '',
          rationale TEXT NOT NULL DEFAULT '',
          features TEXT NOT NULL DEFAULT '{}',
          score REAL NOT NULL DEFAULT 0,
          evidence TEXT NOT NULL DEFAULT '[]',
          status TEXT NOT NULL DEFAULT 'proposed',
          note TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          decided_at TEXT);
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_ntc_status ON news_topic_candidates(status, score)")
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


SOCIAL_SOURCES = ("bluesky", "x-search")


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
        WHERE {_OPEN_SNAP.format(col='s.odds')} IS NOT NULL"""


def _ev_inputs(r):
    """Pick the opening-snapshot odds, falling back to props.odds (single)."""
    if r["odds_open"] is not None:
        return r["odds_open"], r["odds_opp_open"], (r["status_open"] or "single")
    if r["prop_odds"] is not None:
        return r["prop_odds"], None, "single"
    return None, None, None


# ── projections-backed fair probability (EV's independent probability source) ──

# Prop market → (stat_json_key, game_log_source_filter).
# Most-recent-first game-log values are pulled, then prob_over(values, line)
# gives the empirical P(over) — an independent fair probability to compare
# against the market-implied probability.

_MLB_MARKET_STAT = {
    "strikeouts":     ("K",            "statcast_pitcher"),
    "outs":           ("outs",         "statcast_pitcher"),
    "hits_allowed":   ("hits_allowed", "statcast_pitcher"),
    "walks":          ("BB",           "statcast_pitcher"),
    "hits":           ("H",            "statcast"),
    "home_runs":      ("HR",           "statcast"),
    "doubles":        ("2B",           "statcast"),
    "total_bases":    ("TB",           "statcast"),
    # earned_runs: not in player_game_logs (Statcast events don't track ERA)
}

# NFL: nflverse source has full box-score per-game aggregates.
# nflverse_pbp is ruled out — abbreviated keys (pass_yds/rec) and missing
# receiving stats entirely. These 5 markets are the ONLY NFL player-prop
# markets bovada_scraper.py currently maps.
_NFL_MARKET_STAT = {
    "passing_yards":   ("passing_yards",   "nflverse"),
    "passing_tds":     ("passing_tds",     "nflverse"),
    "rushing_yards":   ("rushing_yards",   "nflverse"),
    "receiving_yards": ("receiving_yards", "nflverse"),
    "receptions":      ("receptions",      "nflverse"),
}

# NBA: espn source, real JSON keys confirmed: PTS,REB,AST,STL,BLK,TO,3PM.
# MIN/FGM/FGA/FTM/FTA/PRA also present but are not bovada prop markets.
_NBA_MARKET_STAT = {
    "points":    ("PTS", "espn"),
    "rebounds":  ("REB", "espn"),
    "assists":   ("AST", "espn"),
    "threes":    ("3PM", "espn"),
    "blocks":    ("BLK", "espn"),
    "steals":    ("STL", "espn"),
    "turnovers": ("TO",  "espn"),
}

# NHL: nhle.com source, skater stats confirmed: goals,assists,points,shots.
# "saves" is a goalie stat — zero NHL rows have a non-null $.saves key.
# Goalie game logs are not ingested at all; leave "saves" unmapped.
_NHL_MARKET_STAT = {
    "goals":   ("goals",   "nhle.com"),
    "shots":   ("shots",   "nhle.com"),
    "assists": ("assists", "nhle.com"),
}

_LEAGUE_MARKET_STAT = {
    "mlb": _MLB_MARKET_STAT,
    "nfl": _NFL_MARKET_STAT,
    "nba": _NBA_MARKET_STAT,
    "nhl": _NHL_MARKET_STAT,
}

# How many recent games to pull for the empirical distribution.
# 30 days ≈ ~25-30 games for a regular — balances recency vs sample size.
_PROJECTION_WINDOW_GAMES = 30
_PROJECTION_MIN_GAMES = 5


def _query_game_log_values(player_id: int, market: str, line: float, league: str = "mlb") -> Optional[list]:
    """Return game-log stat values for a player+market, most-recent-first.
    Returns None if the market isn't mapped for this league or the player has too few games."""
    league_markets = _LEAGUE_MARKET_STAT.get(league)
    if league_markets is None or market not in league_markets:
        return None
    stat_key, source = league_markets[market]
    with closing(_db()) as con:
        rows = con.execute(
            """SELECT json_extract(stats, ?) AS val
               FROM player_game_logs
               WHERE player_id = ? AND league = ? AND source = ?
                 AND json_extract(stats, ?) IS NOT NULL
               ORDER BY game_date DESC
               LIMIT ?""",
            (f"$.{stat_key}", player_id, league, source, f"$.{stat_key}", _PROJECTION_WINDOW_GAMES),
        ).fetchall()
    vals = [float(r["val"]) for r in rows]
    if len(vals) < _PROJECTION_MIN_GAMES:
        return None
    return vals


def _projected_p_fair(player_id: int, market: str, line: float, league: str = "mlb") -> Optional[Tuple[float, str]]:
    """Return (p_fair, 'projection') from player game logs, or None if insufficient data."""
    vals = _query_game_log_values(player_id, market, line, league)
    if vals is None:
        return None
    result = proj_mod.prob_over(vals, line)
    if result is None:
        return None
    return (result["p_over"], "projection")


def _compute_ev_with_projection(r, player_id: int, market: str, line: float) -> Optional[dict]:
    """EV using the projections-backed fair probability. Falls back to de-vig."""
    odds, odds_opp, status = _ev_inputs(r)
    if odds is None:
        return None

    # Try projections first (independent probability source)
    proj = _projected_p_fair(player_id, market, line, r["league"])
    if proj is not None:
        p_fair, confidence = proj
        d = ev_mod.american_to_decimal(odds)
        return {
            "odds_american": odds,
            "d_decimal": round(d, 4),
            "p_implied": round(ev_mod.implied_prob(odds), 4),
            "p_fair": round(p_fair, 4),
            "ev": round(ev_mod.ev(odds, p_fair), 4),
            "de_vig_confidence": confidence,
        }

    # Fall back to de-vig of market odds
    return ev_mod.compute_ev(odds, odds_opp, status)


def _game_team_abbrevs(con, game_id, league: str) -> set:
    """The two teams of a prop_games row as ESPN abbrevs, or an empty set.

    prop_games writes home/away in two vocabularies — "Los Angeles Dodgers" from the
    Bovada competitor list, "LAD" from other callers — so both are folded through the
    same published map link_prop_games already uses for the ESPN crosswalk.
    """
    if not game_id:
        return set()
    row = con.execute("SELECT home, away FROM prop_games WHERE id=?", (game_id,)).fetchone()
    if not row:
        return set()
    try:
        from link_prop_games import _TEAM_MAPS
    except Exception:
        return set()
    tmap = _TEAM_MAPS.get(league, {})
    out = set()
    for value in (row["home"], row["away"]):
        value = (value or "").strip()
        if value:
            out.add(tmap.get(value.lower(), value.upper()))
    return out


def _pick_one(rows, nteam: str, game_teams: set):
    """Choose a single candidate row, or None when the name stays ambiguous.

    Two same-named players are separated by the team the prop was written for, and
    failing that by which of them is actually IN the game. Neither signal present
    means we do not know, and guessing writes the prop onto the wrong man.
    """
    if len(rows) == 1:
        return rows[0]["id"]
    for probe in ({nteam} if nteam else set(), game_teams):
        if not probe:
            continue
        hits = [r for r in rows if (r["team"] or "").strip().upper() in probe]
        if len(hits) == 1:
            return hits[0]["id"]
    return None


def _resolve_player_for_ingest(con, player_name: str, team: str, league: str, source: str = "props",
                               game_id=None):
    """Resolve a player name to players.id via the identity spine.

    Resolution order (deterministic, NO silent creates):
    1. Exact name + league (fast path for already-matched players)
    2. Normalized name + team + league (deterministic spine match)
    3. name_alias table (known nicknames/alternate spellings)
    4. If nothing matches → write to unresolved_players, return None

    A name that matches more than one row in the league is NOT a match. `game_id`
    is what breaks the tie when the source's team parenthetical is missing or in a
    foreign vocabulary; without it the name goes to the review queue unresolved.

    Returns (player_id, confidence) where confidence is 'high', 'low', or None.
    NEVER inserts a new player — that's the whole point of the spine.
    """
    import re, unicodedata
    from datetime import datetime as _dt, timezone as _tz

    now = _dt.now(_tz.utc).isoformat()
    nname = _normalize_name(player_name)
    nteam = team.strip().upper() if team else ""
    game_teams = _game_team_abbrevs(con, game_id, league)

    # 1. Fast path: exact name + league (already-matched players)
    rows = con.execute(
        "SELECT id, team FROM players WHERE name=? AND league=?",
        (player_name, league)
    ).fetchall()
    if rows:
        picked = _pick_one(rows, nteam, game_teams)
        if picked is not None:
            return (picked, "high")
        # The name exists but points at more than one player. Fall through to the
        # review queue rather than take whichever row SQLite happened to yield.
        rows = []

    # 2. Deterministic: normalized name + team + league
    if nteam:
        cands = con.execute(
            "SELECT id, team FROM players WHERE LOWER(REPLACE(name,'.','')) LIKE ? AND league=? AND UPPER(team)=?",
            (f"%{nname.replace(' ', '%')}%", league, nteam)
        ).fetchall()
        if len(cands) == 1:
            return (cands[0]["id"], "high")

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

        # scoring_plays is populated by the ESPN /boxscore snapshot, which only ever
        # ran for the leagues we capture live: on 2026-08-11 it held mlb/nba/nhl and
        # ZERO rows for ncaaf, nfl and mls. Those three finished-game pages therefore
        # rendered as if the game had not been played — the score was never missing
        # from our data, it was in a table nobody asked.
        #
        # team_game_results carries the finals for every league (score_for /
        # score_against, one row per side). It is the season-results ingest rather
        # than a live capture, so it stays the FALLBACK: scoring_plays is what a
        # live game updates, and a game in progress must not be served a final.
        rows = con.execute(
            "SELECT home_away, score_for, score_against FROM team_game_results "
            "WHERE league=? AND game_id=? AND status='completed' "
            "AND score_for IS NOT NULL AND score_against IS NOT NULL",
            (lg, game_id),
        ).fetchall()
    # Either side answers the whole question, so one surviving row is enough — but
    # read the pair off the side we actually matched, never assume the home row.
    for r in rows:
        if r["home_away"] == "home":
            return {"home": int(r["score_for"]), "away": int(r["score_against"])}
    for r in rows:
        if r["home_away"] == "away":
            return {"home": int(r["score_against"]), "away": int(r["score_for"])}
    return None


def _state_from_db(league: str, game_id: str):
    """Return "post" when OUR DB shows this game finished, else None.

    DB-ONLY, same contract as _final_score_from_db: never touches ESPN on the
    request path. Exists because game state had exactly one source — a live
    espn.game_result() call — so a 403 (routine on this host) downgraded every
    finished game to "not started" on the detail page.

    Deliberately one-way: it can promote an unknown state to "post", never
    demote or invent "in"/"pre". A game still being played has no completed
    team_game_results row, so this cannot label a live game final.
    """
    lg = league.lower()
    with closing(_db()) as con:
        row = con.execute(
            "SELECT 1 FROM team_game_results "
            "WHERE league=? AND game_id=? AND status='completed' LIMIT 1",
            (lg, game_id),
        ).fetchone()
    return "post" if row else None


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


__all__ = [n for n in dir() if not n.startswith("__")]


# Build the DB on import so any router that imports _core has the schema ready.
# Stays here, after every `from core_* import *` above: the extracted modules
# resolve `_db` through this namespace at call time, so the schema must exist
# before the first request, not before the first import.
_init_db()
