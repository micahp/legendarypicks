#!/usr/bin/env python3
"""_core.py — shared infrastructure for the Legendary Picks sports API.

DB connection + schema, ESPN->DB capture/snapshot helpers, market maps, the
per-league stats fetchers, identity resolution, and the Pydantic request models.
Split out of the old 2125-line sports_service.py god-file (see docs/RETRO-2026-06-27.md).
Routers in routers/ import everything they need via `from _core import *`.
"""
import json
import os, sqlite3, sys, time, datetime as dt
import re, sys, unicodedata
from contextlib import closing
from typing import Optional, Tuple
from fastapi import HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import espn_client as espn
from analytics import ev as ev_mod, clv as clv_mod, calibration as calib_mod, projections as proj_mod
from history_refresh_common import BUSY_TIMEOUT_SECONDS
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
    # `timeout` is SQLite's busy timeout: how long a connection that cannot get the lock
    # keeps retrying before it raises `database is locked`. The default is 5 seconds, and
    # that default is what prod's props ingest was hitting -- the OperationalError came
    # back out of the API as an HTTP 500 and the scraper reported "2 of 14 mlb games
    # failed to POST", every 30 minutes, silently dropping props.
    #
    # This is the API's connection helper, imported by 61 non-test modules, so it is the
    # one place worth fixing rather than the 176 individual connect() sites. WAL (set on
    # the database file itself, not here) removes reader-vs-writer contention; this
    # covers what WAL does not, which is writer-vs-writer. SQLite allows exactly one
    # writer at a time in both modes.
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con = sqlite3.connect(DB, timeout=BUSY_TIMEOUT_SECONDS)
    con.row_factory = sqlite3.Row
    # SQLite defaults foreign_keys OFF, PER CONNECTION. `props.player_id`,
    # `props.game_id` and `prop_results.prop_id` have all DECLARED their
    # references since the schema was written, and none of them had ever fired:
    # only three scripts in this repo set the pragma, and neither the API nor
    # settlement is one of them. A constraint that reads as protection in the
    # schema and enforces nothing is worse than no constraint, because it stops
    # anyone looking.
    #
    # What that cost, found 2026-08-26: 78 props on both databases pointed at 15
    # `players` rows that had been deleted by an identity repair, and 4
    # `prop_results` outlived the props they graded. Nothing raised, nothing
    # counted them. Both databases are at ZERO `PRAGMA foreign_key_check`
    # violations as of that cleanup, so turning this on rejects no existing row.
    #
    # NULL is still allowed: an unresolved prop keeps `player_id IS NULL`, which
    # is the fail-closed path the resolvers already use. What this stops is a
    # non-NULL id pointing at nothing.
    con.execute("PRAGMA foreign_keys=ON")
    return con


