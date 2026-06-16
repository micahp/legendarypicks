#!/usr/bin/env python3
"""
settlement.py — Prop settlement pipeline: grade props against per-game box scores.

Phase 1: market→stat mapping + single-game settler.
Phase 2: driver + backfill (see settle_props.py).
Phase 3: read-side wired through sports_service.py's existing /api/props/stats + /performance.

CRITICAL: settlement uses per-GAME box-score stats (espn.boxscore), NOT season aggregates
from player_stats. A prop is graded against what that player did in THAT specific game.
"""
import os, sqlite3, datetime as dt, re, json
from typing import Optional, Dict, Tuple, List

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

# ── Market → ESPN boxscore stat mapping ──────────────────────────
# (league, canonical_market) → (boxscore_category, stat_key)
# Canonical market = normalized form without player name suffix.
# boxscore_category = the statistics category name in ESPN's boxscore JSON
#   (e.g. "batting", "pitching", "defensive", "receiving", "passing", "rushing" etc.)
# stat_key = the field name inside that category (e.g. "SO", "H", "outs", "TB", "2B", "Pts", "Reb")

# ESPN MLB boxscore label sets (used to identify stat group when name is None)
_BATTING_LABELS  = {'AB', 'R', 'H', 'RBI', 'HR', 'BB', 'K', 'AVG', 'OBP', 'SLG', 'H-AB', '#P', 'TB', '2B', '3B', 'SB', 'CS'}
_PITCHING_LABELS = {'IP', 'H', 'R', 'ER', 'BB', 'K', 'HR', 'ERA', 'PC-ST', 'PC', 'SO', 'outs', 'BF'}

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


def _find_player_stat(boxscore: dict, player_name: str, team: str,
                       category: str, stat_key: str) -> Optional[float]:
    """Extract a single stat for a player from ESPN's boxscore JSON.

    The ESPN boxscore structure:
      boxscore.players[team_abbrev] = {
        "team": {...},
        "statistics": [{"name": "batting", "athletes": [
          {"athlete": {"displayName": ...}, "stats": ["AB", "R", "H", ...]},
          ...
        ]}]
      }
    Returns the stat value as float, or None if player not found / DNP.
    """
    if not boxscore:
        return None
    players = boxscore.get("players", [])
    if not players:
        return None

    # Team abbreviation aliases (ESPN sometimes uses different abbrevs than our data)
    _TEAM_ALIASES = {
        "WAS": "WSH", "WSH": "WAS",  # Washington
        "ATH": "OAK", "OAK": "ATH",  # Athletics
        "LAL": "LAL", "LAC": "LAC",  # LA teams
        "TB": "TB", "TBL": "TB",     # Tampa Bay
        "ARI": "ARI", "AZ": "ARI",   # Arizona
    }

    # players is a list of team groups: [{"team": {"abbreviation": "PHI"}, "statistics": [...]}, ...]
    for team_group in players:
        tg_team = (team_group.get("team") or {}).get("abbreviation", "")
        # Match by team abbreviation (case-insensitive, with aliases)
        tg_upper = tg_team.upper()
        team_upper = team.upper()
        if tg_upper != team_upper and _TEAM_ALIASES.get(tg_upper) != team_upper:
            # Also try displayName / shortDisplayName
            tg_name = (team_group.get("team") or {}).get("displayName", "")
            tg_short = (team_group.get("team") or {}).get("shortDisplayName", "")
            if team.upper() not in (tg_upper, tg_name.upper(), tg_short.upper()):
                continue

        for stats_group in team_group.get("statistics", []):
            # ESPN sometimes returns name=None for stat groups.
            # Identify by labels: batting has AB/H/RBI/HR, pitching has IP/ER/BB
            stats_name = (stats_group.get("name") or "")
            labels = stats_group.get("labels") or []
            label_set = set(labels)
            category_norm = (category or "").lower().replace(" ", "_")

            if category is not None:
                if stats_name:
                    # Named stat group — match by name
                    if stats_name.lower().replace(" ", "_") != category_norm:
                        continue
                else:
                    # Unnamed — identify by labels
                    if category_norm in ("batting", "offensive") and not (label_set & _BATTING_LABELS):
                        continue
                    if category_norm == "pitching" and not (label_set & _PITCHING_LABELS):
                        continue

            for athlete_entry in stats_group.get("athletes", []):
                athlete = athlete_entry.get("athlete", {})
                display_name = (athlete.get("displayName") or "").strip()
                # Match by display name (case-insensitive subset match)
                if player_name.lower() not in display_name.lower():
                    # Also try last-name match
                    pn_parts = player_name.strip().split()
                    if len(pn_parts) >= 2:
                        last = pn_parts[-1].lower()
                        if last not in display_name.lower():
                            continue
                    else:
                        continue

                # Found the player — extract the stat
                stats_list = athlete_entry.get("stats", [])
                labels = stats_group.get("labels") or []
                if isinstance(stats_list, list) and len(stats_list) > 0:
                    # Compute TB from SLG * AB if not directly in labels
                    if stat_key == "TB" and "TB" not in labels and "SLG" in labels and "AB" in labels:
                        try:
                            slg_idx = labels.index("SLG")
                            ab_idx = labels.index("AB")
                            slg = float(stats_list[slg_idx]) if stats_list[slg_idx] not in (None, "") else 0.0
                            ab = float(stats_list[ab_idx]) if stats_list[ab_idx] not in (None, "") else 0.0
                            return round(slg * ab)
                        except (ValueError, TypeError, IndexError):
                            pass

                    # Compute 2B similarly if not available
                    if stat_key == "2B" and "2B" not in labels:
                        return None  # can't compute without expanded boxscore

                    # Standard label-based lookup
                    if labels and stat_key in labels:
                        idx = labels.index(stat_key)
                        if idx < len(stats_list):
                            val = stats_list[idx]
                            try:
                                return float(val) if val not in (None, "") else 0.0
                            except (ValueError, TypeError):
                                return 0.0
                return 0.0
    return None


