#!/usr/bin/env python3
"""ingest_published_rosters.py: fill the roster the resolver reads.

`published_roster.py` explains why the table exists. This fills it, one league at a time,
from EVERY publisher that names that league's players. The resolver never fetches; it only
reads what this leaves behind, because it runs inside a request handler.

    mls                  FotMob squads, plus mlssoccer.com's own club rosters
    ligamx, lcup         FotMob squads

WHY MORE THAN ONE PUBLISHER PER LEAGUE. The first version of this took one publisher per
league, and that shape immediately produced six hand-written aliases in
`published_roster.REVIEWED_ALIASES`: FotMob publishes exactly one spelling per player, so
`playerData?id=652955` returns `Saba Lobjanidze` and reading FotMob harder can never produce
`Lobzhanidze`. mlssoccer.com prints BOTH on one page - it displays "Jake Davis" and files him
at `/players/jacob-davis/`, displays "Vitor Costa" at `/players/vitor-costa-de-brito/`. The
alias table was never a judgment problem; it was the symptom of asking one publisher when a
second publishes the variance for free.

ONE PERSON, TWO PUBLISHERS. Two sources naming the same squad member is not two people, and
`published_roster.lookup` collapses them on club plus a shared spelling before it judges
uniqueness. That collapse is the reason this can add a publisher at all: without it, a second
source would turn every name it also names into an ambiguity and REFUSE it.

WHAT IT WILL NOT DO. Write an empty roster over a full one. An empty result is a request that
told us nothing, not a league with no players, and the resolver would then start refusing
people it had been resolving yesterday. The guard is per publisher, so a failing mlssoccer.com
cannot erase what FotMob published.
"""
import argparse
import collections
import datetime as dt
import html
import json
import os
import re
import sqlite3
import sys
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import published_roster
import paced_http
from ingest_fotmob_soccer_logs import _get as _fotmob_get
from link_prop_games import _norm_team as _team_code

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

# FotMob's squad group -> (position, position_group), in the vocabulary these databases
# already store for soccer. `coach` is deliberately absent: a coach is not a player.
_FOTMOB_GROUPS = {
    "keepers": ("G", "Goalkeeper"),
    "defenders": ("D", "Defender"),
    "midfielders": ("M", "Midfielder"),
    "attackers": ("F", "Forward"),
}

# mlssoccer.com's own vocabulary, mapped to the same four values so the two publishers
# cannot disagree about a position for a reason that is only about wording.
_MLS_POSITIONS = {
    "goalkeeper": ("G", "Goalkeeper"),
    "defense": ("D", "Defender"),
    "midfield": ("M", "Midfielder"),
    "offense": ("F", "Forward"),
}


def _clubs(con, league) -> List[Tuple[str, str]]:
    """(canonical name, publisher id) for a league's clubs, ONE row per club.

    `league_clubs` is keyed (league, name) and holds aliases, so 21 of the 30 MLS clubs are
    stored twice under one id - `Seattle Sounders` and `Seattle Sounders FC` are both 130394.
    Reading it directly fetched 51 squads for 30 clubs and left `published_roster.team`
    holding whichever alias happened to be written last. Both matter now: the team string is
    what tells `lookup` that two publishers mean one person, so it has to be the same string
    every run. The longest alias wins because it is the one a reader recognises.
    """
    by_code: Dict[str, str] = {}
    for name, code in con.execute(
            "SELECT name, code FROM league_clubs WHERE league=? AND code GLOB '[0-9]*'",
            (league,)):
        if len(name) > len(by_code.get(code, "")):
            by_code[code] = name
    return sorted(((name, code) for code, name in by_code.items()), key=lambda row: row[0])


def _fotmob_squads(con, league: str) -> List[Dict]:
    """Every squad member FotMob publishes for a league, via `league_clubs`.

    Uses the club list the FotMob club ingest already stores, so this needs no club list of
    its own and the two cannot disagree about which clubs exist.
    """
    clubs = _clubs(con, league)
    if not clubs:
        print("  {}: no published clubs stored; run ingest_league_clubs.py first".format(league))
        return []
    out: List[Dict] = []
    for club_name, club_id in clubs:
        try:
            document = _fotmob_get(
                "https://www.fotmob.com/api/data/teams?id={}".format(club_id))
        except Exception as exc:  # noqa: BLE001 - one club is not the run
            print("  {} club {}: fetch failed ({})".format(league, club_name, exc))
            continue
        for group in (document.get("squad") or {}).get("squad") or []:
            mapped = _FOTMOB_GROUPS.get((group.get("title") or "").strip().lower())
            if not mapped:
                continue
            for member in group.get("members") or []:
                if not member.get("id") or not member.get("name"):
                    continue
                out.append({
                    "source": "fotmob",
                    "source_player_key": str(member["id"]),
                    "name": member["name"],
                    "names": [member["name"]],
                    "team": club_name,
                    "position": mapped[0],
                    "position_group": mapped[1],
                })
    return out