def ensure_wal(con):
    """Put the served database in WAL, and report the mode it is actually in.

    WAL is a persistent property of the database FILE, not of a connection, so it
    survives restarts and applies to every process that opens it. That is also the
    hazard: prod was flipped by hand on 2026-08-19, and a restore from a `delete`-mode
    backup would silently put it back without a single line of code changing. Setting
    it here means the API repairs that on startup instead of quietly serving 500s again.

    Under `delete` a writer holds an exclusive lock on the whole database and every
    reader waits. Prod runs API reads, a per-minute `scoreboard_snapshots` writer and a
    30-minute props ingest against one file, so they serialised, the 5s busy timeout
    expired and `database is locked` came back out of the API as an HTTP 500. The
    scraper reported it honestly as "2 of 14 mlb games failed to POST".

    The PRAGMA cannot be forced: if another connection holds a lock, SQLite returns the
    CURRENT mode rather than raising. So this returns what the database is actually in,
    which is the only answer worth having. Callers that care must check the value.
    """
    return str(con.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()


def _init_db():
    with closing(_db()) as con:
        ensure_wal(con)
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
        -- An ESPN event id IS the identity of a game, so two rows carrying one must not
        -- exist. Prod held 59 events across 124 rows, and it was not tidiness: settlement
        -- works one prop_games row at a time, so the props that landed on the second row
        -- were never graded against anything.
        --
        -- Sized honestly, because an earlier version of this comment claimed the duplicates
        -- WERE prod's June hole and that was wrong. Of June's 14,124 unsettled MLB props
        -- (against 693 settled), the partition on 2026-08-17 was: 827 on rows never linked,
        -- 4,467 on linked rows holding no final score, 2,212 on duplicated rows, and 6,618
        -- on rows that are linked, unique, and final -- unexplained by any of this. The
        -- duplicates are 16% of it. Removing them is worth doing on its own terms; it is
        -- not the fix for June.
        --
        -- They arise honestly. prop_games.date comes from a UTC first pitch while ESPN's
        -- scoreboard is keyed by LOCAL date, so one fixture arrives under two calendar
        -- days; the ingest matches on (league, date, home, away) and misses, inserting a
        -- second row; the linker then searches neighbouring slates -- correctly -- and
        -- resolves BOTH to the same event. Nothing in that chain is a bug on its own,
        -- which is why it needs a constraint rather than a fix.
        --
        -- Partial, because a blank event id asserts nothing: unlinked rows are not claims
        -- about identity and several may legitimately share the empty string.
        CREATE UNIQUE INDEX IF NOT EXISTS ux_prop_games_event
          ON prop_games(league, espn_event_id)
          WHERE espn_event_id IS NOT NULL AND espn_event_id != '';
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
        # `pool_key` is a fingerprint of the exact material the served card was
        # written from (the shown items + the editor marks). Without it a run
        # cannot answer "did anything change?", so every run rewrote every card
        # — new title, new prose, same story, and no way to tell a real
        # development from churn (Micah, 2026-08-12: "i hate that the titles and
        # text change for previously generated narratives even when there's no
        # new news"). `newest_item` is the publish timestamp of the freshest
        # item in that pool: what the card's present tense is entitled to.
        _cols = {r[1] for r in con.execute(
            "PRAGMA table_info(news_narratives)").fetchall()}
        for _c in ("pool_key", "newest_item"):
            if _c not in _cols:
                con.execute(
                    "ALTER TABLE news_narratives ADD COLUMN %s TEXT NOT NULL "
                    "DEFAULT ''" % _c)
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


# Feeds whose items are POSTS, not reporting. Nothing here may ever be treated
# as a verified publisher: a tweet carrying a false claim was once read as one
# and served as fact (Micah, 2026-08-12). `x` was missing from this tuple while
# 855 rows carried it, so every one of those tweets counted as published
# reporting. Membership by name is necessary but not sufficient — see
# `ingest_league_narratives.is_social`, which also refuses anything SHAPED like
# a post, so the next feed added does not have to be remembered here to be safe.
SOCIAL_SOURCES = ("bluesky", "x-search", "x", "twitter", "nitter", "mastodon",
                  "threads", "reddit")


# Accounts whose FIRSTHAND posts are reporting, not chatter. Curated BY HAND and
# only by hand (Micah, 2026-08-13) — nothing here is inferred from behaviour,
# volume or engagement, because an automatic route into this table is an
# automatic route into the receipts.
#
# The distinction this table encodes is NOT the platform. Adam Schefter breaking
# a trade on X is the reporting; the ESPN article is downstream of him, and a
# chip reading "Adam Schefter, ESPN" is better provenance than one reading
# `espn.com`, not worse. What earns a place here is an accountable identity —
# a named person, a masthead that employs them, and a reputation that costs them
# when they are wrong. `rawchili` has none of the three.
#
# `outlet=None` means the account is not a named journalist (a league desk, a
# regional news account). Those may still ORIGINATE a claim and carry a card,
# but the chip names the account rather than a person, so a reader can see the
# difference between Ken Rosenthal and an anonymous aggregator.
#
# HARD RULE — this table may only UPGRADE. An account that is absent is treated
# as ordinary voice, never as trusted, so forgetting to add one costs us a
# story and never costs a reader a false receipt. That asymmetry is the whole
# safety argument: `SOCIAL_SOURCES` failed once by MISSING `x` while 855 tweets
# rode through as verified publishers, and the fix is not a better list, it is
# a list whose absent entries fail closed. Corroboration is computed
# independently of this table for the same reason: a wrong entry here still
# cannot make a single-source claim look confirmed.
#
# TODO(micah): confirm the outlets marked (?) before these reach a chip — they
# are displayed to readers and beat moves are not something to guess at.
REPORTER_ROSTER = {
    # handle:        (display name,        outlet,          beat)
    "AdamSchefter":  ("Adam Schefter",     "ESPN",          "nfl"),
    "RapSheet":      ("Ian Rapoport",      "NFL Network",   "nfl"),
    "FieldYates":    ("Field Yates",       "ESPN",          "nfl"),
    "ShamsCharania": ("Shams Charania",    "ESPN",          "nba"),
    "JeffPassan":    ("Jeff Passan",       "ESPN",          "mlb"),
    "Ken_Rosenthal": ("Ken Rosenthal",     "The Athletic",  "mlb"),   # (?)
    "FriedgeHNIC":   ("Elliotte Friedman", "Sportsnet",     "nhl"),
    "TomBogert":     ("Tom Bogert",        "The Athletic",  "mls"),   # (?)
    # Not a named journalist — a Liga MX/CONCACAF desk. Added 2026-08-13 for
    # the Gold Cup/Netflix->CONMEBOL story, which our publisher feeds did not
    # have at all. Originates, so it can carry a card; names itself on the chip.
    "AllFutbolMX":   ("@AllFutbolMX",      None,            "mls"),
}


# ── the LLM call ──────────────────────────────────────────────────────────────
#
# One provider-agnostic chat function. It was `_deepseek_chat` with
# `api.deepseek.com` hardcoded, and on 2026-08-18 that account ran out of
# credit: 2,334 HTTP 402s in seven days, ~2 a minute, and every AI preview,
# recap, news narrative and conversation card went dark. Micah's decision the
# next day was to stop using DeepSeek direct, so the endpoint is now
# configuration and the provider is a chain.
#
# PROVIDERS, in order. First one that can authenticate wins.
#
#   nous        https://inference-api.nousresearch.com/v1   $0.00005 / call
#               The hermes agent's own default. Auth is OAuth, NOT a static
#               key: the bearer token lives in /root/.hermes/auth.json and
#               expires hourly. **We only ever READ that file**, freshly on
#               every call, because the hermes agent is what refreshes it. We
#               do not refresh and we do not write it: it is another process's
#               state, and two writers to one token file is how you get a
#               logged-out agent at 3am.
#
#   openrouter  https://openrouter.ai/api/v1                 $0.0002 / call
#               Static API key, so it works when the OAuth token is stale.
#               4x the price and still a fifth of a cent.
#
# MODEL: `deepseek/deepseek-v4-flash-0731`, dated on purpose. The old code
# asked for `deepseek-v4-pro`, an UNDATED alias, and DeepSeek moved what it
# points at without renaming it. Measured 2026-08-19 on OpenRouter's price
# list, which is the visible edge of that move:
#
#     deepseek-v4-pro         in $1.44/M  out $2.88/M   <- the alias we called
#     deepseek-v4-pro-0813    in $0.66/M  out $1.98/M   <- the dated snapshot
#     deepseek-v4-flash-0731  in $0.14/M  out $0.28/M   <- this
#
# Never ask for an undated alias again. A model name without a date is a
# moving target, and it moved us onto something twice the price.
#
# Quality was measured, not assumed: 3 runs of a real game-story prompt, every
# claim checked against the grounding. flash-0731 invented nothing. Of the
# alternatives, nvidia/nemotron-3.5-lightning was 20x faster (0.6s) but
# contradicted itself inside one blurb (Houston "leads the division" and "sits
# 13 games back"), and liquid/lfm-2.5-2.6b inverted which club led the division
# and flipped the sign of a run differential.
_LLM_MODEL = os.environ.get("LP_LLM_MODEL", "deepseek/deepseek-v4-flash-0731")
_LLM_PROVIDERS = [p.strip() for p in
                  os.environ.get("LP_LLM_PROVIDERS", "nous,openrouter").split(",") if p.strip()]
_HERMES_AUTH = os.environ.get("LP_HERMES_AUTH", "/root/.hermes/auth.json")

# A 401/402/403 is a PERMANENT refusal: the account has no money or no
# permission, and it will not change until a person acts. The old code returned
# None and every caller retried, which is how one dead account produced 2,334
# requests. This is the same rule already written for ESPN's 403 in
# .claude/skills/espn-request-budget §5, finally applied to the LLM path.
_LLM_REFUSED_UNTIL: dict = {}
_LLM_REFUSAL_COOLDOWN = float(os.environ.get("LP_LLM_REFUSAL_COOLDOWN", "3600"))


def _env_key(name: str):
    """A key from the environment, falling back to either .env on this box."""
    v = os.environ.get(name)
    if v:
        return v
    for path in ("/root/legendarypicks/.env", "/root/.hermes/.env"):
        try:
            with open(path) as f:
                for line in f:
                    if line.startswith(name + "="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            continue
    return None


def _deepseek_key():
    """Kept for callers that only want to know whether an LLM is configured."""
    return _env_key("DEEPSEEK_API_KEY")


def _nous_auth():
    """(base_url, bearer) from the hermes agent's token file, or None.

    Read-only and re-read every call, so a token the agent refreshed a minute
    ago is picked up without restarting anything. An expired token is treated
    as "no credential" rather than tried and failed, because a 401 here costs a
    request and tells us what the clock already knew.
    """
    try:
        with open(_HERMES_AUTH) as f:
            n = (json.load(f).get("providers") or {}).get("nous") or {}
        tok = n.get("access_token")
        base = n.get("inference_base_url")
        if not tok or not base:
            return None
        exp = n.get("expires_at")
        if exp:
            import datetime as _dt
            if _dt.datetime.fromisoformat(exp) <= _dt.datetime.now(_dt.timezone.utc):
                return None
        return base, tok
    except Exception:
        return None


def _llm_endpoint(provider: str):
    """(url, headers) for a provider, or None when it has no usable credential."""
    if provider == "nous":
        # A static portal key is preferred when one exists: it does not expire,
        # so this path stops depending on another process keeping a token warm.
        # The OAuth token stays as the fallback for boxes without a key.
        base = os.environ.get("NOUS_BASE_URL") or _env_key("NOUS_BASE_URL") \
            or "https://inference-api.nousresearch.com/v1"
        key = _env_key("NOUS_PORTAL_KEY") or _env_key("NOUS_API_KEY")
        if key:
            return base.rstrip("/") + "/chat/completions", {"Authorization": f"Bearer {key}"}
        got = _nous_auth()
        if not got:
            return None
        base, tok = got
        return base.rstrip("/") + "/chat/completions", {"Authorization": f"Bearer {tok}"}
    if provider == "openrouter":
        key = _env_key("OPENROUTER_API_KEY")
        if not key:
            return None
        return ("https://openrouter.ai/api/v1/chat/completions",
                {"Authorization": f"Bearer {key}"})
    if provider == "deepseek":
        key = _env_key("DEEPSEEK_API_KEY")
        if not key:
            return None
        return ("https://api.deepseek.com/v1/chat/completions",
                {"Authorization": f"Bearer {key}"})
    return None


def _llm_chat(system: str, user: str, max_tokens: int = 8000,
              reasoning: str = None) -> Optional[str]:
    """One chat completion, or None. Never raises: callers are built on None.

    `max_tokens` stays generous because this is a REASONING model and the
    hidden reasoning is billed against the same ceiling. Measured 2026-08-19 on
    the same prompt: at 3000, two of three runs came back with empty content
    and reasoning_tokens equal to the ceiling. At 8000, three of three
    answered. A low ceiling here does not truncate the answer, it deletes it.
    """
    import urllib.request as _u
    payload_body = {
        "model": _LLM_MODEL, "temperature": 0.4, "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
    }
    # Hidden reasoning is billed against max_tokens, so an expensive thinker can
    # spend the ENTIRE ceiling and return empty content. That has now happened
    # three times on three different ceilings: 4000 (discover_topics, 08-17),
    # 3000 and 24000 (both 08-19, the second leaving 1 token for the answer out
    # of 24,000).
    #
    # Our prompts are grounded writing: every fact is handed to the model and
    # the job is selection and phrasing, not derivation. Measured 2026-08-19 on
    # the same game-story prompt, all three outputs factually clean:
    #
    #     default   12.9s   1,252 out   1,126 reasoning
    #     low       10.7s     653 out     503 reasoning
    #     none       3.0s     142 out       0 reasoning
    #
    # So "none" by default: 4x faster, an order of magnitude cheaper, no
    # accuracy cost on this shape of task, and the empty-answer failure becomes
    # structurally impossible. A caller that genuinely needs deliberation (a
    # ranking or a judge) passes reasoning="low"/"high" explicitly.
    effort = reasoning or os.environ.get("LP_LLM_REASONING", "none")
    if effort and effort != "default":
        payload_body["reasoning_effort"] = effort
    body = json.dumps(payload_body).encode()

    tried = []
    for provider in _LLM_PROVIDERS:
        until = _LLM_REFUSED_UNTIL.get(provider, 0)
        if until > time.time():
            tried.append(f"{provider}(refused, {int(until - time.time())}s left)")
            continue
        got = _llm_endpoint(provider)
        if not got:
            tried.append(f"{provider}(no credential)")
            continue
        url, headers = got
        headers = dict(headers)
        headers["Content-Type"] = "application/json"
        # Without a User-Agent the Nous edge answers 403 with Cloudflare error
        # 1010, a browser-signature block. It is not an auth failure and reads
        # exactly like one.
        headers["User-Agent"] = "legendarypicks-backend/1.0"
        req = _u.Request(url, data=body, headers=headers)
        try:
            with _u.urlopen(req, timeout=180) as r:
                payload = json.loads(r.read())
        except Exception as exc:
            code = getattr(exc, "code", None)
            detail = ""
            try:
                detail = " — " + exc.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            if code in (401, 402, 403):
                _LLM_REFUSED_UNTIL[provider] = time.time() + _LLM_REFUSAL_COOLDOWN
                print(f"_llm_chat: {provider} REFUSED us ({code}). This is permanent until "
                      f"someone acts, so it is now skipped for "
                      f"{_LLM_REFUSAL_COOLDOWN / 60:.0f} min rather than retried.{detail}",
                      file=sys.stderr, flush=True)
            else:
                print(f"_llm_chat: {provider} request failed: "
                      f"{type(exc).__name__}: {exc}{detail}", file=sys.stderr, flush=True)
            tried.append(f"{provider}({code or type(exc).__name__})")
            continue
        try:
            choice = payload["choices"][0]
            content = (choice["message"]["content"] or "").strip()
        except Exception as exc:
            print(f"_llm_chat: {provider} unexpected response shape: "
                  f"{type(exc).__name__}: {exc} — keys={list(payload)[:8]}",
                  file=sys.stderr, flush=True)
            tried.append(f"{provider}(bad shape)")
            continue
        if not content:
            usage = payload.get("usage") or {}
            detail = (usage.get("completion_tokens_details") or {})
            print(f"_llm_chat: {provider} EMPTY answer. finish_reason="
                  f"{choice.get('finish_reason')!r} max_tokens={max_tokens} "
                  f"completion_tokens={usage.get('completion_tokens')} "
                  f"reasoning_tokens={detail.get('reasoning_tokens')}. "
                  f"reasoning ~= the ceiling means the budget went entirely to hidden "
                  f"reasoning — RAISE max_tokens.", file=sys.stderr, flush=True)
            tried.append(f"{provider}(empty)")
            continue
        return content

    # Every provider is gone. SAY SO, with which ones and why. A silent None
    # here is what let previews, recaps and narratives sit dark for 17 hours.
    print(f"_llm_chat: no provider answered. Tried: {', '.join(tried) or '(none configured)'}. "
          f"model={_LLM_MODEL}", file=sys.stderr, flush=True)
    return None


# Every caller imports this name. Keep it working, but it no longer names a
# vendor: the provider is configuration now.
_deepseek_chat = _llm_chat


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


_FOLDED_NAME_INDEX = {}


def _folded_name_index(con, league: str) -> dict:
    """{folded_name: [player rows]} for one league, rebuilt when the league changes.

    There is no stored normalized column to index, and adding one would need every writer
    to maintain it -- a second definition of "the same name" that drifts silently, which is
    the defect this exists to fix. So the fold is computed from `players` itself and cached
    per process, stamped with (row count, max id, max updated_at). Any insert, delete or
    rename moves the stamp and the map is rebuilt; a stale map can never outlive a write.

    The API server is long-lived, so the stamp query runs per resolve. It is one aggregate
    over an indexed column, and it is what makes the cache safe to keep.
    """
    has_updated_at = any(
        r[1] == "updated_at" for r in con.execute("PRAGMA table_info(players)"))
    if has_updated_at:
        stamp = tuple(con.execute(
            "SELECT COUNT(*), COALESCE(MAX(id),0), COALESCE(MAX(updated_at),'') "
            "FROM players WHERE league=?", (league,)).fetchone())
        cached = _FOLDED_NAME_INDEX.get(league)
        if cached is not None and cached[0] == stamp:
            return cached[1]
    else:
        # A `players` without updated_at (test fixtures, and any future schema that drops
        # it) gives no signal that a row was RENAMED in place, and a cache that can go
        # stale without knowing it is worse than no cache. Rebuild every call instead.
        stamp = None
    index = {}
    for row in con.execute("SELECT id, name, team FROM players WHERE league=?", (league,)):
        index.setdefault(_normalize_name(row["name"]), []).append(row)
    if stamp is not None:
        _FOLDED_NAME_INDEX[league] = (stamp, index)
    return index


def _resolve_player_for_ingest(con, player_name: str, team: str, league: str, source: str = "props",
                               game_id=None):
    """Resolve a player name to players.id via the identity spine.

    Resolution order (deterministic, NO silent creates):
    1. Exact name + league (fast path for already-matched players)
    2. Normalized name + team + league (deterministic spine match)
    2b. Folded name on both sides + league (diacritics/case/punctuation)
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

    # 2b. Folded name on BOTH sides.
    #
    # Step 2 folds accents off the INCOMING name and then compares it to the stored name
    # unfolded, so `Thomas Muller` from a sportsbook never matches `Thomas Müller` as ESPN
    # publishes him -- and the miss is silent, because a name that resolves to nothing is
    # indistinguishable from a player we do not carry. Measured on the MLS board
    # 2026-08-16: 53 of 74 unresolved names had an exact same-team match in the spine
    # differing only by a diacritic or a capital (Christian Ramírez, Andrés Cubas, Albert
    # Rusnák, Kim Kee-Hee). This is the "ambiguous key never raises -- it MISSES" shape.
    #
    # Deliberately NOT name_alias: that table is for reviewed judgment calls ("Matt" for
    # "Matthew"), and it holds 2 rows. Folding a diacritic is not a judgment call, so it
    # belongs on the deterministic path where every league gets it. Ambiguity is still
    # refused -- _pick_one is the same tiebreak the exact-name path uses.
    cands = _folded_name_index(con, league).get(nname) or []
    if cands:
        picked = _pick_one(cands, nteam, game_teams)
        if picked is not None:
            return (picked, "high")

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


def _snapshot_field(league: str, game_id: str, key: str):
    """One field out of the newest scoreboard snapshot, or None. DB-ONLY.

    The snapshot carries `period`, `clock` and `status_detail` alongside the
    score -- the same values the detail page would otherwise fetch live. Reading
    them here keeps a live game page answerable with zero publisher requests.
    """
    lg = league.lower()
    with closing(_db()) as con:
        row = con.execute(
            "SELECT payload FROM scoreboard_snapshots "
            "WHERE league=? AND game_id=? ORDER BY fetched_at DESC LIMIT 1",
            (lg, game_id),
        ).fetchone()
    if not row:
        return None
    try:
        payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
    except Exception:
        return None
    value = payload.get(key)
    return value if value not in ("", None) else None


def _state_and_score_from_snapshot(league: str, game_id: str):
    """Read state + final score from scoreboard_snapshots, or (None, None).

    DB-ONLY, the same contract as _state_from_db/_final_score_from_db. The
    scoreboard ingest writes a row here for every game it has seen (per-minute
    for live games, once for finished slates), carrying the published state and
    score. That makes it a fallback for games team_game_results has not caught
    up to: a game that finished an hour ago can have a scoreboard snapshot row
    before the season-results ingest has written its team_game_results row.

    This is deliberately the LAST DB source consulted: team_game_results is the
    source of record for finals (it carries every game of the season, not just
    what was on a board), so a contradiction between the two should resolve to
    team_game_results, never to the snapshot.

    Returns (state, {home: int, away: int} | None). state is the snapshot's own
    state string ('pre'/'in'/'post') or None when no row exists.
    """
    lg = league.lower()
    with closing(_db()) as con:
        row = con.execute(
            "SELECT state, payload FROM scoreboard_snapshots "
            "WHERE league=? AND game_id=? ORDER BY fetched_at DESC LIMIT 1",
            (lg, game_id),
        ).fetchone()
    if not row:
        return None, None
    state = row["state"]
    score = None
    # The score is read for ANY state that published one, not just 'post'. The
    # payload shape is identical for a live game -- the 2026-08-26 Leagues Cup
    # snapshot carried home 2, away 0 at Halftime -- and gating on 'post' meant a
    # live game's score was thrown away here and then re-fetched from ESPN by the
    # detail handler, which is a live request for a number already on disk.
    #
    # Callers decide what a score MEANS: game_detail still only promotes it to
    # `final_score` when the state is 'post'.
    if state in ("post", "in"):
        try:
            payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
            home = (payload.get("home") or {}).get("score")
            away = (payload.get("away") or {}).get("score")
            if home is not None and away is not None:
                score = {"home": int(home), "away": int(away)}
        except Exception:
            score = None
    return state, score


def _snapshot_result_info(league: str, game_id: str):
    """Read winner + finish detail from the scoreboard snapshot, or None.

    DB-ONLY, same contract. The scoreboard snapshot carries, per league:

      - UFC:   home/away `winner` flag on every finished fight, plus
               `outcome_method` / `outcome_round` / `outcome_clock` when the
               fight was captured after the finish (code landed 2026-08-19;
               older snapshots lack the outcome fields but keep the winner).
      - soccer (mls/lcup/wc): home/away `winner` flag + `winner_abbrev` +
               `is_draw` + `stage` (et/pens) — the publisher's flag is the
               only honest grade for a shootout final.
      - tennis (atp/wta): `sets` per side; the match winner is whoever won
               more sets.
      - team sports (mlb/nfl/etc.): scores, so the winner is derivable from
               the score — caller should use the score, not this.

    Returns a dict or None:
      {winner_abbrev, winner_name, is_draw, outcome_method, outcome_round,
       outcome_clock, sets: {home: [...], away: [...]}, home_winner, away_winner}
    """
    lg = league.lower()
    with closing(_db()) as con:
        row = con.execute(
            "SELECT payload FROM scoreboard_snapshots "
            "WHERE league=? AND game_id=? ORDER BY fetched_at DESC LIMIT 1",
            (lg, game_id),
        ).fetchone()
    if not row:
        return None
    try:
        payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
    except Exception:
        return None
    home = payload.get("home") or {}
    away = payload.get("away") or {}
    info = {
        "home_winner": home.get("winner"),
        "away_winner": away.get("winner"),
        "winner_abbrev": payload.get("winner_abbrev"),
        "is_draw": payload.get("is_draw"),
        "stage": payload.get("stage"),
        "outcome_method": payload.get("outcome_method") or payload.get("outcomeMethod"),
        "outcome_round": payload.get("outcome_round") or payload.get("outcomeRound"),
        "outcome_clock": payload.get("outcome_clock") or payload.get("outcomeClock"),
        "sets": {
            "home": home.get("sets"),
            "away": away.get("sets"),
        },
        "home_name": home.get("name") or home.get("abbrev"),
        "away_name": away.get("name") or away.get("abbrev"),
    }
    # Winner abbrev: from the publisher flag (soccer), else from the winner flag on
    # a side (UFC), else None. Never guess from score here — caller handles that.
    if info["winner_abbrev"] is None:
        if info["home_winner"] is True:
            info["winner_abbrev"] = home.get("abbrev") or home.get("name")
            info["winner_name"] = home.get("name") or home.get("abbrev")
        elif info["away_winner"] is True:
            info["winner_abbrev"] = away.get("abbrev") or away.get("name")
            info["winner_name"] = away.get("name") or away.get("abbrev")
    if info["winner_abbrev"] is None and info.get("winner_name") is None and not info["is_draw"]:
        # Tennis: no winner flag in the payload; the sets decide.
        hs = home.get("sets") or []
        as_ = away.get("sets") or []
        if hs and as_ and len(hs) == len(as_):
            hw = sum(1 for h, a in zip(hs, as_) if h > a)
            aw = sum(1 for h, a in zip(hs, as_) if a > h)
            if hw > aw:
                info["winner_abbrev"] = home.get("abbrev") or home.get("name")
                info["winner_name"] = home.get("name") or home.get("abbrev")
            elif aw > hw:
                info["winner_abbrev"] = away.get("abbrev") or away.get("name")
                info["winner_name"] = away.get("name") or away.get("abbrev")
    return info


def _context_from_snapshot(league: str, game_id: str):
    """Read home/away team names from scoreboard_snapshots, or None.

    DB-ONLY, same contract. The detail page's score strip needs team names, and
    for a game the boxscore snapshot never captured (MLB etc.), game_context
    has no row — but scoreboard_snapshots always carries the names it saw. This
    lets the page render real teams instead of AWAY/HOME placeholders without
    spending an ESPN request.
    """
    lg = league.lower()
    with closing(_db()) as con:
        row = con.execute(
            "SELECT payload FROM scoreboard_snapshots "
            "WHERE league=? AND game_id=? ORDER BY fetched_at DESC LIMIT 1",
            (lg, game_id),
        ).fetchone()
    if not row:
        return None
    try:
        payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
        home = payload.get("home") or {}
        away = payload.get("away") or {}
        if not home.get("name") and not away.get("name"):
            return None
        return {
            "venue_name": "", "venue_city": "",
            "attendance": None, "officials": [],
            "home_team": home.get("name") or home.get("abbrev") or "",
            "away_team": away.get("name") or away.get("abbrev") or "",
        }
    except Exception:
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


__all__ = [n for n in dir() if not n.startswith("__")]


# Build the DB on import so any router that imports _core has the schema ready.
# Stays here, after every `from core_* import *` above: the extracted modules
# resolve `_db` through this namespace at call time, so the schema must exist
# before the first request, not before the first import.
_init_db()
