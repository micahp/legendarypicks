#!/usr/bin/env python3
"""Ingest NCAAF (college football) FBS player logs from CollegeFootballData (CFBD).

Why CFBD instead of ESPN summaries (decision 2026-08-07: CFBD permitted — the
"do not use cfbd key" ruling was news-engine-only; verified live same day):

- ~139 requests for the whole season (1 /games + 1 /teams + 137 per-team
  /games/players) vs 888 summary fetches.
- /games/players returns ESPN event ids and ESPN athlete ids verbatim, so rows
  join the spine directly on espn_id — no name-resolution pass. Athletes the
  spine does not know yet are added (self-heal), like the MLS resolve pass.
- The payload includes FCS buy-game opponents (verified: Alabama-Eastern
  Illinois carried 229 EIU player rows), so the 230-team population survives.
- It publishes defensive categories (tackles/sacks/INTs) ESPN's summaries
  lack; those map into the stats JSON line, closing the LEAGUE-STAT-GAPS
  defensive gap.

The payload mirrors ESPN's football boxscore contract: games -> teams[] ->
categories[] -> types[] -> athletes[]. This module reuses the ESPN ingest's
stat mapping shape (our key <- (group, label)) and merges per athlete per
game exactly like the ESPN ingest.

Re-source semantics: the existing ncaaf rows for the season are deleted first,
then replaced — player_game_logs is single-source per (league, season) after
this run. Rows key on UNIQUE(league, source_player_key, season, game_no) where
source_player_key = ESPN athlete id and game_no = ESPN event id.

Usage:
  python3 ingest_cfbd_logs.py --season 2025 [--dry-run]
"""
import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import team_codes
from ingest_nfl_logs import ensure_table  # shared player_game_logs schema

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)

LEAGUE = "ncaaf"
GAME_TYPE = "REG"
_API = "https://api.collegefootballdata.com"
_MIN_INTERVAL = float(os.environ.get("LP_CFBD_MIN_INTERVAL") or 1.0)  # free tier ~1 req/s
_HDRS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}

# our key <- (published group name, published label) — the offense half is the
# same vocabulary the ESPN ingest measured (passing C/ATT,YDS,AVG,TD,INT;
# rushing CAR,YDS,AVG,TD,LONG; receiving REC,YDS,AVG,TD,LONG).
_STAT_MAP = {
    ("passing", "catt"): "att",
    ("passing", "yds"): "pass_yds",
    ("passing", "td"): "pass_td",
    ("passing", "int"): "intc",
    ("rushing", "yds"): "rush_yds",
    ("rushing", "td"): "rush_td",
    ("receiving", "rec"): "rec",
    ("receiving", "yds"): "rec_yds",
    ("receiving", "td"): "rec_td",
}

# Defensive keys, measured from the same payload family (labels TOT,SOLO,
# SACKS,TFL,PD,"QB HUR",TD and INT,YDS,TD). These close the defensive gap the
# ESPN summaries never published. Namespaced (def_*) so a defensive INT can
# never collide with the passing intc.
_DEF_STAT_MAP = {
    ("defensive", "tot"): "tackles",
    ("defensive", "solo"): "tackles_solo",
    ("defensive", "sacks"): "sacks",
    ("defensive", "tfl"): "tfl",
    ("defensive", "pd"): "pd",
    ("defensive", "qbhur"): "qbhur",
    ("defensive", "td"): "def_td",
    ("interceptions", "int"): "def_int",
    ("interceptions", "yds"): "def_int_yds",
    ("interceptions", "td"): "def_int_td",
}


