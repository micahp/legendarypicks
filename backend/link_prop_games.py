#!/usr/bin/env python3
"""
link_prop_games.py — Crosswalk: match prop_games to ESPN games and populate espn_event_id.

Matches by: league + date + normalized team abbreviation.
Runs on existing rows AND usable as a library for ingest_props.py going forward.

Usage: venv/bin/python link_prop_games.py [--dry-run] [--relink]

--relink also re-checks rows that already carry an espn_event_id, correcting any
bound to the wrong game of a series (85 MLB rows on 2026-08-11).
"""
import sys, os, sqlite3, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import espn_client as espn

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

# Team name → abbreviation lookup (built from ESPN data on the fly + a static fallback)
# ESPN returns team abbrev in game data, so we match by abbreviation.
# prop_games has full team names like "Philadelphia Phillies" — we need to normalize to "PHI".

# Static MLB team name → abbreviation map (covers common names)
_MLB_TEAM_MAP = {
    "arizona diamondbacks": "ARI", "atlanta braves": "ATL", "baltimore orioles": "BAL",
    "boston red sox": "BOS", "chicago cubs": "CHC", "chicago white sox": "CWS",
    "cincinnati reds": "CIN", "cleveland guardians": "CLE", "colorado rockies": "COL",
    "detroit tigers": "DET", "houston astros": "HOU", "kansas city royals": "KC",
    "los angeles angels": "LAA", "los angeles dodgers": "LAD", "miami marlins": "MIA",
    "milwaukee brewers": "MIL", "minnesota twins": "MIN", "new york mets": "NYM",
    "new york yankees": "NYY", "oakland athletics": "OAK", "athletics": "ATH",
    "philadelphia phillies": "PHI", "pittsburgh pirates": "PIT",
    "san diego padres": "SD", "san francisco giants": "SF",
    "seattle mariners": "SEA", "st. louis cardinals": "STL",
    "tampa bay rays": "TB", "texas rangers": "TEX", "toronto blue jays": "TOR",
    "washington nationals": "WSH",
}

_NBA_TEAM_MAP = {
    "atlanta hawks": "ATL", "boston celtics": "BOS", "brooklyn nets": "BKN",
    "charlotte hornets": "CHA", "chicago bulls": "CHI", "cleveland cavaliers": "CLE",
    "dallas mavericks": "DAL", "denver nuggets": "DEN", "detroit pistons": "DET",
    "golden state warriors": "GS", "houston rockets": "HOU", "indiana pacers": "IND",
    "la clippers": "LAC", "los angeles lakers": "LAL", "memphis grizzlies": "MEM",
    "miami heat": "MIA", "milwaukee bucks": "MIL", "minnesota timberwolves": "MIN",
    "new orleans pelicans": "NO", "new york knicks": "NY", "oklahoma city thunder": "OKC",
    "orlando magic": "ORL", "philadelphia 76ers": "PHI", "phoenix suns": "PHX",
    "portland trail blazers": "POR", "sacramento kings": "SAC", "san antonio spurs": "SA",
    "toronto raptors": "TOR", "utah jazz": "UTAH", "washington wizards": "WSH",
}

_NFL_TEAM_MAP = {
    "arizona cardinals": "ARI", "atlanta falcons": "ATL", "baltimore ravens": "BAL",
    "buffalo bills": "BUF", "carolina panthers": "CAR", "chicago bears": "CHI",
    "cincinnati bengals": "CIN", "cleveland browns": "CLE", "dallas cowboys": "DAL",
    "denver broncos": "DEN", "detroit lions": "DET", "green bay packers": "GB",
    "houston texans": "HOU", "indianapolis colts": "IND", "jacksonville jaguars": "JAX",
    "kansas city chiefs": "KC", "las vegas raiders": "LV", "los angeles chargers": "LAC",
    "los angeles rams": "LAR", "miami dolphins": "MIA", "minnesota vikings": "MIN",
    "new england patriots": "NE", "new orleans saints": "NO", "new york giants": "NYG",
    "new york jets": "NYJ", "philadelphia eagles": "PHI", "pittsburgh steelers": "PIT",
    "san francisco 49ers": "SF", "seattle seahawks": "SEA", "tampa bay buccaneers": "TB",
    "tennessee titans": "TEN", "washington commanders": "WSH",
}

_NHL_TEAM_MAP = {
    "anaheim ducks": "ANA", "boston bruins": "BOS", "buffalo sabres": "BUF",
    "calgary flames": "CGY", "carolina hurricanes": "CAR", "chicago blackhawks": "CHI",
    "colorado avalanche": "COL", "columbus blue jackets": "CBJ", "dallas stars": "DAL",
    "detroit red wings": "DET", "edmonton oilers": "EDM", "florida panthers": "FLA",
    "los angeles kings": "LAK", "minnesota wild": "MIN", "montreal canadiens": "MTL",
    "nashville predators": "NSH", "new jersey devils": "NJD", "new york islanders": "NYI",
    "new york rangers": "NYR", "ottawa senators": "OTT", "philadelphia flyers": "PHI",
    "pittsburgh penguins": "PIT", "san jose sharks": "SJS", "seattle kraken": "SEA",
    "st. louis blues": "STL", "tampa bay lightning": "TBL", "toronto maple leafs": "TOR",
    "utah hockey club": "UTA", "vancouver canucks": "VAN", "vegas golden knights": "VGK",
    "washington capitals": "WSH", "winnipeg jets": "WPG",
}

