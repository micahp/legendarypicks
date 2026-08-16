#!/usr/bin/env python3
"""
settlement.py — Prop settlement pipeline: grade props against per-game box scores.

Phase 1: market→stat mapping + single-game settler.
Phase 2: driver + backfill (see settle_props.py).
Phase 3: read-side wired through sports_service.py's existing /api/props/stats + /performance.

CRITICAL: settlement uses per-GAME box-score stats (espn.boxscore), NOT season aggregates
from player_stats. A prop is graded against what that player did in THAT specific game.
"""
import os, sqlite3, datetime as dt, re, json, unicodedata
from typing import Optional, Dict, Tuple, List

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

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


def _norm_name(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace — so "Michael Porter Jr."
    and "michael porter jr" are the same name and nothing else is."""
    return " ".join("".join(c for c in (text or "").lower() if c.isalnum() or c.isspace()).split())


def _find_player_stat(boxscore: dict, player_name: str, team: str,
                       category: str, stat_key: str,
                       espn_id: Optional[str] = None) -> Optional[float]:
    """Extract a single stat for a player from ESPN's boxscore JSON.

    Identity, exact key first — ESPN publishes `athlete.id` on the same object as
    the stats, so there is no name to match:

      1. `espn_id` against `athlete.id`. Absent from the box score means the player
         did not appear: a void, not a licence to guess.
      2. No espn_id on our row: exact name match after normalising case,
         punctuation and whitespace.
      3. Two athletes answering to the same name: void.

    This used to accept a SUBSTRING of the display name and, failing that, the
    player's LAST TOKEN anywhere in it. For "Michael Porter Jr." that token is
    "jr.", which matches the first suffixed athlete on the team — 1,568 players
    have a suffix as their match token and NFL has 2,619 same-team surname groups.
    See test_boxscore_player_match_by_id.

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
                    # Unnamed — identify by a label the OTHER group does not have.
                    # A non-empty intersection is not identity: the two sets share
                    # {BB, H, HR, K, R}, so every pitching line satisfied the batting
                    # test and a batter's "hits" read the pitcher's hits allowed.
                    # See test_stat_group_identity.
                    if category_norm in ("batting", "offensive"):
                        if not (label_set & _BATTING_ONLY) or (label_set & _PITCHING_ONLY):
                            continue
                    elif category_norm == "pitching":
                        if not (label_set & _PITCHING_ONLY) or (label_set & _BATTING_ONLY):
                            continue

            entries = stats_group.get("athletes", []) or []
            matched = None
            if espn_id:
                wanted = str(espn_id)
                matched = next(
                    (e for e in entries
                     if str((e.get("athlete") or {}).get("id") or "") == wanted), None)
            else:
                want = _norm_name(player_name)
                by_name = [e for e in entries
                           if _norm_name((e.get("athlete") or {}).get("displayName")) == want]
                # Exactly one, or nobody. Two people answering to one name is the
                # case the old surname rule silently resolved by taking the first.
                matched = by_name[0] if len(by_name) == 1 else None

            for athlete_entry in ([matched] if matched else []):
                # Found the player — extract the stat
                stats_list = athlete_entry.get("stats", [])
                labels = stats_group.get("labels") or []
                if isinstance(stats_list, list) and len(stats_list) > 0:
                    # TB was derived here as round(SLG * AB). MLB publishes totalBases
                    # directly and _MLB_BATTING_STATS already reads it, so this forked a
                    # definition for no gain — and ESPN's box-score AVG/OBP/SLG are
                    # season-to-date, making it a season rate times one game's at-bats.
                    # A box score that does not report TB is a void, like any other
                    # unreported stat. Same for 2B, which was already handled this way.

                    # Standard label-based lookup
                    if labels and stat_key in labels:
                        idx = labels.index(stat_key)
                        if idx < len(stats_list):
                            val = stats_list[idx]
                            # An empty cell is ESPN declining to report the stat for
                            # this athlete, not a measured zero. Every prop is over/
                            # under a line, so a 0 here does not fail — it grades, and
                            # the UNDER cashes. Void instead. See
                            # test_missing_stat_is_void_not_zero.
                            if val in (None, ""):
                                return None
                            try:
                                return float(val)
                            except (ValueError, TypeError):
                                return None
                # The athlete is in this box score but the stat is not among its
                # labels — "not reported" became "recorded zero" here.
                return None
    return None


def _find_player_compound_stat(boxscore: dict, player_name: str, team: str,
                                categories: List[str], stat_keys: List[str],
                                espn_id: Optional[str] = None) -> Optional[float]:
    """Sum multiple stats across categories (e.g. hits_runs_rbis = H + R + RBI)."""
    # EVERY part, not any part: a sum missing one of its terms is not a total, it is
    # a smaller number that grades. H + R + (missing RBI) settled as H+R and the
    # UNDER cashed on the difference.
    total = 0.0
    for cat, key in zip(categories, stat_keys):
        val = _find_player_stat(boxscore, player_name, team, cat, key, espn_id=espn_id)
        if val is None:
            return None
        total += val
    return total


# ── MLB Stats API boxscore integration ─────────────────────────────
# MLB settlement uses the MLB Stats API (statsapi.mlb.com) instead of ESPN
# because: (a) totalBases/doubles are directly available per player,
# (b) players are keyed by mlbam_id (no name-matching, no derivation),
# (c) strikeOuts, hits, rbi, runs all come directly.

_MLB_SCHEDULE = "https://statsapi.mlb.com/api/v1/schedule"
_MLB_BOXSCORE = "https://statsapi.mlb.com/api/v1/game/{gamePk}/boxscore"
_MLB_HDR = {"User-Agent": "Mozilla/5.0"}

# MLB Stats API field names → our canonical stat_key
_MLB_BATTING_STATS = {
    "hits": "H", "totalBases": "TB", "rbi": "RBI", "runs": "R",
    "homeRuns": "HR", "doubles": "2B", "triples": "3B",
    "stolenBases": "SB", "atBats": "AB",
}
_MLB_PITCHING_STATS = {
    "strikeOuts": "SO", "hits": "H", "earnedRuns": "ER",
    "baseOnBalls": "BB", "inningsPitched": "IP", "outs": "outs",
}

# Canonical market name → (mlb_api_category, mlb_api_field_name)
_MLB_MARKET_MAP = {
    # Pitching
    "strikeouts":    ("pitching", "strikeOuts"),
    "hits_allowed":  ("pitching", "hits"),
    "outs":          ("pitching", "outs"),
    "earned_runs":   ("pitching", "earnedRuns"),
    "walks":         ("pitching", "baseOnBalls"),
    # Batting
    "total_bases":           ("batting", "totalBases"),
    "hits_runs_rbis":        (None, None),  # compound — sum H+R+RBI
    "home_run_any":          ("batting", "homeRuns"),
    "hit_any":               ("batting", "hits"),
    "rbi_any":               ("batting", "rbi"),
    "run_any":               ("batting", "runs"),
    "stolen_base_any":       ("batting", "stolenBases"),
    "double_any":            ("batting", "doubles"),
    "triple_any":            ("batting", "triples"),
}


_MLB_SCHEDULE_CACHE: Dict[str, dict] = {}


def _mlb_schedule(date_str: str) -> dict:
    """One schedule fetch per DATE, not per game. A slate is fifteen games and this was
    pulling the same document fifteen times; re-grading a season did it 709 times for 55
    distinct dates."""
    if date_str not in _MLB_SCHEDULE_CACHE:
        import urllib.request as _ur
        url = f"{_MLB_SCHEDULE}?date={date_str}&sportId=1"
        req = _ur.Request(url, headers=_MLB_HDR)
        with _ur.urlopen(req, timeout=15) as r:
            _MLB_SCHEDULE_CACHE[date_str] = json.loads(r.read().decode())
    return _MLB_SCHEDULE_CACHE[date_str]


def _fetch_mlb_gamepk(date_str: str, home_team: str, away_team: str,
                      start_time: Optional[str] = None) -> Optional[int]:
    """Look up MLB gamePk by FIRST PITCH, falling back to the calendar day.

    Publishers do not agree on which calendar day a game belongs to. A first pitch at 22:15
    ET is the next day in UTC, and our prop_games rows and the MLB schedule land on opposite
    sides of it: the Braves-Giants fixture is 2026-06-17 to Statcast and the MLB schedule,
    and 2026-06-18 in prop_games. Matching on the exact date therefore found either nothing
    or, worse, a DIFFERENT game involving one of the same clubs — which is how ten games were
    graded to zeros against a box score their players never appeared in. 39 of 210 props
    across them disagreed with Statcast even after the finality fix.

    The date is a hint, the teams are NOT the identity: a series plays the same two clubs on
    consecutive days. Searching day-1/day/day+1 on teams alone and returning the first match
    picked a different game between the same clubs — measured 2026-08-11, an hour after the
    props timer ran:

        _fetch_mlb_gamepk('2026-08-11', 'Arizona Diamondbacks', 'Colorado Rockies')
          -> 825046 = 2026-08-12T01:40Z, "Pre-Game"

    while the game that happened was 2026-08-11T01:40Z, Final 9-0. An unplayed game still
    publishes a lineup with zeroed batting lines, so every player resolved, every stat read
    0 and every prop graded: **every UNDER cashed**. 7,857 props over 6 games.

    `prop_games.start_time` is the exact key, on the same row, and the schedule publishes
    `gameDate` on the same object. Match instants and there is nothing to guess. Two guards,
    because either alone leaves the other hole open:

      1. When we have the instant, it decides — within a few minutes of drift, since a
         published first pitch moves. No instant match, no gamePk.
      2. A game that is not Final is never the answer, instant or not. That covers the
         rows with no start_time (everything before 2026-07-17) and postponed games, which
         are `Preview` forever.

    Ambiguity with no instant to resolve it fails closed. An unsettled prop is recoverable;
    one graded against the wrong game is not. See test_mlb_gamepk_by_instant.
    """
    import datetime as _dt

    def _instant(text):
        if not text:
            return None
        try:
            return _dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
        except ValueError:
            return None

    want = _instant(start_time)
    try:
        base = _dt.date.fromisoformat(date_str)
        candidates = [date_str,
                      (base - _dt.timedelta(days=1)).isoformat(),
                      (base + _dt.timedelta(days=1)).isoformat()]
    except Exception:
        candidates = [date_str]

    matches = []  # [(gamePk, gameDate instant or None)]
    seen = set()
    for day in candidates:
        try:
            data = _mlb_schedule(day)
        except Exception:
            # A failed schedule fetch is not "no game that day". Everything below reads
            # `matches`, so an empty result here returns None rather than a wrong pk.
            continue
        for dt_entry in data.get("dates", []):
            for game in dt_entry.get("games", []):
                pk = game.get("gamePk")
                if pk in seen:
                    continue
                teams = game.get("teams", {})
                away = teams.get("away", {}).get("team", {})
                home = teams.get("home", {}).get("team", {})
                if not any(home_team.lower() == (home.get(key) or "").lower()
                           and away_team.lower() == (away.get(key) or "").lower()
                           for key in ("name", "abbreviation")):
                    continue
                # Guard 2: a box score for a game that has not been played to a result is
                # not a result. Postponed games sit at Preview permanently.
                if (game.get("status") or {}).get("abstractGameState") != "Final":
                    continue
                seen.add(pk)
                matches.append((pk, _instant(game.get("gameDate"))))

    if want is not None:
        # Guard 1: the instant decides — but our start_time comes from ESPN and the
        # candidates come from MLB, and the two publishers disagree by up to ~35
        # minutes on a revised first pitch (measured: event 401815922 is 20:40Z to
        # ESPN and 20:05Z to MLB; 401816096 is 23:50Z vs 23:15Z). A 15-minute window
        # rejected both and settled nothing for those games.
        #
        # 90 minutes absorbs that drift and still cannot reach the other half of a
        # doubleheader, which is hours away (the 2026-06-17 pair is 18:00Z and
        # 23:15Z). Two candidates inside the window means the window is not doing its
        # job — fail closed rather than take the nearer one.
        near = sorted((abs((gd - want).total_seconds()), pk)
                      for pk, gd in matches if gd is not None)
        near = [(d, pk) for d, pk in near if d <= 90 * 60]
        return near[0][1] if len(near) == 1 else None

    if len(matches) == 1:
        return matches[0][0]
    return None


def _fetch_mlb_final(gamePk: int) -> Optional[Tuple[int, int]]:
    """(home_score, away_score) for a gamePk the schedule reports Final, else None.

    Keyed on the gamePk rather than on (date, home, away): a doubleheader publishes two
    games with identical teams on one date, so a dict keyed by the triple keeps whichever
    landed last and hands both halves the same final. See test_regrade_finals_by_gamepk.
    """
    import urllib.request as _ur
    try:
        url = f"{_MLB_SCHEDULE}?gamePk={gamePk}&sportId=1"
        with _ur.urlopen(_ur.Request(url, headers=_MLB_HDR), timeout=15) as r:
            data = json.loads(r.read().decode())
    except Exception:
        return None
    for entry in data.get("dates", []):
        for game in entry.get("games", []):
            if (game.get("status") or {}).get("abstractGameState") != "Final":
                continue
            teams = game.get("teams") or {}
            home = (teams.get("home") or {}).get("score")
            away = (teams.get("away") or {}).get("score")
            if home is not None and away is not None:
                return (home, away)
    return None


def _fetch_mlb_boxscore(gamePk: int) -> Optional[dict]:
    """Pull the MLB Stats API boxscore for a game."""
    import urllib.request as _ur
    try:
        url = _MLB_BOXSCORE.format(gamePk=gamePk)
        req = _ur.Request(url, headers=_MLB_HDR)
        with _ur.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def _settle_mlb_props(con, game_row, props) -> dict:
    """Settle MLB props using the MLB Stats API boxscore (mlbam_id-based matching).

    A ``prop_results`` row is terminal: the driver excludes that prop from every
    later run.  Only write one for a numeric outcome.  This payload has no
    positive DNP field: absence from its player/stat dictionaries is not enough
    to distinguish a true DNP from identity drift or incomplete publisher data.
    Those states stay pending so a later repair can retry them.
    """
    date_str = game_row["date"]
    home = game_row["home"]
    away = game_row["away"]

    # start_time is the exact key and it is already on this row. Passing the date alone
    # made the lookup guess between games of the same series; see _fetch_mlb_gamepk.
    try:
        start_time = game_row["start_time"]
    except (KeyError, IndexError):
        start_time = None
    gamePk = _fetch_mlb_gamepk(date_str, home, away, start_time=start_time)
    if not gamePk:
        return {"settled": 0, "void": 0, "unmappable": 0, "pending": 0,
                "errors": 0,
                "msg": f"MLB gamePk not found for {away}@{home} on {date_str} "
                       f"(start_time={start_time or 'none'})"}

    box = _fetch_mlb_boxscore(gamePk)
    if not box:
        return {"settled": 0, "void": 0, "unmappable": 0, "pending": 0,
                "errors": 1,
                "error_msg": f"MLB boxscore failed for gamePk={gamePk}"}

    # Build lookup: mlbam_id → {"batting": {...}, "pitching": {...}}
    # MLB Stats API: players are keyed as "ID{mlbam_id}" in teams.{side}.players
    player_stats = {}  # mlbam_id → {"batting": {...}, "pitching": {...}}
    for side in ("away", "home"):
        team_data = box.get("teams", {}).get(side, {})
        players_dict = team_data.get("players", {})
        for key, pdata in players_dict.items():
            # Key is like "ID689414" — extract numeric mlbam_id
            if key.startswith("ID"):
                try:
                    mlbam = int(key[2:])
                except ValueError:
                    continue
            else:
                try:
                    mlbam = int(key)
                except ValueError:
                    continue
            stats = pdata.get("stats", {})
            player_stats[mlbam] = {
                "batting": stats.get("batting", {}),
                "pitching": stats.get("pitching", {}),
            }

    # Build player_id → mlbam_id lookup from the spine
    player_mlbam = {}
    for r in con.execute("SELECT id, mlbam_id FROM players WHERE league='mlb' AND mlbam_id IS NOT NULL AND mlbam_id != 0"):
        player_mlbam[r["id"]] = r["mlbam_id"]

    settled = 0
    void = 0
    unmappable = 0
    pending = 0
    errors = 0
    now = dt.datetime.now(dt.timezone.utc).isoformat()

    for prop in props:
        mlbam_id = player_mlbam.get(prop["player_id"])
        if not mlbam_id:
            # A missing local crosswalk is not evidence that the player did not
            # appear.  It is repairable identity data, so leave the prop retryable.
            pending += 1
            continue

        ps = player_stats.get(mlbam_id)
        if not ps:
            # Absence is not a positive DNP signal.  It can also mean that the
            # identity or publisher payload is incomplete.
            pending += 1
            continue

        # Resolve market to (category, mlb_api_field)
        canonical = normalize_market(prop["market"])
        canonical = MARKET_ALIASES.get(canonical, canonical)
        mapping = _MLB_MARKET_MAP.get(canonical)

        if not mapping or mapping == (None, None):
            # Compound markets: sum multiple stats
            if canonical in ("hits_runs_rbis", "hits_runs_rbis"):
                # `.get(x, 0)` on a player with no batting object at all read as a
                # hitless day. That is how an unplayed game — which still publishes a
                # lineup, with no batting lines — graded every prop 0.0 and cashed
                # every UNDER. A player who really went 0-for-4 HAS a batting object
                # with hits: 0, so the two are distinguishable; read the difference.
                bat = ps.get("batting") or {}
                parts = [bat.get(k) for k in ("hits", "runs", "rbi")]
                if any(v is None for v in parts):
                    pending += 1
                    continue
                actual = float(sum(parts))
            else:
                unmappable += 1
                continue
        else:
            category, mlb_field = mapping
            stats_dict = ps.get(category, {})

            # Handle derived fields
            if mlb_field == "outs" and "outs" not in stats_dict:
                # Compute outs from innings pitched (IP like "6.0" = 18 outs)
                ip_str = stats_dict.get("inningsPitched")
                if ip_str:
                    try:
                        actual = float(ip_str) * 3
                    except (ValueError, TypeError):
                        pending += 1
                        continue
                else:
                    pending += 1
                    continue
            else:
                actual = stats_dict.get(mlb_field)
                if actual is None:
                    pending += 1
                    continue
                try:
                    actual = float(actual)
                except (ValueError, TypeError):
                    pending += 1
                    continue

        # Grade
        line = prop["line"]
        side = (prop["side"] or "").lower()
        if side == "over":
            hit = 1 if actual > line else (0 if actual < line else None)
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
        except Exception:
            errors += 1

    con.commit()
    return {"settled": settled, "void": void, "unmappable": unmappable,
            "pending": pending, "errors": errors}


_UFC_NUMERIC_MARKETS = {
    "significant_strikes": "sigStrikesLanded",
    "fight_time": "fight_time",
}

_UFC_METHOD_MARKETS = {
    "win_by_decision": "DEC",
    "win_by_ko": "KO/TKO",
    "knockouts": "KO/TKO",
    "win_by_submission": "SUB",
    "submissions": "SUB",
}

_MLS_ROSTER_MARKETS = {
    "goals": "totalGoals",
    "assists": "goalAssists",
}


def _ufc_scoreboard_competition(espn, date_text: str, fight_id: str) -> dict:
    """Return the exact fight object from ESPN's card-level UFC scoreboard.

    UFC links store a competition (fight) id, not a summary event id. MMA has no
    working site-summary endpoint, so finality must be read from the competition
    nested in a nearby date scoreboard. ESPN indexes the card by its US-local
    date while late fights routinely start on the next UTC date used by the prop
    feed. Use the same shared date window as the linker so a link it creates can
    also be resolved here. Keep the publisher's ``completed`` bit intact;
    ``state == post`` alone also includes canceled events in ESPN's taxonomy.
    """
    path = espn.LEAGUES["ufc"][0]
    wanted = str(fight_id)
    checked = []
    for day in espn.neighbor_dates(date_text):
        checked.append(day)
        date_key = str(day or "").replace("-", "")
        payload = espn._get(
            espn._SITE.format(path=path) + f"/scoreboard?dates={date_key}", ttl=60)
        for event in payload.get("events") or []:
            for competition in event.get("competitions") or []:
                if str(competition.get("id") or "") == wanted:
                    return competition
    raise ValueError(
        f"UFC fight {wanted} absent from scoreboards {', '.join(checked)}")


def _ufc_actual(stats: dict, market: str) -> Optional[float]:
    """Read a supported UFC actual from one durable per-fight log.

    Method markets are yes/no events. Both the win/loss and method are publisher
    fields persisted by ``ingest_ufc_fight_stats.py``; no outcome is inferred from
    strike counts or clock values here.
    """
    canonical = normalize_market(market)
    canonical = MARKET_ALIASES.get(canonical, canonical)
    stat_key = _UFC_NUMERIC_MARKETS.get(canonical)
    if stat_key:
        value = stats.get(stat_key)
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    wanted_method = _UFC_METHOD_MARKETS.get(canonical)
    if not wanted_method:
        return None
    result = str(stats.get("result") or "").strip().upper()
    method = str(stats.get("method") or "").strip().upper()
    if result == "W":
        if not method:
            return None
        return 1.0 if method == wanted_method else 0.0
    if result in {"L", "D", "NC"}:
        return 0.0
    return None


def _grade_actual(con: sqlite3.Connection, prop, actual: float, now: str) -> bool:
    """Write one numeric actual. Return False when the prop side is unsupported."""
    line = prop["line"]
    side = (prop["side"] or "").lower()
    if side == "over":
        hit = 1 if actual > line else (0 if actual < line else None)
    elif side == "under":
        hit = 1 if actual < line else (0 if actual > line else None)
    else:
        return False
    con.execute(
        "INSERT INTO prop_results(prop_id, actual_value, hit, settled_at) VALUES (?,?,?,?)",
        (prop["id"], actual, hit, now))
    return True


def _settle_ufc_props(con: sqlite3.Connection, game, props: list) -> dict:
    """Grade UFC props from durable per-fighter, per-fight actuals.

    Missing logs remain unsettled: absence means the ingest has not published an
    actual into this database, not that the fighter recorded zero or did not play.
    Likewise an unsupported market remains retryable instead of receiving the null
    ``prop_results`` placeholder used by the legacy generic path.
    """
    logs = con.execute(
        "SELECT player_id, source_player_key, stats FROM player_game_logs "
        "WHERE league='ufc' AND game_id=?",
        (str(game["espn_event_id"]),)).fetchall()
    by_player_id = {}
    by_espn_id = {}
    for row in logs:
        if row["player_id"] is not None:
            by_player_id.setdefault(str(row["player_id"]), []).append(row)
        if row["source_player_key"]:
            by_espn_id.setdefault(str(row["source_player_key"]), []).append(row)

    settled = 0
    unmappable = 0
    pending = 0
    errors = 0
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    supported = set(_UFC_NUMERIC_MARKETS) | set(_UFC_METHOD_MARKETS)

    for prop in props:
        canonical = normalize_market(prop["market"])
        canonical = MARKET_ALIASES.get(canonical, canonical)
        if canonical not in supported:
            unmappable += 1
            continue

        if prop["espn_id"]:
            matches = by_espn_id.get(str(prop["espn_id"]), [])
        else:
            matches = by_player_id.get(str(prop["player_id"]), [])
        if len(matches) != 1:
            pending += 1
            continue

        try:
            stats = json.loads(matches[0]["stats"] or "")
        except (TypeError, ValueError, json.JSONDecodeError):
            errors += 1
            continue
        actual = _ufc_actual(stats, canonical)
        if actual is None:
            pending += 1
            continue
        try:
            if _grade_actual(con, prop, actual, now):
                settled += 1
            else:
                unmappable += 1
        except Exception:
            errors += 1

    con.commit()
    return {"settled": settled, "void": 0, "unmappable": unmappable,
            "pending": pending, "errors": errors}


def _soccer_name(text: str) -> str:
    """Accent-fold an exact soccer roster name without using substring matching."""
    ascii_text = unicodedata.normalize("NFKD", str(text or "")).encode(
        "ascii", "ignore").decode("ascii")
    return " ".join("".join(
        char for char in ascii_text.lower()
        if char.isalnum() or char.isspace()).split())


def _settle_mls_props(con: sqlite3.Connection, props: list, summary: dict) -> dict:
    """Grade MLS goals/assists from the summary roster-stat surface.

    Soccer summaries publish only team aggregates under ``boxscore``. Player
    actuals live alongside athlete identity in ``rosters[].roster[].stats``.
    """
    roster_rows = [
        row
        for group in summary.get("rosters") or []
        for row in group.get("roster") or []
    ]
    if not roster_rows:
        return {"settled": 0, "void": 0, "unmappable": 0, "pending": 0,
                "errors": 1, "error_msg": "MLS summary has no player rosters"}

    by_espn_id = {}
    by_name = {}
    for row in roster_rows:
        athlete = row.get("athlete") or {}
        athlete_id = str(athlete.get("id") or "")
        if athlete_id:
            by_espn_id.setdefault(athlete_id, []).append(row)
        name_key = _soccer_name(athlete.get("displayName"))
        if name_key:
            by_name.setdefault(name_key, []).append(row)

    settled = 0
    void = 0
    unmappable = 0
    pending = 0
    errors = 0
    now = dt.datetime.now(dt.timezone.utc).isoformat()

    for prop in props:
        canonical = normalize_market(prop["market"])
        canonical = MARKET_ALIASES.get(canonical, canonical)
        stat_name = _MLS_ROSTER_MARKETS.get(canonical)
        if not stat_name:
            unmappable += 1
            continue

        if prop["espn_id"]:
            matches = by_espn_id.get(str(prop["espn_id"]), [])
        else:
            matches = by_name.get(_soccer_name(prop["player_name"]), [])
        if not matches:
            # Roster absence is not a DNP flag.  It can be a partial roster or a
            # stale ESPN id, and neither may permanently exclude the prop from a
            # later settlement run.
            pending += 1
            continue
        if len(matches) != 1:
            pending += 1
            continue

        published = [stat.get("value") for stat in matches[0].get("stats") or []
                     if stat.get("name") == stat_name]
        if len(published) != 1 or published[0] in (None, ""):
            pending += 1
            continue
        try:
            actual = float(published[0])
            if _grade_actual(con, prop, actual, now):
                settled += 1
            else:
                unmappable += 1
        except (TypeError, ValueError):
            pending += 1
        except Exception:
            errors += 1

    con.commit()
    return {"settled": settled, "void": void, "unmappable": unmappable,
            "pending": pending, "errors": errors}


def settle_game(con: sqlite3.Connection, game_id: int) -> dict:
    """Settle all unsettled props for one prop_games row.

    Pulls the ESPN boxscore for the game, resolves each prop's market,
    finds the player's actual stat, grades over/under, writes prop_results.

    Returns: {settled: N, void: N, unmappable: N, pending: N, errors: N}
    Idempotent: skips props that already have a prop_results row.
    """
    import espn_client as espn

    game = con.execute(
        # start_time is the exact key _fetch_mlb_gamepk resolves on; leaving it out of
        # this SELECT made every MLB settle fall back to the ambiguous date+teams path
        # and then fail closed, writing nothing.
        "SELECT id, league, home, away, date, espn_event_id, final_home, final_away, "
        "start_time FROM prop_games WHERE id=?",
        (game_id,)
    ).fetchone()
    if not game:
        return {"settled": 0, "void": 0, "unmappable": 0, "errors": 1, "error_msg": "game not found"}

    league = game["league"]
    espn_event_id = game["espn_event_id"]
    if not espn_event_id and league != "mlb":
        return {"settled": 0, "void": 0, "unmappable": 0, "errors": 0,
                "msg": f"game {game_id}: no espn_event_id, cannot pull boxscore"}
    if not espn_event_id:
        # MLB grades from the MLB Stats API, not from ESPN, so an ESPN link is not
        # required to settle it — and requiring one skipped the finality gate entirely
        # for these rows. Game 550 carries 2,052 graded props and no ESPN link at all;
        # they were written by a path that never asked whether the game was over.
        # _fetch_mlb_gamepk resolves by first pitch and returns Final games only, so it
        # IS the gate here; _fetch_mlb_final supplies the score the ESPN branch would
        # have written. See test_finality_gate_completed.
        if game["final_home"] is None:
            pk = _fetch_mlb_gamepk(game["date"], game["home"], game["away"],
                                   start_time=game["start_time"])
            final = _fetch_mlb_final(pk) if pk else None
            if not final:
                return {"settled": 0, "void": 0, "unmappable": 0, "errors": 0,
                        "msg": f"game {game_id}: not final yet (no ESPN link; MLB "
                               f"gamePk={pk or 'unresolved'})"}
            con.execute("UPDATE prop_games SET final_home=?, final_away=? WHERE id=?",
                        (final[0], final[1], game_id))
            con.commit()
            game = dict(game, final_home=final[0], final_away=final[1])
        # Falls through to the MLB branch below; the ESPN gate is skipped because
        # final_home is now set.

    # ── Is the game actually over? ──────────────────────────────────────────────
    # This gate used to live BELOW the MLB branch, which returns before reaching it — so
    # for the one league that has real prop volume it was dead code, and MLB props were
    # graded against whatever the box score held at the moment the job ran. Measured on
    # 401816457 (Reds at Nationals, 2026-08-09): first pitch 16:15Z, every prop settled at
    # 17:00Z, 45 minutes in. Brady Singer was graded at 6 outs and 0 strikeouts; he
    # finished with 18 and 3. Games that had not started yet were graded as zeros — two
    # examples settled roughly 22 HOURS before first pitch.
    #
    # A live box score is not a result. Nothing settles until the publisher says Final.
    if game["final_home"] is None:
        try:
            if league == "ufc":
                competition = _ufc_scoreboard_competition(
                    espn, game["date"], espn_event_id)
                status_type = ((competition.get("status") or {}).get("type") or {})
                result = {
                    "state": status_type.get("state"),
                    "completed": status_type.get("completed") is True,
                }
            else:
                result = espn.game_result(league, espn_event_id)
            # Gate on `completed`, not on state=="post": ESPN files POSTPONED,
            # canceled and suspended games under post as well, with completed=false
            # and a score of 0 on both sides. This gate admitted one (event
            # 401815805) and stamped it final 0-0, which would have graded every
            # prop on an unplayed game against zeros. The old `winner is None`
            # clause was a proxy for the same question that also refused an honest
            # DRAW — a real result in soccer and NHL. See test_finality_gate_completed.
            if not result.get("completed"):
                return {"settled": 0, "void": 0, "unmappable": 0, "errors": 0,
                        "msg": f"game {game_id}: not final yet (state={result['state']}, "
                               f"completed={result.get('completed')})"}
            # `scores` is keyed by ESPN ABBREVIATION ("ATH"); game["home"] is a
            # display name ("Athletics"). The old lookup `scores.get(game["home"])`
            # could never hit, so final_home/final_away were written NULL on every
            # game that came through here — WC had 3 of 3 linked games with no
            # final, and MLB's 605 finals all came from regrade_props instead.
            # A wrong key does not raise, it misses. game_result now reports which
            # side is home from ESPN's own homeAway flag, so there is no name to
            # match. See test_game_result_home_away.
            # UFC competitors have no team scores. Writing winner booleans into
            # final_home/final_away would mislabel the columns, so UFC retains the
            # publisher finality gate without fabricating a score.
            if league != "ufc":
                con.execute(
                    "UPDATE prop_games SET final_home=?, final_away=? WHERE id=?",
                    (result.get("home_score"), result.get("away_score"), game_id))
                con.commit()
        except Exception as e:
            return {"settled": 0, "void": 0, "unmappable": 0, "errors": 1,
                    "error_msg": f"game {game_id}: ESPN pull failed: {e}"}

    # ── MLB: use MLB Stats API for accurate TB/doubles/strikeouts ──
    if league == "mlb":
        # Find unsettled props
        props = con.execute("""
            SELECT p.id, p.market, p.line, p.side, p.player_id, pl.name as player_name, pl.team as player_team,
                   pl.espn_id as espn_id
            FROM props p
            JOIN players pl ON pl.id = p.player_id
            LEFT JOIN prop_results pr ON pr.prop_id = p.id
            WHERE p.game_id = ? AND pr.prop_id IS NULL
        """, (game_id,)).fetchall()
        if not props:
            return {"settled": 0, "void": 0, "unmappable": 0, "errors": 0,
                    "msg": f"game {game_id}: no unsettled props"}
        result = _settle_mlb_props(con, game, props)
        # Merge with standard result keys
        result.setdefault("errors", 0)
        return result

    if league == "ufc":
        props = con.execute("""
            SELECT p.id, p.market, p.line, p.side, p.player_id,
                   pl.name as player_name, pl.team as player_team,
                   pl.espn_id as espn_id
            FROM props p
            JOIN players pl ON pl.id = p.player_id
            LEFT JOIN prop_results pr ON pr.prop_id = p.id
            WHERE p.game_id = ? AND pr.prop_id IS NULL
        """, (game_id,)).fetchall()
        if not props:
            return {"settled": 0, "void": 0, "unmappable": 0, "pending": 0,
                    "errors": 0, "msg": f"game {game_id}: no unsettled props"}
        return _settle_ufc_props(con, game, props)

    if league == "mls":
        try:
            summary = espn.summary(league, espn_event_id)
        except Exception as e:
            return {"settled": 0, "void": 0, "unmappable": 0, "pending": 0,
                    "errors": 1,
                    "error_msg": f"game {game_id}: MLS summary pull failed: {e}"}
        props = con.execute("""
            SELECT p.id, p.market, p.line, p.side, p.player_id,
                   pl.name as player_name, pl.team as player_team,
                   pl.espn_id as espn_id
            FROM props p
            JOIN players pl ON pl.id = p.player_id
            LEFT JOIN prop_results pr ON pr.prop_id = p.id
            WHERE p.game_id = ? AND pr.prop_id IS NULL
        """, (game_id,)).fetchall()
        if not props:
            return {"settled": 0, "void": 0, "unmappable": 0, "pending": 0,
                    "errors": 0, "msg": f"game {game_id}: no unsettled props"}
        return _settle_mls_props(con, props, summary)

    # (finality is checked above, before the MLB branch, so every league passes through it)

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
        SELECT p.id, p.market, p.line, p.side, p.player_id, pl.name as player_name, pl.team as player_team,
                   pl.espn_id as espn_id
        FROM props p
        JOIN players pl ON pl.id = p.player_id
        LEFT JOIN prop_results pr ON pr.prop_id = p.id
        WHERE p.game_id = ? AND pr.prop_id IS NULL
    """, (game_id,)).fetchall()

    settled = 0
    void = 0
    unmappable = 0
    pending = 0
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
                    ["batting", "batting", "batting"], ["H", "R", "RBI"],
                    espn_id=prop["espn_id"])
            else:
                unmappable += 1
                continue
        else:
            actual = _find_player_stat(
                box, prop["player_name"], prop["player_team"],
                category, stat_key, espn_id=prop["espn_id"])

        # The generic ESPN reader deliberately returns one sentinel for several
        # different states: athlete absent, category absent, label absent, empty
        # value, or ambiguous identity.  It cannot prove a terminal DNP, so none
        # of those states may write the same null row used by a real void.
        if actual is None:
            pending += 1
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
    return {"settled": settled, "void": void, "unmappable": unmappable,
            "pending": pending, "errors": errors}


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