# mlssoccer.com is a different host from every publisher already budgeted here, and 31
# requests a run is far inside the process-wide count. It gets a full second between
# requests because nobody has measured its wall and a league's own site is not a resource to
# find the edge of.
_MLS_FETCH = paced_http.Fetcher(min_interval=1.0, timeout=40,
                                retry_waits=(5.0, 20.0, 60.0))
_MLS_SITE = "https://www.mlssoccer.com"


def _widgets(page: str):
    """Every `data-options` payload on an mlssoccer.com page, decoded.

    The club rosters are not served by an API - `sportapi.mlssoccer.com` and
    `stats-api.mlssoccer.com` both answer 404 from this box. They are published as
    HTML-escaped JSON inside a react mount attribute, which is still the publisher's own
    structured record and not scraped prose.
    """
    for match in re.finditer(r'data-options="([^"]*)"', page, re.S):
        try:
            payload = json.loads(html.unescape(match.group(1)))
        except ValueError:
            continue
        if isinstance(payload, dict):
            yield payload


def _mls_club_slugs() -> List[str]:
    """The club list MLS itself publishes, rather than one written down here."""
    try:
        page = _MLS_FETCH.text(_MLS_SITE + "/clubs/")
    except Exception as exc:  # noqa: BLE001
        print("  mls: club index fetch failed ({})".format(exc))
        return []
    return sorted(set(re.findall(r'/clubs/([a-z0-9-]+)/', page)))


def _match_club(slug: str, clubs: List[Tuple[str, str]]) -> Optional[str]:
    """An mlssoccer.com slug against the club names already on record, or None.

    None is a REFUSAL, not a default. A squad filed under a club string the FotMob rows do
    not use could never collapse onto them, so it would arrive as 30 extra people rather
    than as a second opinion about 30 existing ones.
    """
    # MLS writes out "football club" where our club record writes "FC", and nowhere else do
    # the two vocabularies differ. Two clubs of thirty turn on it: los-angeles-football-club
    # and new-york-city-football-club.
    folded = published_roster.fold(re.sub(r"football-club$", "fc", slug))
    if not folded:
        return None
    exact = {code for name, code in clubs if published_roster.fold(name) == folded}
    if len(exact) == 1:
        code = exact.pop()
    else:
        near = {code for name, code in clubs
                if len(published_roster.fold(name)) >= 6
                and (published_roster.fold(name).startswith(folded)
                     or folded.startswith(published_roster.fold(name)))}
        if len(near) != 1:
            return None
        code = near.pop()
    return next(name for name, club_code in clubs if club_code == code)


