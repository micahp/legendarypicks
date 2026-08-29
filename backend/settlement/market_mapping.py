#!/usr/bin/env python3
"""market_mapping.py — canonical market names, aliases, league→stat maps."""
from typing import Dict, Tuple, Optional

# ── Market → ESPN boxscore stat mapping ──────────────────────────
# (league, canonical_market) → (boxscore_category, stat_key)
# Canonical market = normalized form without player name suffix.
# boxscore_category = the statistics category name in ESPN's boxscore JSON
#   (e.g. "batting", "pitching", "defensive", "receiving", "passing", "rushing" etc.)
# stat_key = the field name inside that category (e.g. "SO", "H", "outs", "TB", "2B", "Pts", "Reb")

# ESPN MLB boxscore label sets (used to identify stat group when name is None)
_BATTING_LABELS  = {'AB', 'R', 'H', 'RBI', 'HR', 'BB', 'K', 'AVG', 'OBP', 'SLG', 'H-AB', '#P', 'TB', '2B', '3B', 'SB', 'CS'}
_PITCHING_LABELS = {'IP', 'H', 'R', 'ER', 'BB', 'K', 'HR', 'ERA', 'PC-ST', 'PC', 'SO', 'outs', 'BF'}
# The two sets share {BB, H, HR, K, R}, so membership in either proves nothing. Only
# the labels unique to one group identify it. See test_stat_group_identity.
_BATTING_ONLY = _BATTING_LABELS - _PITCHING_LABELS
_PITCHING_ONLY = _PITCHING_LABELS - _BATTING_LABELS

MARKET_STAT: Dict[Tuple[str, str], Tuple[str, str]] = {
    # ── MLB pitching ──
    ("mlb", "strikeouts"):    ("pitching", "K"),
    ("mlb", "hits_allowed"):  ("pitching", "H"),
    ("mlb", "outs"):          ("pitching", "outs"),
    ("mlb", "earned_runs"):   ("pitching", "ER"),
    ("mlb", "walks"):         ("pitching", "BB"),
    # ── MLB batting ──
    ("mlb", "total_bases"):           ("batting", "TB"),
    ("mlb", "hits_runs_rbis"):        (None, None),  # compound — sum H+R+RBI
    ("mlb", "home_run_any"):          ("batting", "HR"),
    ("mlb", "hit_any"):               ("batting", "H"),
    ("mlb", "rbi_any"):               ("batting", "RBI"),
    ("mlb", "run_any"):               ("batting", "R"),
    ("mlb", "stolen_base_any"):       ("batting", "SB"),
    ("mlb", "double_any"):            ("batting", "2B"),
    ("mlb", "triple_any"):            ("batting", "3B"),
    # ── NBA ──
    ("nba", "points"):        ("offensive", "Pts"),
    ("nba", "rebounds"):      ("offensive", "Reb"),
    ("nba", "assists"):       ("offensive", "Ast"),
    ("nba", "threes"):        ("offensive", "3PT"),
    ("nba", "blocks"):        ("defensive", "Blk"),
    ("nba", "steals"):        ("defensive", "Stl"),
    ("nba", "turnovers"):     ("offensive", "TO"),
    # ── NFL ──
    ("nfl", "passing_yards"): ("passing", "Yds"),
    ("nfl", "passing_tds"):   ("passing", "TD"),
    ("nfl", "rushing_yards"): ("rushing", "Yds"),
    ("nfl", "receiving_yards"):("receiving", "Yds"),
    ("nfl", "receptions"):    ("receiving", "Rec"),
    ("nfl", "tackles"):       ("defensive", "Tkl"),
    ("nfl", "sacks"):         ("defensive", "Sk"),
    ("nfl", "field_goals_made"):("kicking", "FG"),
    # ── NHL ──
    ("nhl", "shots"):         ("offensive", "Shots"),
    ("nhl", "goals"):         ("offensive", "G"),
    ("nhl", "assists"):       ("offensive", "A"),
    ("nhl", "saves"):         ("goalkeeping", "Sv"),
}


def normalize_market(raw_market: str) -> str:
    """Strip player-specific suffix from Bovada-style market names.

    'total_bases___alec_bohm_(phi)' → 'total_bases'
    'total_hits,_runs_and_rbis___bryce_harper_(phi)' → 'total_hits,_runs_and_rbis'
    """
    import re
    # Remove double-underscore player suffix
    m = re.match(r'^(.+?)___.+$', raw_market)
    if m:
        return m.group(1).strip().rstrip('_')
    return raw_market.strip().lower().replace(' ', '_').replace('-', '_')


# Aliases from Bovada's market descriptions → canonical keys
MARKET_ALIASES = {
    "total_bases": "total_bases",
    "total_hits": "hit_any",
    "total_runs": "run_any",
    "total_rbis": "rbi_any",
    "total_doubles": "double_any",  # 2B not in ESPN basic labels — will return None (unmappable without expanded boxscore)
    "total_triples": "triple_any",
    "total_home_runs": "home_run_any",
    "total_stolen_bases": "stolen_base_any",
    "total_hits,_runs_and_rbis": "hits_runs_rbis",
    "total_strikeouts": "strikeouts",
    "total_hits_allowed": "hits_allowed",
    "total_pitcher_outs": "outs",
    "total_pitcher_walks": "walks",
    "total_earned_runs": "earned_runs",
    "total_walks": "walks",
    "total_points": "points",
    "total_rebounds": "rebounds",
    "total_assists": "assists",
    "total_threes": "threes",
    "total_blocks": "blocks",
    "total_steals": "steals",
    "total_turnovers": "turnovers",
    "passing_yards": "passing_yards",
    "passing_tds": "passing_tds",
    "rushing_yards": "rushing_yards",
    "receiving_yards": "receiving_yards",
    "total_receptions": "receptions",
    "total_tackles": "tackles",
    "total_sacks": "sacks",
    "total_shots": "shots",
    "total_goals": "goals",
    "total_saves": "saves",
}


def resolve_market(league: str, raw_market: str) -> Optional[Tuple[str, str]]:
    """Resolve a raw market string → (boxscore_category, stat_key) for the league.
    Returns None if the market can't be mapped (should go to unmappable queue)."""
    canonical = normalize_market(raw_market)
    canonical = MARKET_ALIASES.get(canonical, canonical)
    return MARKET_STAT.get((league, canonical))
