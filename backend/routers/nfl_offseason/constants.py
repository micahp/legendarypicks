"""constants — NFL offseason constants."""
import copy
import datetime as dt
import os
import re
import sqlite3
import threading
import time
from collections import defaultdict
from contextlib import closing
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Sequence, Set, Tuple
from fastapi import APIRouter, HTTPException, Query

_CONTEXT_CONTRACT = "nfl-season-context-v1"

_DRAFT_BOARD_CONTRACT = "nfl-draft-board-v2"

_CURRENT_SEASON = 2026

# Draft board cache — the draft board only changes when nfl_adp, projections,
# or depth chart are re-ingested (daily timers), so a 5-min TTL is safe.
_DRAFT_BOARD_CACHE_TTL = 300

_DRAFT_BOARD_CACHE_MAX_ENTRIES = 64

_DATABASE_TOKEN_MEMO_MAX_ENTRIES = 16

_DRAFT_CACHE_SOURCES = (
    ("players", "league='nfl'", ("updated_at",), ()),
    ("player_game_logs", "league='nfl'", ("ingested_at",), ()),
    (
        "nfl_adp",
        None,
        ("updated_at",),
        ("adp", "percent_owned", "espn_ppr_rank", "espn_standard_rank", "adp_ppr"),
    ),
    (
        "nfl_player_projections",
        None,
        ("fetched_at", "payload_checksum"),
        ("lp_ppr_projected_points", "projected_games"),
    ),
    (
        "nfl_depth_chart",
        None,
        ("ingested_at", "snapshot_at"),
        ("pos_rank",),
    ),
    (
        "nfl_schedule",
        None,
        ("ingested_at",),
        ("season", "week", "away_score", "home_score"),
    ),
    (
        "nfl_dst_stats",
        None,
        (),
        (
            "sacks", "interceptions", "tds", "safeties", "fumble_rec",
            "st_tds", "pr_tds", "points_allowed", "fantasy_pts",
        ),
    ),
    (
        "nfl_snap_counts",
        None,
        (),
        ("off_snaps", "off_pct", "def_snaps", "def_pct", "st_snaps", "st_pct"),
    ),
    (
        "player_stats",
        "league='nfl' AND stat_type='season'",
        (),
        (
            "season", "games", "pass_yds_g", "pass_td", "interceptions",
            "cmp_g", "carries_g", "rush_yds_g", "receptions",
            "rec_yds_g", "targets", "fantasy_ppr_g",
        ),
    ),
)

# Availability's denominator is a constant, not a join. Verified on picks.dev.db:
# in each of 2024 and 2025, all 32 teams played exactly 17 regular-season games,
# across an 18-week schedule with one bye. Deriving it from team_game_results
# instead would drag in ROADMAP B1/B2/B3 (Joe Flacco read 13/34 because a
# mid-season team change summed both teams' seasons) for no gain.
_REG_SEASON_TEAM_GAMES = 17

_REG_SEASON_LAST_WEEK = 18

# Weeks 19-22 are the postseason. Counting them would let a deep playoff run
# report 21/17 games played.
_POSTSEASON_FIRST_WEEK = 19

# Below this, a per-game average is one or two games. xFP predicts better than
# actual points here (r=0.42 vs 0.37 over 2024->2025) but neither is reliable,
# so the surface must mark the sample rather than quietly rank on it.
_THIN_SAMPLE_GAMES = 4

_CALENDAR_VALID_THROUGH = dt.date(2026, 12, 31)

_NFL_CALENDAR_SOURCE = {
    "name": "NFL Football Operations — Important Dates",
    "url": "https://operations.nfl.com/calendar-events/nfl-important-dates",
    "verified_at": "2026-07-21",
}

_NFL_CAMP_SOURCE = {
    "name": "NFL.com — 2026 Training Camp Reporting Dates",
    "url": "https://www.nfl.com/news/2026-nfl-training-camps-report-dates-locations-announced-for-all-32-teams",
    "verified_at": "2026-07-21",
}

_NFL_MILESTONES = (
    ("camp_opens", "Training camps begin opening", dt.date(2026, 7, 17), "training_camp"),
    ("all_teams_report", "All 32 teams in camp", dt.date(2026, 7, 28), "training_camp"),
    ("hall_of_fame_game", "Hall of Fame Game", dt.date(2026, 8, 6), "game"),
    ("preseason_week_1", "First preseason weekend", dt.date(2026, 8, 13), "game"),
    ("preseason_week_2", "Second preseason weekend", dt.date(2026, 8, 20), "game"),
    ("preseason_week_3", "Third preseason weekend", dt.date(2026, 8, 27), "game"),
    ("roster_cutdown", "53-player roster deadline", dt.date(2026, 8, 30), "roster"),
    ("kickoff_weekend", "Kickoff Weekend begins", dt.date(2026, 9, 9), "regular_season"),
)

_SKILL_POSITIONS = ("QB", "RB", "WR", "TE", "FB")

_DEF_POSITION = "DEF"

_FANTASY_DRAFT_POSITIONS = ("QB", "RB", "WR", "TE", "PK", "DEF")

_POSITION_FILTERS = set(_FANTASY_DRAFT_POSITIONS) | {"FLEX"}

# Sort key -> (player field, ascending). Rank and projection come from the
# explicit 2026 ESPN fantasy contract; every missing value remains null and
# sorts after published values.
_SORT_FIELDS = {
    "rank": ("espn_ppr_rank", True),
    "proj": ("proj_ppr_points", False),
    "adp": ("adp", True),
    "ppr_per_team_game": ("ppr_per_team_game", False),
    "ppr_per_game_played": ("ppr_per_game_played", False),
    "xfp_per_game": ("xfp_per_game", False),
    "games_played": ("games_played", False),
    "snap_pct": ("snap_pct", False),
    "target_share": ("target_share", False),
    "dst_pts_per_game": ("dst_pts_per_game", False),
    "pk_pts_per_game": ("pk_pts_per_game", False),
}

# Name search. Bounded so a pathological query cannot turn one request into an
# unbounded pile of LIKE scans.
_SEARCH_MAX_LEN = 64

_SEARCH_MAX_TOKENS = 5

_TRANSACTIONS_CONTRACT = "nfl-transactions-v1"

# ESPN's transaction text always prefixes a player mention with their position
# abbreviation ("WR A.J. Brown", "DE Myles Garrett") — reliable enough to pull
# player names out of free text without a real NLP pass.
_POSITION_PREFIX = re.compile(
    r"\b(?:QB|RB|WR|TE|FB|OL|OT|OG|C|DL|DE|DT|EDGE|LB|CB|S|FS|SS|K|P|LS|NT|DB)\s+"
    r"([A-Z][A-Za-z'.\-]+(?:\s+[A-Z][A-Za-z'.\-]+){0,3})"
)

# Negative lookbehind excludes splitting after a single-capital-letter initial
# ("A.J.", "T.J.") — those periods aren't sentence ends, just part of a name.
_SENTENCE_SPLIT = re.compile(r"(?<![A-Z]\.)(?<=[.!?])\s+(?=[A-Z])")

# A bare trailing period is sentence punctuation, not part of the name — unless
# the name itself legitimately ends in a single-letter initial ("A.J.").
_TRAILING_INITIAL = re.compile(r"\b[A-Z]\.$")

# players/nfl_adp only change via the daily ingest timers now (see
# docs/DATA-FRESHNESS-SPLIT-2026-07-23.md) — no reason to rebuild these two
# full-table dicts (~9.6k players + ~2.5k ADP rows) on every single request.
_SIGNIFICANCE_CACHE_TTL = 300