_WC_TEAM_MAP = {
    "argentina": "ARG", "australia": "AUS", "belgium": "BEL", "brazil": "BRA",
    "canada": "CAN", "chile": "CHI", "colombia": "COL", "croatia": "CRO",
    "denmark": "DEN", "ecuador": "ECU", "england": "ENG", "egypt": "EGY",
    "france": "FRA", "germany": "GER", "ghana": "GHA", "iceland": "ISL",
    "iran": "IRN", "italy": "ITA", "japan": "JPN", "jamaica": "JAM",
    "mexico": "MEX", "morocco": "MAR", "netherlands": "NED", "new zealand": "NZL",
    "nigeria": "NGA", "norway": "NOR", "paraguay": "PAR", "peru": "PER",
    "poland": "POL", "portugal": "POR", "qatar": "QAT", "saudi arabia": "KSA",
    "senegal": "SEN", "serbia": "SRB", "south africa": "RSA", "south korea": "KOR",
    "spain": "ESP", "sweden": "SWE", "switzerland": "SUI", "tunisia": "TUN",
    "turkey": "TUR", "ukraine": "UKR", "united states": "USA", "uruguay": "URU",
    "venezuela": "VEN", "wales": "WAL",
    # Also map some common short forms
    "usa": "USA", "uae": "UAE", "costa rica": "CRC", "ivory coast": "CIV",
    "côte d'ivoire": "CIV", "cote d'ivoire": "CIV",
    "czech republic": "CZE", "czechia": "CZE",
    "scotland": "SCO", "northern ireland": "NIR", "ireland": "IRL",
    "austria": "AUT", "hungary": "HUN", "romania": "ROU", "greece": "GRE",
    "slovakia": "SVK", "slovenia": "SVN", "bulgaria": "BUL",
    "algeria": "ALG", "cameroon": "CMR", "mali": "MLI",
    "bolivia": "BOL",
    "north korea": "PRK",
    "china": "CHN", "india": "IND",
}

_TEAM_MAPS = {"mlb": _MLB_TEAM_MAP, "nba": _NBA_TEAM_MAP, "nfl": _NFL_TEAM_MAP, "nhl": _NHL_TEAM_MAP, "wc": _WC_TEAM_MAP}


def _norm_team(team_name: str, league: str) -> str:
    """Normalize a team name to its ESPN abbreviation."""
    if not team_name:
        return ""
    # If already an abbreviation (2-4 uppercase letters), return as-is
    if re.match(r'^[A-Z]{2,4}$', team_name.strip()):
        return team_name.strip()
    # Look up in static map
    key = team_name.strip().lower()
    team_map = _TEAM_MAPS.get(league, {})
    if key in team_map:
        return team_map[key]
    # Fuzzy: try substring match
    for name, abbrev in team_map.items():
        if key in name or name in key:
            return abbrev
    # Fallback: first 3 letters uppercase
    return team_name.strip()[:3].upper()


def _instant(value):
    """Parse a timestamp to a UTC datetime truncated to the minute, or None.

    prop_games writes `2026-08-11T01:40:00+00:00`; ESPN writes `2026-08-11T01:40Z`.
    Both name the same instant and must compare equal.
    """
    import datetime as _dt
    s = (value or "").strip()
    if not s:
        return None
    try:
        dt = _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt.astimezone(_dt.timezone.utc).replace(second=0, microsecond=0)


def link_prop_game(con: sqlite3.Connection, game_row, espn_games: list) -> str:
    """Link one prop_game to an ESPN game. Returns espn_event_id or ''.

    Teams identify the MATCHUP; `start_time` identifies WHICH GAME of it.

    Matching on teams within a day's slate is ambiguous for the case baseball
    produces constantly -- the same two clubs on consecutive days. `prop_games.date`
    comes from a UTC first pitch while ESPN's scoreboard is keyed by LOCAL date, so
    a 01:40Z start (the previous evening locally) is looked up against the NEXT
    day's slate, which in a series holds the same two teams. The team match then
    succeeds on the wrong game: 85 of 286 dated MLB rows were bound to a game they
    were not, hiding a played game's props on an unplayed one and leaving them
    permanently ungraded (2026-08-11, /game/mlb/401816477).

    When `start_time` is known it is decisive, and a matchup whose instant matches
    nothing here returns '' rather than falling back to the team match. A wrong
    link is strictly worse than no link -- it is invisible, it hides the props from
    the game that was played, and settlement can never resolve it. An unlinked row
    is visibly missing and can be fixed.
    """
    league = game_row["league"]
    home_norm = _norm_team(game_row["home"], league)
    away_norm = _norm_team(game_row["away"], league)
    pg_home_name = (game_row["home"] or "").lower()
    pg_away_name = (game_row["away"] or "").lower()

    def _same_matchup(eg):
        if eg["home"]["abbrev"].upper() == home_norm and eg["away"]["abbrev"].upper() == away_norm:
            return True
        return ((eg["home"].get("displayName") or "").lower() == pg_home_name
                and (eg["away"].get("displayName") or "").lower() == pg_away_name)

    candidates = [eg for eg in espn_games if _same_matchup(eg)]
    if not candidates:
        return ""

    try:
        want = _instant(game_row["start_time"])
    except (KeyError, IndexError):
        want = None  # caller selected the row without start_time

    if want is not None:
        for eg in candidates:
            if _instant(eg.get("date")) == want:
                return eg["game_id"]
        return ""  # fail closed: known instant, no event at it

    return candidates[0]["game_id"]


