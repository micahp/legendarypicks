#!/usr/bin/env python3
"""
link_prop_games.py — Crosswalk: match prop_games to ESPN games and populate espn_event_id.

Matches by: league + date + normalized team abbreviation.
Runs on existing rows AND usable as a library for ingest_props.py going forward.

Usage: venv/bin/python link_prop_games.py [--dry-run] [--relink] [--league LG]

--league scopes the run to one league, which is a REQUEST BUDGET control: an
unscoped run fetches a scoreboard per league+date across every league with props.

--relink also re-checks rows that already carry an espn_event_id, correcting any
bound to the wrong game of a series (85 MLB rows on 2026-08-11).
"""
from __future__ import annotations  # this box runs 3.8; `int | None` is 3.10 syntax

import sys, os, sqlite3, re, unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import espn_client as espn
from prop_game_merge import fold_prop_game
from publisher_capture import capture_payload, require_publisher_capture_schema

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")


def _scoreboard_endpoint(league: str, date: str) -> str:
    """The native scoreboard URL that produced a linker candidate slate."""
    _, path = espn._check(league)
    return espn._SITE.format(path=path) + "/scoreboard?dates=" + date.replace("-", "")


def _scoreboard_games(league: str, date: str, connection, *, capture: bool) -> list:
    """Capture a source scoreboard before normalizing it for event linking."""
    raw = espn.scoreboard_raw(league, date)
    if capture:
        capture_payload(
            connection, source="espn", league=league,
            endpoint=_scoreboard_endpoint(league, date), payload=raw,
        )
    from espn_client.scoreboard import _games_from_payload
    return _games_from_payload(league, date, raw)

# Team name → abbreviation lookup (built from ESPN data on the fly + a static fallback)
# ESPN returns team abbrev in game data, so we match by abbreviation.
# prop_games has full team names like "Philadelphia Phillies" — we need to normalize to "PHI".