def _key(value) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _number(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _api_key():
    key = os.environ.get("CFBD_API_KEY")
    if key:
        return key
    env_path = os.path.join(os.path.expanduser("~"), ".hermes", ".env")
    try:
        with open(env_path) as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("CFBD_API_KEY="):
                    return line.split("=", 1)[1]
    except OSError:
        pass
    raise RuntimeError("CFBD_API_KEY not found (env or ~/.hermes/.env)")


_last_request = [0.0]


class CfbdError(Exception):
    pass


def _get_json(url):
    """One paced CFBD request with a short 429/5xx ladder.

    CFBD's free tier is ~1 request/second; pacing is the budget, and a 429 is
    waited out briefly (never a 403 — CFBD does not wall like ESPN).
    """
    global _last_request
    gap = _MIN_INTERVAL - (time.monotonic() - _last_request[0])
    if gap > 0:
        time.sleep(gap)
    attempts = 4
    last = None
    for i in range(attempts):
        req = urllib.request.Request(url, headers=_HDRS)
        req.add_header("Authorization", "Bearer " + _api_key())
        try:
            _last_request[0] = time.monotonic()
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = "HTTP %s" % e.code
            if e.code in (400, 401, 403):
                break  # a real error; retrying will not fix it
            time.sleep(min(30, 2.0 * (i + 1)))
        except OSError as e:
            last = "%s: %s" % (type(e).__name__, e)
            time.sleep(min(30, 2.0 * (i + 1)))
    raise CfbdError("%s failed after %d attempts: %s" % (url, attempts, last))


def _line_stats(group_name, type_name, stat, maps):
    """Our stat value from one (group, type, stat) triple."""
    group = _key(group_name)
    label = _key(type_name)
    target = maps.get((group, label))
    if target is None:
        return None
    if target == "att" and isinstance(stat, str) and "/" in stat:
        parts = stat.split("/")
        num = _number(parts[-1]) if parts[-1].strip() else None
    else:
        num = _number(stat)
    return (target, num) if num is not None else None


def _merge_game_athletes(game):
    """Yield (athlete_id, name, team_school, home_away, stats) per athlete.

    Mirrors the ESPN ingest: one athlete spans several types within a
    category and several categories (e.g. a WR who also returns punts), so
    lines merge per athlete id before yielding.
    """
    merged = {}
    for team_block in game.get("teams") or []:
        school = (team_block.get("team") or "").strip()
        home_away = team_block.get("homeAway")
        for category in team_block.get("categories") or []:
            group_name = category.get("name") or ""
            for type_entry in category.get("types") or []:
                type_name = type_entry.get("name") or ""
                for athlete in type_entry.get("athletes") or []:
                    athlete_id = str(athlete.get("id") or "")
                    name = (athlete.get("name") or "").strip()
                    if not athlete_id or not name:
                        continue
                    mapped = _line_stats(group_name, type_name, athlete.get("stat"), _STAT_MAP)
                    if mapped is None:
                        mapped = _line_stats(group_name, type_name, athlete.get("stat"), _DEF_STAT_MAP)
                    if mapped is None:
                        continue
                    key, num = mapped
                    entry = merged.setdefault(athlete_id, [name, school, home_away, {}])
                    entry[3][key] = num
    for athlete_id, (name, school, home_away, stats) in merged.items():
        yield athlete_id, name, school, home_away, stats


def _team_code(abbrev):
    raw = (abbrev or "").strip().upper()
    if not raw:
        return None
    try:
        return team_codes.normalize(LEAGUE, raw)
    except Exception:
        return raw


# ESPN display names by canonical code (docs/espn-team-codes-2026-07-27.json).
# CFBD's abbreviations mostly match ESPN's, but three FBS schools differ
# (Air Force=AF vs AFA, Buffalo=BUF vs BUFF, Jacksonville State=JXST vs JVST);
# their school names are still prefixes of the ESPN display names, so match on
# the name when the abbreviation does not resolve.
_NAME_BY_CODE = {}
try:
    with open(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "docs",
        "espn-team-codes-2026-07-27.json",
    )) as _fh:
        _NAME_BY_CODE = {
            code: str(name or "").lower()
            for code, name in (json.load(_fh).get("ncaaf") or {}).items()
        }
except OSError:
    _NAME_BY_CODE = {}


def _school_to_code(school, abbrev):
    """Canonical ESPN code for a CFBD team, or None (FCS schools etc.)."""
    ab = (abbrev or "").strip().upper()
    if ab and team_codes.is_canonical(LEAGUE, ab):
        return ab
    s = (school or "").strip().lower()
    if s:
        for code, display in _NAME_BY_CODE.items():
            if display.startswith(s):
                return code
    return None


def _opponent(team, home_away, home, away):
    if home_away == "home":
        return away
    if home_away == "away":
        return home
    if team and home and team.upper() == home.upper():
        return away
    if team and away and team.upper() == away.upper():
        return home
    return None