def _neighbour_days(date_str):
    """The day itself first, then the day before and after.

    prop_games.date is derived from a UTC first pitch; ESPN's scoreboard is keyed
    by LOCAL date. A 01:40Z start is the previous evening in the US, so the event
    sits on the day BEFORE the one our row is filed under. Same day first so an
    exact match still wins.
    """
    import datetime as _dt
    try:
        base = _dt.date.fromisoformat(date_str)
    except (TypeError, ValueError):
        return [date_str]
    return [date_str,
            (base - _dt.timedelta(days=1)).isoformat(),
            (base + _dt.timedelta(days=1)).isoformat()]


def link_existing_games(con: sqlite3.Connection, dry_run: bool = False,
                        relink: bool = False) -> int:
    """Link prop_games to ESPN events.

    `relink=True` also re-examines rows that already carry an espn_event_id, which
    is how the 85 rows bound to the wrong game of a series get corrected. It only
    writes when the answer actually changes.
    """
    where = "" if relink else "WHERE espn_event_id IS NULL OR espn_event_id = ''"
    unlinked = con.execute(f"""
        SELECT id, league, date, start_time, home, away, espn_event_id
        FROM prop_games {where}
    """).fetchall()

    if not unlinked:
        print("All prop_games already linked.")
        return 0

    # Group by date+league to minimize ESPN calls
    from collections import defaultdict
    by_date_league = defaultdict(list)
    for g in unlinked:
        by_date_league[(g["date"], g["league"])].append(g)

    linked = 0
    changed = 0
    for (date, league), games in by_date_league.items():
        print(f"\n  {date} {league}: {len(games)} games to link")
        # The neighbouring slates matter: prop_games.date comes from a UTC first
        # pitch, ESPN's scoreboard is keyed by LOCAL date, so the event we want is
        # routinely filed under the day before. Without this the correct game is
        # not even a candidate and the team match lands on the wrong one.
        espn_games = []
        seen_ids = set()
        for day in _neighbour_days(date):
            try:
                for eg in espn.games(league, day):
                    if str(eg.get("game_id")) not in seen_ids:
                        seen_ids.add(str(eg.get("game_id")))
                        espn_games.append(eg)
            except Exception as e:
                print(f"    ESPN pull failed for {day}: {e}")
        if not espn_games:
            continue

        for g in games:
            espn_id = link_prop_game(con, g, espn_games)
            prev = g["espn_event_id"] or ""
            if espn_id:
                if espn_id != prev:
                    if not dry_run:
                        con.execute("UPDATE prop_games SET espn_event_id=? WHERE id=?", (espn_id, g["id"]))
                    changed += 1
                    tag = f"→ {espn_id}" if not prev else f"{prev} → {espn_id}  CORRECTED"
                    print(f"    game {g['id']}: {g['away']} @ {g['home']} {tag}")
                linked += 1
            else:
                print(f"    game {g['id']}: {g['away']} @ {g['home']} → NO MATCH"
                      + (f" (was {prev}, left alone)" if prev else ""))
    print(f"\n  {linked} linked, {changed} changed")

    if not dry_run:
        con.commit()
    return linked


def main():
    dry_run = "--dry-run" in sys.argv
    relink = "--relink" in sys.argv

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    print("Linking prop_games → ESPN event IDs...")
    linked = link_existing_games(con, dry_run=dry_run, relink=relink)

    if dry_run:
        print(f"\nDRY RUN — {linked} would be linked")
    else:
        print(f"\nLinked {linked} prop_games")
        # Verify
        total = con.execute("SELECT COUNT(*) FROM prop_games").fetchone()[0]
        with_id = con.execute("SELECT COUNT(*) FROM prop_games WHERE espn_event_id IS NOT NULL AND espn_event_id != ''").fetchone()[0]
        print(f"  {with_id}/{total} games now have espn_event_id")

    con.close()


if __name__ == "__main__":
    main()
