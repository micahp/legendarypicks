#!/usr/bin/env python3
"""
link_prop_games.py — Crosswalk: match prop_games to ESPN games and populate espn_event_id.

Matches by: league + date + normalized team abbreviation.
Runs on existing rows AND usable as a library for ingest_props.py going forward.

Usage: venv/bin/python link_prop_games.py [--dry-run]
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

_TEAM_MAPS = {"mlb": _MLB_TEAM_MAP, "nba": _NBA_TEAM_MAP, "nfl": _NFL_TEAM_MAP, "nhl": _NHL_TEAM_MAP}


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


def link_prop_game(con: sqlite3.Connection, game_row, espn_games: list) -> str:
    """Try to link one prop_game to an ESPN game. Returns espn_event_id or ''."""
    league = game_row["league"]
    date = game_row["date"]
    home_norm = _norm_team(game_row["home"], league)
    away_norm = _norm_team(game_row["away"], league)

    for eg in espn_games:
        eg_home = eg["home"]["abbrev"].upper()
        eg_away = eg["away"]["abbrev"].upper()
        if eg_home == home_norm and eg_away == away_norm:
            return eg["game_id"]
        # Also try displayName match
        eg_home_name = (eg["home"].get("displayName") or "").lower()
        eg_away_name = (eg["away"].get("displayName") or "").lower()
        pg_home_name = (game_row["home"] or "").lower()
        pg_away_name = (game_row["away"] or "").lower()
        if eg_home_name == pg_home_name and eg_away_name == pg_away_name:
            return eg["game_id"]
    return ""


def link_existing_games(con: sqlite3.Connection, dry_run: bool = False) -> int:
    """Link all prop_games that have empty espn_event_id."""
    unlinked = con.execute("""
        SELECT id, league, date, home, away FROM prop_games 
        WHERE espn_event_id IS NULL OR espn_event_id = ''
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
    for (date, league), games in by_date_league.items():
        print(f"\n  {date} {league}: {len(games)} games to link")
        try:
            espn_games = espn.games(league, date)
        except Exception as e:
            print(f"    ESPN pull failed: {e}")
            continue

        for g in games:
            espn_id = link_prop_game(con, g, espn_games)
            if espn_id:
                if not dry_run:
                    con.execute("UPDATE prop_games SET espn_event_id=? WHERE id=?", (espn_id, g["id"]))
                linked += 1
                print(f"    game {g['id']}: {g['away']} @ {g['home']} → {espn_id}")
            else:
                print(f"    game {g['id']}: {g['away']} @ {g['home']} → NO MATCH")

    if not dry_run:
        con.commit()
    return linked


def main():
    dry_run = "--dry-run" in sys.argv

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    print("Linking prop_games → ESPN event IDs...")
    linked = link_existing_games(con, dry_run=dry_run)

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