# Names minted with no published position, reported at the end of the run. Empty is the
# expected state and it still prints — a log that only speaks up on failure cannot tell
# "clean" from "never ran" (fail-loudly §3.7).
_MINTED_WITHOUT_POSITION = []


def _published_positions(season):
    """{espn_athlete_id: (position, position_group)} from CFBD's roster, or {}.

    One request per season returns every roster row CFBD publishes (~30,000 for 2025),
    keyed by the same ESPN athlete id this ingest already joins on — so setting the
    position at mint time costs one request, not one per player.

    Returns {} when the roster cannot be read. That is a degraded run, not a failed one:
    the game logs are still worth ingesting. It is reported, and every player minted
    without a position is counted, so the gap is a number in the run output rather than
    something an audit finds months later.
    """
    try:
        rows = _get_json("{}/roster?year={}".format(_API, season))
    except Exception as exc:  # noqa: BLE001 - the logs are still worth having
        print("  WARNING: CFBD roster for {} unavailable ({}) — players minted by this "
              "run will carry no position".format(season, exc))
        return {}
    try:
        from backfill_ncaaf_positions_cfbd import _position_group, _vocabulary
        vocab = _vocabulary()
    except Exception:  # noqa: BLE001
        _position_group, vocab = (lambda position, _v: None), None
    out = {}
    for row in rows or []:
        athlete_id, position = row.get("id"), row.get("position")
        # CFBD writes "?" for an unknown position. Storing that is worse than NULL: it
        # looks like a value and no vocabulary contains it.
        if not athlete_id or not position or position == "?":
            continue
        out[str(athlete_id)] = (position, _position_group(position, vocab))
    print("  CFBD roster {}: {} rows, {} carry a published position"
          .format(season, len(rows or []), len(out)))
    return out


def _spine_index(con):
    """{espn_id: players.id} for the league. O(1) lookups during ingest."""
    idx = {}
    if con is not None:
        try:
            for row in con.execute(
                "SELECT id, espn_id FROM players WHERE league=? AND espn_id IS NOT NULL",
                (LEAGUE,),
            ):
                idx[str(row[1])] = row[0]
        except sqlite3.Error:
            pass
    return idx


def _resolve_or_create(con, spine, athlete_id, name, team, positions=None):
    """players.id by espn_id; inserts the athlete when the spine lacks them.

    CFBD athlete ids ARE ESPN ids, so this is the whole resolution pass — the
    MLS 08-07 pattern (add missing players to the spine, then link) at zero
    extra requests.

    This used to insert `position NULL, position_group NULL` with the comment "left NULL
    for the roster sync to backfill". The roster sync is ingest_mls_ncaaf_rosters.py, which
    reads ESPN's published team rosters — and these athletes are not on them, because they
    are here precisely by having appeared in a game CFBD covered. The promised backfill
    therefore never happened for anybody: measured 2026-08-16, **5,853 active NCAAF players
    carried no position at all, 27% of the league**, and a blank position does not error or
    render an empty state — it renders a generic game log, which reads as coverage
    (fail-loudly §2c).

    CFBD publishes the position itself, keyed by the same athlete id, one request per
    season for all ~30,000 rows. So it is set HERE, at mint time, and the row is never
    written blank in the first place. `positions` is that map; when it is empty (no API
    key) the count of blank rows minted is reported by the caller rather than left to be
    discovered by an audit a month later.
    """
    player_id = spine.get(athlete_id)
    if player_id is not None:
        return player_id
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    position, position_group = (positions or {}).get(str(athlete_id), (None, None))
    con.execute(
        "INSERT INTO players(name, team, league, espn_id, position, position_group, active, updated_at)"
        " VALUES(?,?,?,?,?,?,1,?)",
        (name, team, LEAGUE, athlete_id, position, position_group, now),
    )
    player_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    spine[athlete_id] = player_id
    if position is None:
        _MINTED_WITHOUT_POSITION.append(name)
    return player_id