def _find_player_compound_stat(boxscore: dict, player_name: str, team: str,
                                categories: List[str], stat_keys: List[str]) -> Optional[float]:
    """Sum multiple stats across categories (e.g. hits_runs_rbis = H + R + RBI)."""
    total = 0.0
    found_any = False
    for cat, key in zip(categories, stat_keys):
        val = _find_player_stat(boxscore, player_name, team, cat, key)
        if val is not None:
            total += val
            found_any = True
    return total if found_any else None


def settle_game(con: sqlite3.Connection, game_id: int) -> dict:
    """Settle all unsettled props for one prop_games row.

    Pulls the ESPN boxscore for the game, resolves each prop's market,
    finds the player's actual stat, grades over/under, writes prop_results.

    Returns: {settled: N, void: N, unmappable: N, errors: N}
    Idempotent: skips props that already have a prop_results row.
    """
    import espn_client as espn

    game = con.execute(
        "SELECT id, league, home, away, espn_event_id, final_home, final_away FROM prop_games WHERE id=?",
        (game_id,)
    ).fetchone()
    if not game:
        return {"settled": 0, "void": 0, "unmappable": 0, "errors": 1, "error_msg": "game not found"}

    league = game["league"]
    espn_event_id = game["espn_event_id"]
    if not espn_event_id:
        return {"settled": 0, "void": 0, "unmappable": 0, "errors": 0,
                "msg": f"game {game_id}: no espn_event_id, cannot pull boxscore"}

    # Ensure game is final
    if game["final_home"] is None:
        # Try to get final from ESPN
        try:
            result = espn.game_result(league, espn_event_id)
            if result["state"] != "post" or result["winner"] is None:
                return {"settled": 0, "void": 0, "unmappable": 0, "errors": 0,
                        "msg": f"game {game_id}: not final yet (state={result['state']})"}
            # Update final scores in DB
            con.execute(
                "UPDATE prop_games SET final_home=?, final_away=? WHERE id=?",
                (result["scores"].get(game["home"]), result["scores"].get(game["away"]), game_id))
            con.commit()
        except Exception as e:
            return {"settled": 0, "void": 0, "unmappable": 0, "errors": 1,
                    "error_msg": f"game {game_id}: ESPN pull failed: {e}"}

    # Pull boxscore
    try:
        box = espn.boxscore(league, espn_event_id)
    except Exception as e:
        return {"settled": 0, "void": 0, "unmappable": 0, "errors": 1,
                "error_msg": f"game {game_id}: boxscore pull failed: {e}"}

    if not box:
        return {"settled": 0, "void": 0, "unmappable": 0, "errors": 1,
                "error_msg": f"game {game_id}: empty boxscore returned"}

    # Find unsettled props for this game
    props = con.execute("""
        SELECT p.id, p.market, p.line, p.side, p.player_id, pl.name as player_name, pl.team as player_team
        FROM props p
        JOIN players pl ON pl.id = p.player_id
        LEFT JOIN prop_results pr ON pr.prop_id = p.id
        WHERE p.game_id = ? AND pr.prop_id IS NULL
    """, (game_id,)).fetchall()

    settled = 0
    void = 0
    unmappable = 0
    errors = 0
    now = dt.datetime.now(dt.timezone.utc).isoformat()

    for prop in props:
        mapping = resolve_market(league, prop["market"])
        if mapping is None:
            unmappable += 1
            continue

        category, stat_key = mapping

        # Handle compound stats
        if category is None and stat_key is None:
            if "hits_runs_rbis" in normalize_market(prop["market"]):
                actual = _find_player_compound_stat(
                    box, prop["player_name"], prop["player_team"],
                    ["batting", "batting", "batting"], ["H", "R", "RBI"])
            else:
                unmappable += 1
                continue
        else:
            actual = _find_player_stat(
                box, prop["player_name"], prop["player_team"],
                category, stat_key)

        # Void: player DNP or stat not found
        if actual is None:
            void += 1
            continue

        # Grade
        line = prop["line"]
        side = (prop["side"] or "").lower()
        if side == "over":
            hit = 1 if actual > line else (0 if actual < line else None)  # None = push
        elif side == "under":
            hit = 1 if actual < line else (0 if actual > line else None)
        else:
            unmappable += 1
            continue

        try:
            con.execute(
                "INSERT INTO prop_results(prop_id, actual_value, hit, settled_at) VALUES (?,?,?,?)",
                (prop["id"], actual, hit, now))
            settled += 1
        except Exception as e:
            errors += 1

    con.commit()
    return {"settled": settled, "void": void, "unmappable": unmappable, "errors": errors}


if __name__ == "__main__":
    # Quick self-test: resolve some markets
    tests = [
        ("mlb", "total_strikeouts", "strikeouts"),
        ("mlb", "total_bases___alec_bohm_(phi)", "total_bases"),
        ("mlb", "total_hits,_runs_and_rbis___bryce_harper_(phi)", "hits_runs_rbis"),
        ("nba", "total_points", "points"),
    ]
    print("Market resolution tests:")
    for league, raw, expected_canonical in tests:
        mapping = resolve_market(league, raw)
        canonical = normalize_market(raw)
        canonical = MARKET_ALIASES.get(canonical, canonical)
        status = "✅" if canonical == expected_canonical else "❌"
        print(f"  {status} {raw!r} → canonical={canonical!r} mapping={mapping}")
