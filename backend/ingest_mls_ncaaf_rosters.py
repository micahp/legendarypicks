#!/usr/bin/env python3
"""ingest_mls_ncaaf_rosters.py — identity spine for the two new leagues.

Why this exists: the MLS game-log ingest landed 15,361 rows with 0 resolved
player_id because `players` had no league='mls' rows (the doctrine: publish
canonical identity + roster membership FIRST, then key logs onto the id).
This walks every team's ESPN roster for mls + ncaaf, upserts `players` rows
(league, espn_id, name, team, position, position_group, active=1), and lets
the log ingests re-run with a working resolver.

Measured shapes (2026-08-06):
- MLS rosters: site.web .../soccer/usa.1/teams/{id}/roster?season=2025 — the
  season param works (2025 roster = 31 for ATL vs 28 current). 30 teams.
- NCAAF rosters: site.web .../football/college-football/teams/{id}/roster
  serves ONLY the current season (2025 returns Postseason type with 0
  athletes — measured). The FBS population is the group-80 whitelist
  (sports.core .../seasons/{season}/types/{type}/groups/80/teams, 146 ids);
  the site teams list maps id -> abbreviation in one request.
- Roster athletes nest under position-group headers for football (offense /
  defense / specialTeam ...) and flat for soccer; both flatten the same way.
- The default roster page is capped at 100 athletes; Alabama returned 110
  with limit=200 — pass limit=200 or rosters silently truncate.
- team codes come from team_codes.normalize(league, abbrev) with an
  uppercase fallback, the SAME normalization the log resolver uses, so the
  join on (name_norm, team_norm) works.
- position_group is derived from the position-vocabulary ancestry root
  (mls: Goalkeeper/Defender/Midfielder/Forward; ncaaf: Offense/Defense/
  Special Teams), matching the existing convention (Pitcher, Defense, ...).

Request count (state BEFORE running, per espn-request-budget):
- mls:  1 (site teams) + 30 (rosters)                     = 31 site.web
- ncaaf: 1 (site teams) + 2 (group-80 whitelist, 2 pages) + 146 (rosters)
       = 149 site.web + 2 sports.core
The shared fetcher self-throttles past ~100/host; the disk cache makes a
re-run free. One ingest at a time.

Usage: LP_DB_PATH=<copy.db> ./venv/bin/python ingest_mls_ncaaf_rosters.py [mls ncaaf]
"""
import collections
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import espn_client as espn
from team_codes import normalize, UnknownTeamCode

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)

_SITE = "https://site.web.api.espn.com/apis/site/v2/sports/{path}"
_CORE = "https://sports.core.api.espn.com/v2/sports/{path}"
# site path (espn_client LEAGUES) -> core path (espn_leagues registry)
_SITE_PATH = {
    "mls": "soccer/usa.1",
    "ncaaf": "football/college-football",
}
_CORE_PATH = {
    "mls": "soccer/leagues/usa.1",
    "ncaaf": "football/leagues/college-football",
}
_SCOPE_GROUP = {"mls": None, "ncaaf": "80"}
_REG_TYPE_ID = {"mls": "1", "ncaaf": "2"}
_SEASON_CACHE = {}


def _get(url: str, ttl: int = 43200) -> dict:
    return espn._get(url, ttl=ttl)


def _season(league: str) -> int:
    """The season ESPN currently publishes for this league.

    This was `_SEASON = {"mls": 2025, "ncaaf": 2025}`. A season is a definition,
    and a definition is always published (published-first rung 5) -- hardcoding
    one means the roster sync silently serves last year's squads the moment the
    calendar turns. Measured 2026-08-16: ESPN published 2026 for both leagues
    while this constant still said 2025, so every MLS roster fetch returned the
    2025 squad (Atlanta: Brad Guzan present, Lucas Hoyos absent) and 146 players
    carrying live 2026 Bovada props matched nothing in the spine.

    `/seasons?limit=1` returns newest-first, so the year in the first $ref is
    the current season. There is deliberately no fallback: a stale constant is
    exactly the failure this replaces, and guessing a year would reintroduce it
    quietly. LP_ROSTER_SEASON overrides for backfills of a specific season.
    """
    override = os.environ.get("LP_ROSTER_SEASON")
    if override:
        return int(override)
    if league in _SEASON_CACHE:
        return _SEASON_CACHE[league]
    path = _CORE_PATH[league]
    d = _get(f"{_CORE.format(path=path)}/seasons?limit=1", ttl=43200)
    items = d.get("items") or []
    ref = items[0].get("$ref") if items and isinstance(items[0], dict) else None
    m = re.search(r"/seasons/(\d{4})", ref or "")
    if not m:
        raise RuntimeError(
            "ESPN published no current season for {} (asked {}/seasons?limit=1)"
            .format(league, path))
    _SEASON_CACHE[league] = int(m.group(1))
    return _SEASON_CACHE[league]