# Static MLB team name → abbreviation map (covers common names)
_MLB_TEAM_MAP = {
    "arizona diamondbacks": "ARI", "atlanta braves": "ATL", "baltimore orioles": "BAL",
    # CHW, not CWS. ESPN publishes CHW and this repo is canonically CHW —
    # team_codes.py:43 carries the CWS -> CHW correction and
    # refresh_mlb_player_teams.py states the rule outright. This map was the one
    # place that never got it, and because the abbrev is what the linker matches
    # on, every White Sox game silently failed to link.
    "boston red sox": "BOS", "chicago cubs": "CHC", "chicago white sox": "CHW",
    "cincinnati reds": "CIN", "cleveland guardians": "CLE", "colorado rockies": "COL",
    "detroit tigers": "DET", "houston astros": "HOU", "kansas city royals": "KC",
    "los angeles angels": "LAA", "los angeles dodgers": "LAD", "miami marlins": "MIA",
    "milwaukee brewers": "MIL", "minnesota twins": "MIN", "new york mets": "NYM",
    "new york yankees": "NYY",
    # The club left Oakland; ESPN publishes it as ATH and no longer publishes OAK
    # at all. Both spellings are kept because a sportsbook may still say the old
    # name, but they resolve to the code the publisher actually uses — an alias
    # pointing at a retired code is a name that looks handled and links nothing.
    "oakland athletics": "ATH", "athletics": "ATH",
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

# MLS: Bovada's club name -> ESPN's abbreviation, recorded from the publisher's own
# scoreboard payload on 2026-08-15/16 (all 30 clubs appeared across those two slates).
#
# The name-equality path added on 08-11 fixed the dead `displayName` read but still
# required the two publishers to spell a club the same way, and for 8 of 13 unlinked
# games they do not: Bovada says "New York Red Bulls" where ESPN says "Red Bull New
# York" (different word order), "DC United" vs "D.C. United" (punctuation), "Los
# Angeles FC" vs "LAFC" (contraction), and a whole family of dropped corporate
# suffixes — Atlanta United/Inter Miami/Minnesota United/Houston Dynamo/Orlando City
# all carry FC, CF or SC on ESPN's side and none on Bovada's.
#
# Written as a recorded vocabulary rather than a normaliser on purpose. A suffix
# stripper plus fuzzy matching gets all eight of these and also silently accepts
# "San Diego FC" for San Jose, which is a wrongly linked game — props bound to the
# wrong club, settling against the wrong boxscore, with nothing to notice it. An
# unlinked row is visibly missing; a mislinked one is not.
_MLS_TEAM_MAP = {
    "atlanta united": "ATL", "austin fc": "ATX", "cf montréal": "MTL",
    "cf montreal": "MTL", "charlotte fc": "CLT", "chicago fire": "CHI",
    "colorado rapids": "COL", "columbus crew": "CLB", "dc united": "DC",
    "d.c. united": "DC", "fc cincinnati": "CIN", "fc dallas": "DAL",
    "houston dynamo": "HOU", "inter miami": "MIA", "la galaxy": "LA",
    "los angeles fc": "LAFC", "lafc": "LAFC", "minnesota united": "MIN",
    "nashville sc": "NSH", "new england revolution": "NE",
    "new york city fc": "NYC", "new york red bulls": "RBNY",
    "red bull new york": "RBNY", "orlando city": "ORL",
    "philadelphia union": "PHI", "portland timbers": "POR",
    "real salt lake": "RSL", "san diego fc": "SD",
    "san jose earthquakes": "SJ", "seattle sounders": "SEA",
    "sporting kansas city": "SKC", "st. louis city sc": "STL",
    "toronto fc": "TOR", "vancouver whitecaps": "VAN",
}

_TEAM_MAPS = {"mlb": _MLB_TEAM_MAP, "nba": _NBA_TEAM_MAP, "nfl": _NFL_TEAM_MAP,
              "nhl": _NHL_TEAM_MAP, "wc": _WC_TEAM_MAP, "mls": _MLS_TEAM_MAP}

# Leagues whose map is the publisher's COMPLETE club list, so a name that misses it
# is a name we have never seen — not a near miss to guess at. The first-three-letters
# fallback stays available to the leagues whose maps are admittedly partial, and is
# refused here: MLS is precisely where it collides ("San Diego FC" and "San Jose
# Earthquakes" both yield SAN).
_EXHAUSTIVE_MAPS = frozenset({"mls"})


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
    # Fuzzy: try substring match. Where the map is the publisher's complete club
    # list, an ambiguous substring is a refusal rather than a coin flip — "new york"
    # is inside both "new york city fc" and "new york red bulls", and whichever one
    # dict order happened to reach first would bind the props to that club and look
    # exactly like a successful link.
    hits = [abbrev for name, abbrev in team_map.items()
            if key in name or name in key]
    if len(set(hits)) > 1 and league in _EXHAUSTIVE_MAPS:
        return ""
    if hits:
        return hits[0]
    # No map for this league at all: say "unknown" instead of inventing one.
    #
    # The first-three-letters fallback below is a last resort AMONG KNOWN TEAMS,
    # where a near miss still lands in the right league's vocabulary. Applied to
    # a league we have no map for it manufactures collisions: MLS alone gives
    # "San Diego FC" -> SAN and "San Jose Earthquakes" -> SAN, and a matcher that
    # accepts either would bind a game's props to the wrong club silently. An
    # unlinked row is visibly missing and fixable; a wrongly linked one is not.
    # Callers match on the published team NAME for these leagues instead.
    if not team_map:
        return ""
    # Nor where the map IS the publisher's full club list. This comment's own example
    # is now a live map rather than a hypothetical, so the guard has to hold: a name
    # that missed 34 recorded spellings of 30 clubs is an unknown club, and three
    # letters of it is a guess that reads as an answer.
    if league in _EXHAUSTIVE_MAPS:
        return ""
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


def apply_start_time(con, game_id, published, stored, label=""):
    """Store the publisher's kickoff instant, overwriting ours only when it DISAGREES.

    Policy set by Micah 2026-08-17, replacing write-once. All three ingest paths
    (`routers/props.py`, `bovada_scraper.py` x2) guarded on `if published and not stored`,
    so the first value we ever saw was permanent: a publisher revising first pitch could
    never propagate, which is ~20 of prod's 95 start_time disagreements. That is the +17h
    /+19h class, separate from the +24h UTC-rollover class.

    Write-once and last-writer-wins are both wrong here for the same reason -- neither asks
    whether the two values differ:

      * write-once  freezes a bad instant forever, and a wrong kickoff is not a cosmetic
                    defect: the board files the game on the wrong day and settlement looks
                    for it at the wrong time.
      * last-writer every scrape rewrites the row on its 30-minute timer, so `mtime` and any
        -wins     "what changed?" audit become noise, and a stale board can overwrite a
                  good instant with an old one.

    So: compare INSTANTS, not strings. `prop_games` stores `2026-08-11T01:40:00+00:00` and
    ESPN sends `2026-08-11T01:40Z`; they are the same moment and must not count as a change.
    A real disagreement is written and ANNOUNCED, because a moved kickoff is exactly the
    signal a human wants to see in a run log -- it is usually a reschedule.

    Note what this does NOT do: a game moved to a DIFFERENT DAY is not this function's
    problem. Every ingest path looks its row up by (league, date, home, away), so a new date
    creates a second row and leaves the original holding its props. Nothing in the pipeline
    records postponements at all -- `team_game_results.status` only ever holds 'completed'
    or 'scheduled' -- and ESPN issues makeups under a NEW event id, so the original can
    never link to one. See BACKLOG-holes #46.

    Returns "set", "moved", "same" or "skipped" so callers can count.
    """
    if not published:
        return "skipped"          # never blank a known instant with a publisher's silence
    if not stored:
        con.execute("UPDATE prop_games SET start_time=? WHERE id=?", (published, game_id))
        return "set"
    if _instant(published) == _instant(stored):
        return "same"
    con.execute("UPDATE prop_games SET start_time=? WHERE id=?", (published, game_id))
    print("    start_time moved%s: %s -> %s" % (label and " " + label, stored, published))
    return "moved"


def _fighter_key(name):
    """Accent-fold a fighter name to its alphanumeric identity key."""
    value = unicodedata.normalize("NFKD", str(name or "")).encode(
        "ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _fighter_parts(name):
    value = unicodedata.normalize("NFKD", str(name or "")).encode(
        "ascii", "ignore").decode("ascii")
    return re.findall(r"[a-z0-9]+", value.lower())


def _same_fighter(prop_name, espn_name):
    """Match exact, bookmaker-truncated, or first/last UFC fighter names.

    Bovada truncates the displayed fighter names (``Christian Ler``), while
    ESPN retains accents and middle names (``Jose Miguel Delgado``).  A prefix
    needs at least seven normalized characters; shorter prefixes are too easy to
    collide on one card.
    """
    prop_key = _fighter_key(prop_name)
    espn_key = _fighter_key(espn_name)
    if not prop_key or not espn_key:
        return False
    if prop_key == espn_key:
        return True
    if min(len(prop_key), len(espn_key)) >= 7:
        if prop_key.startswith(espn_key) or espn_key.startswith(prop_key):
            return True
    prop_parts = _fighter_parts(prop_name)
    espn_parts = _fighter_parts(espn_name)
    return (len(prop_parts) >= 2 and len(espn_parts) >= 2
            and prop_parts[0] == espn_parts[0]
            and prop_parts[-1] == espn_parts[-1])


def _link_ufc_fight(game_row, espn_games):
    """Resolve an unordered fighter pair to one UFC competition id.

    UFC ``home``/``away`` is an artificial slot and the two publishers reverse
    it on real fights.  ESPN also publishes a card-segment start for several
    bouts at once, while the prop feed publishes rolling bout estimates, so time
    is not an identity key here.  Prefer both fighter names.  Permit one name
    only when it identifies exactly one fight on the slate and the other prop
    name matches no published fighter at all (the measured nickname case is
    Eduardo Henrique / Eduardo Chapolin).  Every ambiguity fails closed.
    """
    prop_names = [game_row["away"], game_row["home"]]

    def names(game):
        return [((game.get("away") or {}).get("name") or ""),
                ((game.get("home") or {}).get("name") or "")]

    strong = {}
    for game in espn_games:
        published = names(game)
        if ((_same_fighter(prop_names[0], published[0])
             and _same_fighter(prop_names[1], published[1]))
                or (_same_fighter(prop_names[0], published[1])
                    and _same_fighter(prop_names[1], published[0]))):
            strong[str(game.get("game_id") or "")] = game
    strong.pop("", None)
    if len(strong) == 1:
        return next(iter(strong.values()))["game_id"]
    if strong:
        return ""

    matches = []
    for prop_name in prop_names:
        hits = {}
        for game in espn_games:
            if any(_same_fighter(prop_name, published) for published in names(game)):
                hits[str(game.get("game_id") or "")] = game
        hits.pop("", None)
        matches.append(hits)

    if len(matches[0]) == 1 and not matches[1]:
        return next(iter(matches[0].values()))["game_id"]
    if len(matches[1]) == 1 and not matches[0]:
        return next(iter(matches[1].values()))["game_id"]
    return ""


def _link_tennis_match(con: sqlite3.Connection, game_row, espn_games: list) -> str:
    """Link an ATP/WTA prop game by its two already-published ESPN athletes.

    Tennis display names are not a stable crosswalk: ESPN may omit a surname
    (``Daniel Merida`` vs the book's ``Daniel Merida Aguilar``) or reverse the
    order (``Wang Xinyu`` vs ``Xinyu Wang``).  The props have already resolved
    both people to ESPN IDs, which is stronger evidence than a time supplied by
    a sportsbook.  When only one side has a prop, pair that ID with the exact
    two-name matchup.  Anything absent or ambiguous remains unlinked.
    """
    if con is None:
        return ""
    rows = con.execute("""
        SELECT DISTINCT pl.espn_id
        FROM props p JOIN players pl ON pl.id = p.player_id
        WHERE p.game_id=? AND pl.league=? AND NULLIF(pl.espn_id, '') IS NOT NULL
    """, (game_row["id"], game_row["league"])).fetchall()
    wanted = {str(row["espn_id"] if hasattr(row, "keys") else row[0]) for row in rows}
    if not wanted or len(wanted) > 2:
        return ""

    def _name_tokens(value):
        folded = unicodedata.normalize("NFKD", str(value or "")).encode(
            "ascii", "ignore").decode("ascii").lower()
        return set(re.findall(r"[a-z0-9]+", folded))

    def _same_tennis_name(left, right):
        """Accept reordering or one publisher-omitted surname, never fuzzy text."""
        a, b = _name_tokens(left), _name_tokens(right)
        if len(a) < 2 or len(b) < 2:
            return False
        if a == b:
            return True
        short, long = (a, b) if len(a) < len(b) else (b, a)
        return short <= long and len(long) == len(short) + 1

    matches = {}
    for game in espn_games:
        sides = [game.get("home") or {}, game.get("away") or {}]
        published = {str(side.get("athlete_id") or "") for side in sides}
        published.discard("")
        published_names = [side.get("name") or "" for side in sides]
        prop_names_list = [game_row["home"] or "", game_row["away"] or ""]
        names_match = (
            (_same_tennis_name(prop_names_list[0], published_names[0])
             and _same_tennis_name(prop_names_list[1], published_names[1]))
            or (_same_tennis_name(prop_names_list[0], published_names[1])
                and _same_tennis_name(prop_names_list[1], published_names[0]))
        )
        if wanted <= published and names_match:
            game_id = str(game.get("game_id") or "")
            if game_id:
                matches[game_id] = game
    if len(matches) == 1:
        return next(iter(matches))
    return ""


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
    if league == "ufc":
        return _link_ufc_fight(game_row, espn_games)
    if league in {"atp", "wta"}:
        return _link_tennis_match(con, game_row, espn_games)

    home_norm = _norm_team(game_row["home"], league)
    away_norm = _norm_team(game_row["away"], league)
    pg_home_name = (game_row["home"] or "").lower()
    pg_away_name = (game_row["away"] or "").lower()

    def _team_names(side):
        """Every name this payload publishes for a team, lowercased.

        The name fallback used to read `displayName` alone, which the scoreboard
        payload does not carry — measured 2026-08-11 against a real MLS response,
        whose team objects hold abbrev/name/nickname/score/winner and no
        displayName. So the fallback compared against None for every game and the
        whole branch was dead. That is why MLS linked 2 of 15: the abbrev path
        has no MLS map, and the name path was reading a key that isn't there.
        Read all of them; a publisher naming a field differently is not absence.
        """
        return {
            (side.get(k) or "").lower()
            for k in ("displayName", "name", "shortDisplayName", "nickname")
            if side.get(k)
        }

    def _same_matchup(eg):
        # Abbrevs only when BOTH sides normalised to something real. _norm_team
        # returns "" for a league with no map, and ""=="" would otherwise call
        # every game on the slate a match.
        if home_norm and away_norm:
            if (eg["home"]["abbrev"].upper() == home_norm
                    and eg["away"]["abbrev"].upper() == away_norm):
                return True
        return (pg_home_name in _team_names(eg["home"])
                and pg_away_name in _team_names(eg["away"]))

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


def _scope(league: str, relink: bool, days: int | None) -> tuple[str, list]:
    """The WHERE that decides which prop_games a run considers, and its params.

    Built once and used by both the budget estimate and the run itself. They used
    to be two copies of the same clause list, which is a quiet way for a tool to
    spend a budget it did not announce.

    `days` is the window that makes the nightly job possible at all. Without it
    every run reconsiders every slate ever ingested — 54 of them, most from games
    that finished in June and will never link — and that is what tripped the
    ceiling. A game that has been unlinked for two months is not going to link
    tonight; a backfill is a deliberate, scoped, human-run thing.
    """
    clauses = [] if relink else ["(espn_event_id IS NULL OR espn_event_id = '')"]
    # Orphaned prop_game shells cannot be crosswalked and used to consume the
    # entire ESPN request budget on old tennis dates.  Only a row with props
    # has the identity evidence this tool is authorized to link.
    clauses.append("EXISTS (SELECT 1 FROM props WHERE props.game_id = prop_games.id)")
    params: list = []
    if league:
        clauses.append("league = ?")
        params.append(league.lower())
    if days is not None:
        clauses.append("date >= DATE('now', ?)")
        params.append(f"-{int(days)} days")
    return (("WHERE " + " AND ".join(clauses)) if clauses else ""), params


def link_existing_games(con: sqlite3.Connection, dry_run: bool = False,
                        relink: bool = False, league: str = "",
                        days: int | None = None) -> int:
    """Link prop_games to ESPN events.

    `relink=True` also re-examines rows that already carry an espn_event_id, which
    is how the 85 rows bound to the wrong game of a series get corrected. It only
    writes when the answer actually changes.

    `league` scopes the run to one league. This is a REQUEST BUDGET control, not a
    convenience: ESPN's limit is a count per host (~100), not a rate, so the only
    lever that works is issuing fewer requests. An unscoped run fetches a
    scoreboard for every distinct date across every league that has props —
    tennis alone contributes dozens — and spends that budget whether or not you
    care about the league you are fixing. See .claude/skills/espn-request-budget.
    """
    where, params = _scope(league, relink, days)
    unlinked = con.execute(f"""
        SELECT id, league, date, start_time, home, away, espn_event_id
        FROM prop_games {where}
    """, params).fetchall()

    if not unlinked:
        print("All prop_games already linked.")
        return 0

    # A real link run changes durable game identity, so it must retain the raw
    # scoreboard that justified that change.  Check before the first request;
    # dry runs deliberately remain side-effect free and therefore do not claim
    # a durable source capture.
    if not dry_run:
        require_publisher_capture_schema(con)

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
        for day in espn.neighbor_dates(date):
            try:
                for eg in _scoreboard_games(league, day, con, capture=not dry_run):
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
                    # Another row may already BE this event. That is not an error and not
                    # a bad link -- it is the same fixture stored twice under two calendar
                    # dates (see the neighbour-slate comment above), and linking is the
                    # moment we can finally prove it. Fold this row into that one instead
                    # of creating the second row that ux_prop_games_event now forbids.
                    #
                    # Without this the constraint turns a nightly timer into an
                    # IntegrityError, and the duplicate it was meant to prevent becomes a
                    # failed run instead.
                    existing = con.execute(
                        "SELECT id FROM prop_games WHERE league=? AND espn_event_id=? "
                        "AND id!=?", (g["league"], espn_id, g["id"])).fetchone()
                    if existing:
                        merged_into = existing["id"] if hasattr(existing, "keys") else existing[0]
                        if not dry_run:
                            fold_prop_game(con, g["id"], merged_into)
                        print(f"    game {g['id']}: {g['away']} @ {g['home']} is event "
                              f"{espn_id}, already held by game {merged_into} — props "
                              f"repointed, duplicate row removed")
                        changed += 1
                        linked += 1
                        continue
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
    league = ""
    days: int | None = None
    for i, a in enumerate(sys.argv):
        if a == "--league" and i + 1 < len(sys.argv):
            league = sys.argv[i + 1]
        elif a.startswith("--league="):
            league = a.split("=", 1)[1]
        elif a == "--days" and i + 1 < len(sys.argv):
            days = int(sys.argv[i + 1])
        elif a.startswith("--days="):
            days = int(a.split("=", 1)[1])

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # State the request count BEFORE issuing any of it. ESPN's ceiling is a count
    # per host, so a job that cannot say what it will spend is a job nobody can
    # size afterwards (espn-request-budget skill, §6).
    where, params = _scope(league, relink, days)
    slate_rows = con.execute(
        f"SELECT DISTINCT league, date FROM prop_games {where}", params
    ).fetchall()
    # Each slate fetches THREE scoreboards, not one: the day plus its neighbours,
    # because prop_games.date is a UTC start and ESPN keys by local date. Counting
    # slates would understate the spend by 3x, and a budget line that lies is
    # worse than no budget line.
    slates = len(slate_rows)
    requests = slates * 3
    distinct_days = {(r["league"], d) for r in slate_rows
                     for d in espn.neighbor_dates(r["date"])}
    scope = league.lower() if league else "ALL leagues"
    print(f"Linking prop_games → ESPN event IDs [{scope}]")
    print(f"  budget: {requests} scoreboard requests to site.web.api.espn.com "
          f"({slates} slates x 3 neighbour days)")
    print(f"  {len(distinct_days)} are distinct; the repeats cost nothing only if "
          f"LP_ESPN_CACHE_DIR is set (it is "
          f"{'set' if os.environ.get('LP_ESPN_CACHE_DIR') else 'NOT set'})")
    # The guard applies to --dry-run TOO. A dry run skips the DB write, not the
    # HTTP: it issues every request a real run would. Measured 2026-08-11, an
    # unscoped run over this database is 189 requests against a host whose
    # ceiling is about 100, so the tool tripped the wall by design and two
    # "harmless" dry runs are what spent it. A 403 is often one you caused.
    # Judge the guard on what will actually be ISSUED. The three neighbour days of
    # adjacent slates overlap heavily, so a cached run spends `distinct_days` and
    # the raw `requests` figure it used to refuse on is a number that never leaves
    # the process — MLB scoped to one league reads 153 and issues 60. Refusing a
    # run that fits the budget is not a safe error: it pushes you toward the
    # override, which turns the guard off entirely for the run where it might
    # otherwise have mattered.
    #
    # Without a cache dir every repeat IS a request, so the raw count stands.
    spend = len(distinct_days) if os.environ.get("LP_ESPN_CACHE_DIR") else requests
    if spend > 50 and not os.environ.get("LP_LINK_ALLOW_BIG_RUN"):
        print(f"  REFUSING: {spend} requests to one host, ceiling is ~100.")
        print("  Scope it with --league. Pacing does not buy budget — only")
        print("  issuing fewer requests does. Override: LP_LINK_ALLOW_BIG_RUN=1")
        if spend == requests and len(distinct_days) <= 50:
            print(f"  (set LP_ESPN_CACHE_DIR and this run is {len(distinct_days)} "
                  f"requests, which is under the guard.)")
        print("  Or scope the window with --days N; the nightly job wants ~3.")
        con.close()
        # Exit NON-ZERO. This used to return 0, and run_pipeline.py checks the exit
        # code — so the nightly cron has been printing "link: ✅" on top of a refusal
        # every 30 minutes. That is why nothing was ever linked and why the state
        # got blamed on ESPN being down: the run that would have said otherwise
        # reported success. A refusal is a job that did not do its work.
        return 2
    linked = link_existing_games(con, dry_run=dry_run, relink=relink, league=league,
                                 days=days)

    if dry_run:
        print(f"\nDRY RUN — {linked} would be linked")
    else:
        print(f"\nLinked {linked} prop_games")
        # Verify
        total = con.execute("SELECT COUNT(*) FROM prop_games").fetchone()[0]
        with_id = con.execute("SELECT COUNT(*) FROM prop_games WHERE espn_event_id IS NOT NULL AND espn_event_id != ''").fetchone()[0]
        print(f"  {with_id}/{total} games now have espn_event_id")

    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main() or 0)
