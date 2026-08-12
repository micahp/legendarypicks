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


_MARKET_STAT_KEY = {
    "mlb": {"total_bases": "TB", "hits": "H", "home_runs": "HR", "walks": "BB",
            "doubles": "2B", "total_doubles": "2B", "triples": "3B", "total_triples": "3B",
            "total_home_runs": "HR", "total_hits": "H", "total_walks": "BB",
            "total_bases_allowed": None,
            # compound: sum across 3 stat keys. Real Bovada market string is
            # "total_hits,_runs_and_rbis" (comma + "total_" prefix + spelled-out "and") —
            # mapping under the clean "hits_runs_rbis" name alone never matches what
            # _base_market() actually produces from real prop rows, so the chart silently
            # never fires from the real UI. Keep both keys: the real one so it actually
            # works, the clean one in case a future source names it plainly.
            "total_hits,_runs_and_rbis": ["H", "R", "RBI"],
            "hits_runs_rbis": ["H", "R", "RBI"],
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
    "wc": {"goals": "goals", "assists": "assists", "shots": "shots",
           "shots_on_target": "sot", "shots_on_goal": "sot"},
    # MLS game logs store the same soccer stat shape as WC (goals/assists/shots/sot)
    "mls": {"goals": "goals", "assists": "assists", "shots": "shots",
            "shots_on_target": "sot", "shots_on_goal": "sot"},
    # fight_time (minutes, from round+clock at the ESPN status endpoint -- see
    # ingest_ufc_fight_stats.py) now backfillable same as significant_strikes.
    # finishes/win_by_ko/win_by_submission are win-by-method yes/no props, same
    # category as MLB's home_run_any/hit_any etc — none of those are chartable either,
    # this isn't a new gap. All fall back to "chart not available" via lookup returning None.
    "ufc": {"significant_strikes": "sigStrikesLanded", "fight_time": "fight_time"},
    # Tennis has no game-log ingest — docs/LEAGUE-SOURCES-FIELDS.md "Tennis — Bovada prop markets":
    # charting requires tennis game logs that don't exist, so every market maps to None (the chart
    # lookup returns "market not chartable") until that lands. Never fabricate a stat key.
    # total_sets is a match-level Bovada market (O/U 2.5, no player attribution) deferred from
    # _parse_tennis_props; listed here so the intent is explicit.
    "atp": {"match_winner": None, "total_games": None, "set_betting": None,
            "win_a_set": None, "total_sets": None},
    "wta": {"match_winner": None, "total_games": None, "set_betting": None,
            "win_a_set": None, "total_sets": None},
}


def _base_market(m: str) -> str:
    return (m or "").split("___")[0].strip().lower()


# Sources that are ANONYMOUS chatter, not publishers: they feed the signal but
# are never served on the board and never become a card's receipt.
#
# X is NOT in this list (2026-08-10). Lumping it in with Bluesky meant 401
# collected posts — 126 of them real trades, injuries and staff moves from
# Schefter, Shams, Rapoport and Passan — were displayed nowhere at all. A vetted
# beat reporter is a publisher with a byline and a permalink; a random Bluesky
# account arguing about the cap is signal. Micah, 2026-08-10: "these posts we're
# getting might make more sense for the more news section."
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
    """Pull canonical MLB stats published by ``ingest_statcast.py``."""
    import os, sqlite3 as sq

    try:
        db_path = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
        con = sq.connect(db_path)
        con.row_factory = sq.Row

        bat = canonical_player_stats_row(
            con, player_id=player_id, league="mlb", stat_type="batting"
        )
        pit = canonical_player_stats_row(
            con, player_id=player_id, league="mlb", stat_type="pitching"
        )

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


# player_stats stores every NFL column for every player, zero-filled — a receiver
# carries pass_yds_g 0, a quarterback carries targets 0. Rendering the row whole
# opens a tight end's page on "Pass Yds/G 0 · Pass TDs 0 · INTs 0 · Comp/G 0 ·
# Pass EPA 0 · Carries/G 0", which is the first thing on the page and says nothing.
# Which phases a player participates in is a property of his position, so pick the
# blocks off position and prune values second.
_NFL_STAT_BLOCKS = {
    "passing":   ("passing_yards_pg", "passing_tds", "interceptions",
                  "completions_pg", "passing_epa"),
    "rushing":   ("carries_pg", "rushing_yards_pg"),
    "receiving": ("receptions", "receiving_yards_pg", "targets"),
    "fantasy":   ("fantasy_points_pg", "fantasy_points_ppr_pg"),
}

_NFL_POSITION_BLOCKS = {
    "QB": ("passing", "rushing", "fantasy"),
    "RB": ("rushing", "receiving", "fantasy"),
    "FB": ("rushing", "receiving", "fantasy"),
    "WR": ("receiving", "fantasy"),
    "TE": ("receiving", "fantasy"),
}


def _nfl_stats_for_position(stats: dict, position):
    """Narrow a zero-filled NFL stat row to the phases the position plays.

    Within a kept block a zero is a real number — a quarterback with no
    interceptions has thrown none — so only ``None`` is dropped there. An
    unrecognized position (linemen, kickers, defenders, or a missing value) has no
    known phase, so it falls back to dropping anything empty rather than to
    printing the whole zero-filled row."""
    blocks = _NFL_POSITION_BLOCKS.get(str(position or "").upper().strip())
    if blocks is None:
        return {k: v for k, v in stats.items() if v}
    keep = {k for b in blocks for k in _NFL_STAT_BLOCKS[b]}
    return {k: v for k, v in stats.items() if k in keep and v is not None}


def _get_nfl_stats(player_name: str, player_id: int, now: float):
    """Pull the canonical published NFL regular-season totals."""
    import os, sqlite3 as sq

    try:
        db_path = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
        con = sq.connect(db_path)
        con.row_factory = sq.Row

        row = canonical_player_stats_row(
            con, player_id=player_id, league="nfl", stat_type="season"
        )

        if not row:
            con.close()
            return {"stats": None, "message": f"No NFL data for {player_name}. Run ingest_nfl.py."}

        out = {
            "window": str(row["season"]),
            "player_name_nfl": player_name,
            "position": row["nfl_position"],
            "team": row["nfl_team"],
            "games": row["games"],
            "source": row["source"] or "nflverse",
            "stats": _nfl_stats_for_position({
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
            }, row["nfl_position"]),
        }
        con.close()
        return out
    except Exception as e:
        return {"stats": None, "message": f"NFL stats error: {str(e)[:200]}"}


def _get_nba_stats(player_name: str, player_id: int, now: float):
    """Pull the canonical NBA season row."""
    import os, sqlite3 as sq

    try:
        db_path = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
        con = sq.connect(db_path)
        con.row_factory = sq.Row

        row = canonical_player_stats_row(
            con, player_id=player_id, league="nba", stat_type="season"
        )

        if not row:
            con.close()
            return {
                "stats": None,
                "message": (
                    f"Could not find NBA stats for {player_name}. "
                    "Run the season-appropriate published stats ingest."
                ),
            }

        out = {
            "window": str(row["season"]),
            "player_name_nba": player_name,
            "team": row["team"],
            "games": row["games"],
            # Never default a publisher. A row with no source has no known
            # publisher, and naming one is a claim we cannot support -- the old
            # default said "hoopR" for rows that may never have come from it,
            # and as of 2026-08-05 there are no hoopR rows left at all.
            "source": row["source"] or None,
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
    """Pull NHL's published nhle.com season row."""
    import os, sqlite3 as sq

    try:
        db_path = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
        con = sq.connect(db_path)
        con.row_factory = sq.Row

        row = canonical_player_stats_row(
            con, player_id=player_id, league="nhl", stat_type="season"
        )

        if not row:
            con.close()
            return {"stats": None, "message": f"No NHL data for {player_name}. Run ingest_nhl.py."}

        out = {
            "window": str(row["season"]),
            "player_name_nhl": player_name,
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
    return espn.summary(league, game_id)


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


_TIMESTAMP_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _story_is_stale_preview(generated_at, state, start_time) -> bool:
    """True when a cached story was written BEFORE kickoff and the game has since finished.

    A preview and a recap are different pieces of writing, and the cache could not tell
    them apart: the first story written for a game was final forever, so a game detail page
    kept previewing a match that ended hours ago. There is no column recording which kind a
    row holds, and there does not need to be — a story generated before the opening whistle
    is a preview by construction.

    Both sides are compared in UTC: generated_at is written by SQLite's datetime('now'),
    which is UTC, and ESPN's start time is a Zulu instant."""
    if (state or "").lower() != "post" or not generated_at or not start_time:
        return False
    try:
        written = str(generated_at).strip().replace("T", " ").rstrip("Z")[:16]
        kickoff = str(start_time).strip().replace("T", " ").rstrip("Z")[:16]
        # Both must actually look like timestamps. A lexical compare on anything else is
        # not a time comparison: "12345" sorts before "2026-08-10", which would call a
        # malformed row a stale preview and regenerate it on every single view.
        if not (_TIMESTAMP_PREFIX.match(written) and _TIMESTAMP_PREFIX.match(kickoff)):
            return False
        return written < kickoff
    except Exception:
        return False


def generate_game_story(lg: str, game_id: str, refresh: bool = False,
                        home: str = None, away: str = None,
                        state: str = None, start_time: str = None) -> dict:
    """Generate (or fetch cached) the AI blurb for one game, grounded ONLY in our
    records/streaks/form. Shared by the /story endpoint (lazy, on view) and the
    pregenerate_game_stories job (eager, when a game is first discovered).

    home/away (team abbrevs) let the pre-game path work: a scheduled game has no
    `scores` yet, so the team abbrevs come from the scoreboard instead.

    state/start_time come from the same scoreboard row and cost no extra request. They are
    what lets a preview be replaced by a recap once the game is final — without them the
    behaviour is exactly as before, so every existing caller keeps working."""
    lg = lg.lower()
    cached = None
    stale_preview = False
    with closing(_db()) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS game_story(
            league TEXT, game_id TEXT, story TEXT, generated_at TEXT, has_form INTEGER DEFAULT 0,
            PRIMARY KEY(league, game_id))""")
        cols = [c["name"] for c in con.execute("PRAGMA table_info(game_story)")]
        if "has_form" not in cols:
            con.execute("ALTER TABLE game_story ADD COLUMN has_form INTEGER DEFAULT 0")
            con.commit()
        # has_stakes: story was written WITH the stakes context (stakes.py). A has_form story
        # from before the stakes engine is provisional the same way thin pre-form stories
        # were: regenerate once stakes are computable, then it's final.
        if "has_stakes" not in cols:
            con.execute("ALTER TABLE game_story ADD COLUMN has_stakes INTEGER DEFAULT 0")
            con.commit()
        if not refresh:
            cached = con.execute(
                "SELECT story, has_form, has_stakes, generated_at FROM game_story "
                "WHERE league=? AND game_id=?", (lg, game_id)).fetchone()
            stale_preview = cached and _story_is_stale_preview(
                cached["generated_at"], state, start_time)
            if cached and cached["has_form"] and not stale_preview:
                import stakes as _stakes_mod
                # Final unless this league HAS a stakes model and the story predates it —
                # that one case regenerates once (below) and becomes final with has_stakes=1.
                if cached["has_stakes"] or lg not in _stakes_mod.SUPPORTED:
                    return {"league": lg, "game_id": game_id, "story": cached["story"], "cached": True}

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
        return {"league": lg, "game_id": game_id,
                "story": cached["story"] if cached else None, "cached": bool(cached)}
    smap = espn.team_strength_map(lg)
    try:  # quality rank: position in the strength table (same rows smap is built from)
        _rank = {r["abbrev"]: i + 1 for i, r in enumerate(espn.team_strength(lg))}
    except Exception:
        _rank = {}

    def facts(ab):
        s = smap.get(ab) or {}
        rk = f", quality rank #{_rank[ab]} of {len(_rank)}" if ab in _rank else ""
        return (f"{s.get('name', ab)} ({ab}): {s.get('wins')}-{s.get('losses')}, "
                f"{s.get('win_pct')} win%, streak {s.get('streak')}, last-10 {s.get('last10')}, "
                f"differential {s.get('differential')}{rk}")
    grounding = (f"Matchup: {teams[0]} vs {teams[1]}. Game state: {gr.get('state')}.\n"
                 f"{facts(teams[0])}\n{facts(teams[1])}")

    # THE RESULT. It was never in the grounding — `gr` carried scores and a winner and none
    # of it was passed on, so a finished game's facts said only "state: post". The soccer
    # recaps read fine because matchup_context's form line happens to include the scoreline;
    # MLB has no such line, so the Reds-Nationals recap opened on a prop and never said the
    # Nationals won 7-1. A recap that omits the score is not a recap.
    scores = gr.get("scores") or {}
    if scores and (gr.get("state") or "").lower() == "post":
        line = ", ".join(f"{ab} {int(v) if float(v).is_integer() else v}"
                         for ab, v in scores.items())
        winner = gr.get("winner")
        grounding += (f"\nFINAL SCORE: {line}."
                      + (f" {winner} won." if winner else " The game was drawn."))

    # Stakes: what each team is playing for in THIS game (stakes.py — certain facts only).
    try:
        import stakes as _stakes
        stakes_lines = _stakes.for_matchup(lg, teams[0], teams[1])
    except Exception:
        stakes_lines = []
    if stakes_lines:
        grounding += "\nWhat's at stake in this game:\n" + "\n".join(stakes_lines)

    # Player form, from the prop board first and then from our own game logs.
    #
    # The prop path stays because it is TARGETED: it surfaces the players whose markets we
    # actually price, which is what a reader of this product is looking at. But it was the
    # only path, and props exist for MLB, MLS, UFC and the World Cup — nowhere else. Every
    # NBA, NFL and NHL story was written with an empty form section while 232,669 player
    # game logs sat one table over. player_form reads those directly, keyed on the two
    # clubs, and states the season it read so an out-of-date league (MLS logs stop at 2025)
    # cannot be passed off as current.
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

        if len(form_lines) < 6:
            try:
                import player_form as _pform
                for line in _pform.lines(lg, teams, con=con):
                    if len(form_lines) >= 6:
                        break
                    form_lines.append(line)
            except Exception:
                pass
    if form_lines:
        grounding += "\nRecent player form (most recent first):\n" + "\n".join(form_lines)

    # Matchup context: team form, who is producing, and — for a tournament that pairs two
    # leagues — how those leagues are faring against each other. All of it read off the
    # summary payload this game already fetches. Soccer has no props, so form_lines above
    # is always empty there and a Leagues Cup story was being written from strength ranks
    # alone: "#7 in the 36-team table" instead of "Santos have lost five straight".
    try:
        import matchup_context as _mctx
        context_lines = _mctx.context_lines(
            lg, game_id, state=state or gr.get("state"))
    except Exception:
        context_lines = []
    if context_lines:
        grounding += "\nMatchup context:\n" + "\n".join(context_lines)

    # Settled props are NOT given to the recap writer.
    #
    # They were, briefly, and the rendered page settled the question. The Reds-Nationals
    # recap came out as "CJ Abrams's 0 total bases cashed the under on his 1.5 total bases
    # line, as the Nationals, riding a three-game win streak, faced the Reds" — three prop
    # outcomes and not one mention of the 7-1 result. Handing a writer the most specific
    # numbers in the pile makes it write about them, and a prop is never the biggest thing
    # that happened in a game.
    #
    # The panel below the recap now carries every settled line with its actual value, which
    # is a better home for it: complete rather than a sampled three, and it cannot crowd out
    # the score. Re-enabling is one flag if the recap ever earns it back.
    RECAP_MENTIONS_PROPS = False
    settled_lines = []
    if RECAP_MENTIONS_PROPS and (
            (state or "").lower() == "post" or (gr.get("state") or "").lower() == "post"):
        try:
            with closing(_db()) as con:
                for r in con.execute(
                        """SELECT pl.name, p.market, p.line, p.side, r.actual_value, r.hit
                           FROM props p
                           JOIN prop_games pg ON pg.id = p.game_id
                           JOIN players pl ON pl.id = p.player_id
                           JOIN prop_results r ON r.prop_id = p.id
                           WHERE pg.espn_event_id = ? AND r.hit IS NOT NULL
                           GROUP BY pl.id, p.market, p.side
                           ORDER BY r.hit DESC LIMIT 6""", (str(game_id),)):
                    verdict = "HIT" if r["hit"] else "missed"
                    settled_lines.append(
                        f"{r['name']} {_base_market(r['market'])} {r['side']} {r['line']}: "
                        f"actual {r['actual_value']} — {verdict}.")
        except Exception:
            settled_lines = []
    if settled_lines:
        grounding += ("\nHow our published props landed in this game (state these exactly as "
                      "given; never round or restate a line):\n" + "\n".join(settled_lines))

    # Regenerate a cached story ONLY when genuinely new context arrived since it was written
    # (form for a pre-form story, stakes for a pre-stakes story). Otherwise keep it — never
    # burn an LLM call re-writing the same blurb, and never loop when a source is down.
    if cached:
        new_form = bool(form_lines or context_lines) and not cached["has_form"]
        new_stakes = bool(stakes_lines) and not cached["has_stakes"]
        if not new_form and not new_stakes and not stale_preview:
            return {"league": lg, "game_id": game_id, "story": cached["story"], "cached": True}

    # A finished game gets a recap, not a preview. Without this the writer keeps setting up
    # a match whose result is sitting in the facts it was handed — "Chicago look to advance"
    # under a scoreline that says they already did.
    finished = (state or "").lower() == "post" or (gr.get("state") or "").lower() == "post"
    opening = ("You are a sharp sports writer. This game is OVER — write the recap, in past "
               "tense, using ONLY the facts given. The FINAL SCORE and who won come first; "
               "a recap that does not say who won is not a recap. Then what decided it and "
               "what it changed. "
               if finished else
               "You are a sharp sports writer. Set up this matchup using ONLY the facts given. ")
    system = (opening +
              "Lead priority: (1) what's at stake in this game, (2) a player or team on a clear "
              "hot or cold run, (3) record/quality context, including where these two clubs "
              "sit in the competition. Name the players the facts name. A fact marked "
              "BACKGROUND is true of every game in the competition — it is scenery, not the "
              "story, and belongs in this card only if this game is what changed it. Be "
              "specific with numbers, but NEVER "
              "state the same stat twice in different units, and never pad — if the facts are "
              "thin, one sharp sentence beats four generic ones. 1-4 sentences. Do NOT invent "
              "injuries, trades, lineup news, or anything not in the facts. No clichés, no hype, "
              "plain confident tone.")
    story = _deepseek_chat(system, grounding)
    if story:
        with closing(_db()) as con:
            con.execute("INSERT OR REPLACE INTO game_story(league, game_id, story, generated_at, has_form, has_stakes) "
                        "VALUES (?,?,?,datetime('now'),?,?)",
                        (lg, game_id, story, 1 if (form_lines or context_lines) else 0,
                         1 if stakes_lines else 0))
            con.commit()
    elif cached:
        # generation failed this time — keep the previous story rather than blanking it
        return {"league": lg, "game_id": game_id, "story": cached["story"], "cached": True}
    return {"league": lg, "game_id": game_id, "story": story,
            "cached": False, "has_form": bool(form_lines or context_lines)}


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
    ids = [(str(g.get("game_id")), (g.get("home") or {}).get("abbrev"),
            (g.get("away") or {}).get("abbrev"), g.get("state"), g.get("date"))
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
            cached = {r[0]: r[1] for r in con.execute(
                f"SELECT game_id, generated_at FROM game_story WHERE league=? AND game_id IN ({qs})",
                [lg] + gid_list)}
    except Exception:
        cached = {}
    for gid, home, away, state, start_time in ids:
        # A cached story is enough UNLESS it is a preview of a game that has since ended —
        # then this scoreboard load is exactly when we find out the recap is owed, the same
        # way it is when we first find out the game exists.
        if gid in cached and not _story_is_stale_preview(cached[gid], state, start_time):
            continue
        with _story_lock:
            if gid in _story_inflight:
                continue
            _story_inflight.add(gid)
        def _run(gid=gid, home=home, away=away, state=state, start_time=start_time):
            try:
                with _story_sema:
                    generate_game_story(lg, gid, home=home, away=away,
                                        state=state, start_time=start_time)
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