def _vocabulary():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "data", "position-vocabulary.json")
    with open(path) as fh:
        d = json.load(fh)
    out = {}
    for lg in ("mls", "ncaaf"):
        v = d.get("leagues", {}).get(lg, {})
        out[lg] = (v.get("positions", {}), v.get("ancestry", {}))
    return out


def _position_group(league, position, vocab):
    """Human-readable group from the vocabulary ancestry root.

    Walks ancestry[position] to its terminal parent (the root) and maps the
    root's abbreviation to its published name (Goalkeeper, Defender, Offense,
    Special Teams...). Unknown/rootless positions get None.
    """
    if not position:
        return None
    positions, ancestry = vocab.get(league, ({}, {}))
    chain = ancestry.get(position) or []
    root = chain[-1] if chain else position
    if not root:
        return None
    info = positions.get(root) or {}
    return info.get("name")


def _site_teams(league):
    """{abbrev: id} from the site teams list.

    The college-football list is paginated at 50 without paging metadata and
    truncates there — measured 2026-08-06. Pass limit=200; offset is ignored
    by this endpoint (every page is identical), so one call is all we get.
    Combined with the standings map below it covers most of FBS.
    """
    path = _SITE_PATH[league]
    out = {}
    url = _SITE.format(path=path) + "/teams?limit=200"
    d = _get(url)
    for sport in d.get("sports", []) or []:
        for lg in sport.get("leagues", []) or []:
            for item in lg.get("teams", []) or []:
                team = item.get("team") or {}
                ab = (team.get("abbreviation") or "").upper()
                tid = str(team.get("id") or "")
                if ab and tid:
                    out[ab] = tid
    return out


def _standings_teams(league):
    """{abbrev: id} from the site standings (site.web /apis/v2 path).

    Covers FBS teams the truncated site teams list misses; 122 of 146 FBS
    ids measured 2026-08-06. Empty for leagues without a standings page.
    """
    path = _SITE_PATH[league]
    out = {}
    try:
        d = _get("https://site.web.api.espn.com/apis/v2/sports/"
                 f"{path}/standings")
    except Exception:  # noqa: BLE001 — standings are best-effort
        return out
    for child in d.get("children", []) or []:
        for ent in (child.get("standings", {}) or {}).get("entries", []) or []:
            t = ent.get("team", {})
            ab = (t.get("abbreviation") or "").upper()
            tid = str(t.get("id") or "")
            if ab and tid:
                out[ab] = tid
    return out


def _core_team_abbrev(league, team_id):
    """Abbreviation from the core team doc (one request per team)."""
    path = _CORE_PATH[league]
    try:
        d = _get(f"{_CORE.format(path=path)}/seasons/{_season(league)}"
                 f"/teams/{team_id}")
        return str(d.get("abbreviation") or "").upper() or None
    except Exception:  # noqa: BLE001
        return None


def _team_id_map(league):
    """{abbrev: id} for every published team of the league's scope.

    For group-scoped leagues (ncaaf) ONLY the scope-group whitelist counts —
    the site teams list and standings carry non-FBS schools. Union the site
    list + standings for abbreviations, then add the whitelist's own team
    docs for any id still missing one (measured: ~18 for ncaaf 2025).
    """
    by_abbrev = {}
    for src in (_site_teams(league), _standings_teams(league)):
        for ab, tid in src.items():
            by_abbrev.setdefault(ab, tid)
    by_id = {tid: ab for ab, tid in by_abbrev.items()}
    scope = _SCOPE_GROUP[league]
    if not scope:
        return by_abbrev
    ids = _group_whitelist(league) or set()
    # whitelist-only: drop any non-FBS team the site/standings leaks in
    by_abbrev = {ab: tid for ab, tid in by_abbrev.items() if tid in ids}
    by_id = {tid: ab for ab, tid in by_abbrev.items()}
    missing = sorted(str(i) for i in ids if str(i) not in by_id)
    for tid in missing:
        ab = _core_team_abbrev(league, tid)
        if ab:
            by_abbrev[ab] = tid
            by_id[tid] = ab
    return by_abbrev