def _mls_squads(con, league: str) -> List[Dict]:
    """Every squad member mlssoccer.com publishes, with every spelling it prints.

    Four spellings per person, because MLS prints four and each one is a spelling a
    sportsbook actually sends: `fullName` ("Jake Davis"), the profile slug ("jacob-davis"),
    `firstName` + `lastName` ("Lasse Berg Johnsen" against the slug's "Lasse Johnsen"), and
    `knownName` where the player has one ("Capita").
    """
    if league != "mls":
        return []
    clubs = _clubs(con, league)
    if not clubs:
        print("  {}: no published clubs stored; run ingest_league_clubs.py first".format(league))
        return []
    slugs = _mls_club_slugs()
    if not slugs:
        return []
    out: List[Dict] = []
    seen = set()
    for slug in slugs:
        club_name = _match_club(slug, clubs)
        if not club_name:
            print("  mls club {}: no club on record uses that name; skipped".format(slug))
            continue
        try:
            page = _MLS_FETCH.text("{}/clubs/{}/roster/".format(_MLS_SITE, slug))
        except Exception as exc:  # noqa: BLE001 - one club is not the run
            print("  mls club {}: fetch failed ({})".format(slug, exc))
            continue
        members = []
        for widget in _widgets(page):
            members = widget.get("playersData") or members
            if members:
                break
        if not members:
            print("  mls club {}: page published no squad".format(slug))
            continue
        for member in members:
            key = str(member.get("optaId") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            mapped = _MLS_POSITIONS.get((member.get("position") or "").strip().lower())
            if not mapped:
                continue
            full = (member.get("fullName") or "").strip()
            # MLS embeds the nickname inside the full name: `Capita "Capita" Capemba`. The
            # raw form stays as a spelling because a book may send it, but the DISPLAY name
            # a player row would be created with should not carry quotation marks.
            display = re.sub(r'\s*"[^"]*"\s*', " ", full).strip()
            first = (member.get("firstName") or "").strip()
            last = (member.get("lastName") or "").strip()
            spellings = [
                display,
                full,
                (member.get("playerSlug") or "").replace("-", " ").strip(),
                (first + " " + last).strip(),
                (member.get("knownName") or "").strip(),
            ]
            spellings = [s for s in spellings if s]
            if not spellings:
                continue
            out.append({
                "source": "mlssoccer",
                "source_player_key": key,
                "name": spellings[0],
                "names": spellings,
                "team": club_name,
                "position": mapped[0],
                "position_group": mapped[1],
            })
    return out


# league -> the publishers that name its players, in the order they are read. Adding a
# league, or a second opinion about one, is a row here and nothing else.
_PROVIDERS = {
    "mls": (_fotmob_squads, _mls_squads),
    "ligamx": (_fotmob_squads,),
    "lcup": (_fotmob_squads,),
}


def _write(con, league: str, members: List[Dict], now: str) -> None:
    con.executemany(
        "INSERT INTO published_roster(league, source, source_player_key, name, "
        "name_folded, team, position, position_group, team_code, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(league, source, source_player_key) DO UPDATE SET "
        "name=excluded.name, name_folded=excluded.name_folded, team=excluded.team, "
        "position=excluded.position, position_group=excluded.position_group, "
        "team_code=excluded.team_code, updated_at=excluded.updated_at",
        [(league, m["source"], m["source_player_key"], m["name"],
          published_roster.fold(m["name"]), m["team"], m["position"],
          m["position_group"], _team_code(m["team"], league), now) for m in members])
    con.executemany(
        "INSERT INTO published_roster_name(league, source, source_player_key, name, "
        "name_folded) VALUES(?,?,?,?,?) "
        "ON CONFLICT(league, source, source_player_key, name_folded) DO UPDATE SET "
        "name=excluded.name",
        [(league, m["source"], m["source_player_key"], spelling,
          published_roster.fold(spelling))
         for m in members for spelling in m.get("names") or [m["name"]]
         if published_roster.fold(spelling)])


def ingest(leagues, dry_run=True):
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    published_roster.ensure(con)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    total = 0
    identity = collections.Counter()
    for league in leagues:
        providers = _PROVIDERS.get(league)
        if not providers:
            print("  {}: no publisher declared for this league; skipped".format(league))
            continue
        provider_members = {}
        for provider in providers:
            members = provider(con, league)
            provider_members[provider] = members
            if not members:
                # Never overwrite a full roster with an empty fetch, per publisher: one
                # publisher going dark must not erase what another published.
                print("  {} via {}: published NOTHING; leaving the stored roster alone".format(
                    league, provider.__name__))
                continue
            print("  {} via {}: {} published squad members".format(
                league, provider.__name__, len(members)))
            if dry_run:
                continue
            _write(con, league, members, now)
            total += len(members)
        if not dry_run:
            touched = [(member["source"], member["source_player_key"])
                       for provider in providers for member in provider_members.get(provider, [])]
            league_identity = published_roster.publish_identities(
                con, league, now, touched)
            print("  {} identities: {}".format(league, " ".join(
                "{}={}".format(key, league_identity[key])
                for key in sorted(league_identity) if key != "failure_examples")))
            for failure in league_identity["failure_examples"]:
                print("    REFUSE {reason}: names={names} teams={teams} sources={source_keys}".format(
                    **failure))
            for key, value in league_identity.items():
                if key != "failure_examples":
                    identity[key] += value
    if not dry_run:
        con.commit()
    held = con.execute(
        "SELECT league, source, COUNT(*) FROM published_roster GROUP BY league, source "
        "ORDER BY 1, 2").fetchall()
    con.close()
    print("  wrote {}{}".format(total, " (dry run: nothing written)" if dry_run else ""))
    for league, source, count in held:
        print("    published_roster holds {} members for {} from {}".format(
            count, league, source))
    if not dry_run:
        print("  identities: {}".format(" ".join(
            "{}={}".format(key, identity[key]) for key in sorted(identity))))
    return {"rows": total, "identity": dict(identity)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("leagues", nargs="*", help="default: every league with a publisher")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    result = ingest(args.leagues or sorted(_PROVIDERS), dry_run=not args.apply)
    blockers = result["identity"].get("ambiguous", 0) + result["identity"].get(
        "conflicts", 0) + result["identity"].get("team_conflicts", 0)
    return 2 if blockers else 0


if __name__ == "__main__":
    sys.exit(main())