def ingest(season, dry_run=False):
    season = int(season)
    print("NCAAF CFBD %s FBS log ingest%s" % (season, " (dry run)" if dry_run else ""))

    # 1. Season metadata: one call per season.
    games = _get_json(
        "%s/games?year=%d&seasonType=regular&classification=fbs" % (_API, season)
    )
    game_meta = {}
    for g in games:
        game_meta[str(g.get("id"))] = {
            "date": (g.get("startDate") or "")[:10],
            "completed": bool(g.get("completed")),
            "home": (g.get("homeTeam") or "").strip(),
            "away": (g.get("awayTeam") or "").strip(),
        }
    completed = sum(1 for m in game_meta.values() if m["completed"])
    print("  /games: %d published, %d completed" % (len(game_meta), completed))

    # Positions, before any player is minted. One request for the whole season.
    del _MINTED_WITHOUT_POSITION[:]
    published_positions = _published_positions(season)

    # 2. Team vocabulary: school -> abbreviation (FBS + FCS in one call), and
    # school -> canonical ESPN code (abbreviation when it matches, else the
    # ESPN display-name prefix — CFBD abbreviates Air Force/Buffalo/
    # Jacksonville State differently: AF/BUF/JXST vs AFA/BUFF/JVST).
    teams = _get_json("%s/teams?year=%d" % (_API, season))
    abbrev_by_school = {
        (t.get("school") or "").strip(): (t.get("abbreviation") or "").strip().upper()
        for t in teams if (t.get("school") or "").strip()
    }
    code_by_school = {}
    for school, ab in abbrev_by_school.items():
        code = _school_to_code(school, ab)
        if not code:
            continue
        # An exact abbreviation match is more specific than a display-name
        # prefix; among equal scores the longest school name wins. CFBD's
        # /teams carries generic entries ("San Diego", "Eastern") that
        # prefix-match the same code as the real school ("San Diego State",
        # "Eastern Michigan") — without this, the wrong team gets fetched.
        exact = bool(ab and team_codes.is_canonical(LEAGUE, ab))
        score = 2 if exact else 1
        cur = code_by_school.get(code)
        if cur is None or score > cur[0] or (score == cur[0] and len(school) > len(cur[1])):
            code_by_school[code] = (score, school)
    code_by_school = {code: school for code, (score, school) in code_by_school.items()}
    print("  /teams: %d published, %d resolved to canonical codes"
          % (len(abbrev_by_school), len(code_by_school)))

    def _code_for(school):
        # The dict is code -> school, so a school-name lookup can never hit it.
        # Resolve the school properly: canonical abbreviation first, then the
        # ESPN display-name prefix (Air Force/Buffalo/Jacksonville State are
        # AF/BUF/JXST in CFBD but AFA/BUFF/JVST here), and only then fall back
        # to the raw abbreviation for non-canonical (FCS buy-game) opponents.
        ab = abbrev_by_school.get(school, "")
        return _school_to_code(school, ab) or _team_code(ab)

    # 3. Fetch player stats per canonical FBS team. The fetch list comes from
    # the /games participants — the publisher's own names for the 888 games —
    # not from /teams matching, so a generic /teams entry can never shadow a
    # real school. Each game is covered by at least one FBS side, including
    # buy games whose FCS opponent players ride along in the FBS team's
    # payload.
    game_schools = set()
    for m in game_meta.values():
        if m.get("home"):
            game_schools.add(m["home"])
        if m.get("away"):
            game_schools.add(m["away"])
    fetch_schools = sorted(
        s for s in game_schools if _school_to_code(s, "")
    )
    print("  fetching /games/players for %d FBS teams (%d game participants)"
          % (len(fetch_schools), len(game_schools)))

    raw_games = {}
    failed = 0
    for i, school in enumerate(fetch_schools, 1):
        q = urllib.parse.urlencode({
            "year": season, "seasonType": "regular",
            "classification": "fbs", "team": school,
        })
        try:
            payload = _get_json("%s/games/players?%s" % (_API, q))
        except CfbdError as e:
            failed += 1
            print("  %s: %s" % (school, e))
            continue
        for g in payload:
            raw_games[str(g.get("id"))] = g
        if i % 25 == 0 or i == len(fetch_schools):
            print("  teams %d/%d, %d unique games so far" % (i, len(fetch_schools), len(raw_games)))
    print("  %d unique games fetched (%d team calls failed)" % (len(raw_games), failed))

    con = None
    if not dry_run:
        con = sqlite3.connect(DB)
        con.row_factory = sqlite3.Row
        ensure_table(con)
        # Re-source: the CFBD run is the single source for the season.
        deleted = con.execute(
            "DELETE FROM player_game_logs WHERE league=? AND season=?",
            (LEAGUE, season),
        ).rowcount
        print("  deleted %d previous %s %s log rows" % (deleted, LEAGUE, season))
    spine = _spine_index(con)

    ingested = resolved = unresolved = 0
    games_done = 0
    missing_meta = 0
    for gid, game in sorted(raw_games.items()):
        meta = game_meta.get(gid)
        if meta is None:
            missing_meta += 1
            continue
        if not meta["completed"]:
            continue
        games_done += 1
        sides = []
        for athlete_id, name, school, home_away, stats in _merge_game_athletes(game):
            team = _code_for(school)
            sides.append((athlete_id, name, team, home_away, stats))
        home = _code_for(meta.get("home") or "")
        away = _code_for(meta.get("away") or "")
        for athlete_id, name, team, home_away, stats in sides:
            if team is None or not stats:
                continue
            opponent = _opponent(team, home_away, home, away)
            player_id = None
            if con is not None:
                player_id = _resolve_or_create(con, spine, athlete_id, name, team,
                                               published_positions)
            if player_id is None:
                unresolved += 1
            else:
                resolved += 1
            ingested += 1
            if dry_run:
                continue
            con.execute(
                """INSERT INTO player_game_logs
                   (player_id, league, season, game_no, game_id, game_date, team,
                    opponent, home_away, game_type, stats, source, source_player_key)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(league, source_player_key, season, game_no) DO UPDATE SET
                    player_id=excluded.player_id,
                    game_date=excluded.game_date,
                    team=excluded.team,
                    opponent=excluded.opponent,
                    home_away=excluded.home_away,
                    game_type=excluded.game_type,
                    stats=excluded.stats,
                    source=excluded.source,
                    ingested_at=datetime('now')""",
                (
                    player_id, LEAGUE, season, gid, gid, meta["date"],
                    team, opponent, home_away,
                    GAME_TYPE, json.dumps(stats, separators=(",", ":")),
                    "cfbd", athlete_id,
                ),
            )
        if not dry_run and games_done % 200 == 0:
            con.commit()
    if not dry_run and con is not None:
        con.commit()
        total_logs, linked = con.execute(
            "SELECT COUNT(*), COUNT(player_id) FROM player_game_logs WHERE league=? AND season=?",
            (LEAGUE, season),
        ).fetchone()
        dist_games = con.execute(
            "SELECT COUNT(DISTINCT game_id) FROM player_game_logs WHERE league=? AND season=?",
            (LEAGUE, season),
        ).fetchone()[0]
        con.close()
    else:
        total_logs = linked = dist_games = None

    print("Done. %d NCAAF FBS log rows from %d completed games "
          "(%d resolved, %d unresolved)." % (ingested, games_done, resolved, unresolved))
    print("  %d games fetched without /games metadata (skipped), %d team calls failed."
          % (missing_meta, failed))
    # Printed at zero too. This ingest minted 5,853 positionless NCAAF players over its
    # life -- 27% of the league -- and never said so once, because a blank position does
    # not error, it renders a generic game log that reads as coverage.
    print("  %d players minted with no published position%s"
          % (len(_MINTED_WITHOUT_POSITION),
             "" if not _MINTED_WITHOUT_POSITION
             else " (e.g. %s)" % ", ".join(_MINTED_WITHOUT_POSITION[:5])))
    if total_logs is not None:
        print("  table now: %d rows, %d linked, %d distinct games." % (
            total_logs, linked, dist_games))
    return ingested


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ingest NCAAF FBS regular-season player logs from CFBD")
    parser.add_argument("--season", type=int, required=True,
                        help="season year (ESPN/CFBD key, e.g. 2025)")
    parser.add_argument("--dry-run", action="store_true",
                        help="fetch and resolve but write nothing")
    args = parser.parse_args()
    ingest(args.season, dry_run=args.dry_run)