def _group_whitelist(league):
    """Set of published team ids for the league's scope group (ncaaf FBS).

    limit=200 returns the whole group in one call (146 of 146 measured
    2026-08-06); offset/page params on this endpoint are ignored.
    """
    scope = _SCOPE_GROUP[league]
    if not scope:
        return None
    season = _season(league)
    type_id = _REG_TYPE_ID[league]
    base = _CORE.format(path=_CORE_PATH[league])
    d = _get(f"{base}/seasons/{season}/types/{type_id}"
             f"/groups/{scope}/teams?limit=200")
    return _ref_ids(d)


def _ref_ids(d):
    """Extract trailing team ids from $ref items (…/seasons/2025/teams/2)."""
    out = set()
    for item in d.get("items", []) or []:
        ref = item.get("$ref") if isinstance(item, dict) else None
        m = re.search(r"/teams/(\d+)", ref or "")
        if m:
            out.add(m.group(1))
    return out


def _fetch_roster(league, team_id, limit=200):
    """Raw flattened roster: [{player_id, name, jersey, position}]."""
    path = _SITE_PATH[league]
    url = _SITE.format(path=path) + f"/teams/{team_id}/roster?limit={limit}"
    if league == "mls":
        url += f"&season={_season(league)}"
    d = _get(url)
    out = []
    for a in d.get("athletes", []) or []:
        items = a.get("items") if isinstance(a, dict) and "items" in a else [a]
        for p in items or []:
            if not isinstance(p, dict):
                continue
            out.append({
                "player_id": str(p["id"]) if p.get("id") is not None else None,
                "name": p.get("fullName") or p.get("displayName"),
                "jersey": p.get("jersey"),
                "position": (p.get("position") or {}).get("abbreviation"),
            })
    return out


def _team_code(league, abbrev):
    if not abbrev:
        return ""
    try:
        return normalize(league, abbrev)
    except Exception:  # noqa: BLE001 — same boundary as the log ingest
        return str(abbrev).upper()


def sync_league(con, league, vocab):
    print(f"== {league}: teams + rosters ==")
    team_map = _team_id_map(league)
    if not team_map:
        print(f"  FAIL: no teams resolved for {league}")
        return
    teams = list(team_map.items())
    print(f"  teams {len(teams)} (site + standings + core fallback)")

    rows = 0
    inserted = 0
    updated = 0
    failures = []
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for ab, tid in sorted(teams):
        try:
            roster = _fetch_roster(league, tid)
        except Exception as exc:  # noqa: BLE001 — one team must not stop all
            failures.append({"team": ab, "reason": str(exc)})
            continue
        if not roster:
            failures.append({"team": ab, "reason": "empty roster"})
            continue
        team = _team_code(league, ab)
        for p in roster:
            eid = p.get("player_id")
            name = p.get("name")
            if not eid or not name:
                continue
            pg = _position_group(league, p.get("position"), vocab)
            # idempotent on UNIQUE(espn_id, league)
            cur = con.execute(
                "SELECT id FROM players WHERE espn_id=? AND league=?",
                (eid, league),
            ).fetchone()
            if cur is None:
                con.execute(
                    """INSERT INTO players(
                         name, team, league, espn_id, position,
                         position_group, active, updated_at)
                       VALUES(?,?,?,?,?,?,1,?)""",
                    (name, team, league, eid, p.get("position"), pg, now),
                )
                inserted += 1
            else:
                con.execute(
                    """UPDATE players
                       SET name=?, team=?, position=COALESCE(?, position),
                           position_group=COALESCE(?, position_group),
                           active=1, updated_at=?
                       WHERE id=?""",
                    (name, team, p.get("position"), pg, now, cur["id"]),
                )
                updated += 1
            rows += 1
        con.commit()  # periodic commit: a killed run resumes cleanly
    print(f"  {league}: {rows} roster rows ({inserted} inserted, "
          f"{updated} updated)")
    if failures:
        print(f"  failures ({len(failures)}):")
        for f in failures[:10]:
            print(f"    {f['team']}: {f['reason']}")


def main(leagues):
    espn.set_retry_waits((5.0, 30.0, 120.0))
    espn.set_min_interval(float(os.environ.get("LP_ESPN_MIN_INTERVAL", "0.5")))
    espn.set_disk_cache(
        os.environ.get("LP_ESPN_CACHE_DIR")
        or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "data", "espn-cache"),
        ttl=float(os.environ.get("LP_ESPN_CACHE_TTL", "43200")),
    )
    vocab = _vocabulary()
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    for lg in leagues:
        sync_league(con, lg, vocab)
    con.close()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a in ("mls", "ncaaf")]
    main(args or ["mls", "ncaaf"])
