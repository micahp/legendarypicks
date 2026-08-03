#!/usr/bin/env python3
"""backfill_nfl_postseason.py — the postseason `ingest_team_results.py` cannot reach.

`team_game_results` held NFL 2025 as 272 games ending 2026-01-05 — the last
regular-season Sunday — while 2024 held 285. The gap was not a filter we were
applying. `ingest_team_results.py` reads `/teams/{abbrev}/schedule` with no
season argument, so it gets whatever season the publisher considers current;
asked on 2026-08-03 it answers with 2026's *scheduled* games and nothing else.
Adding `?season=2025&seasontype=3` does not help — that endpoint returns zero
events for a past postseason. It is the wrong surface, not a missing parameter.

The right surface is the core API, which enumerates a season's phases directly:

    seasons/2025/types/3/events?limit=1   ->  {"count": 14}

**14, not 13.** ESPN files the **Pro Bowl inside the postseason**, exactly as it
files the All-Star Game inside MLB's regular season. It publishes no
`competitions[0].type`, so the `_COMPETITION_PHASE` hook in `game_types.py`
cannot catch it, and its two "teams" are AFC and NFC — abbreviations that are
not in the published 32-team list. That list is the discriminator used here: a
competitor who is not a team does not get a team-game row. Filtering on the
event's *name* would work today and break the first year ESPN renames it.

`team_game_results` has no `game_type` column (deliberately — see
docs/DATA-COVERAGE-CONTRACT.md), so this cannot file the Pro Bowl as ALLSTAR the
way NBA's play-in is filed. Excluding it is the only honest option available:
including it would put two nonexistent teams and one exhibition into a table
whose rows all read as real games.

Everything else follows `ingest_team_results.py`: phase and season come off the
envelope rather than off our own request, both competitors are written from the
one document that names both, and the run reconciles against the publisher's own
count before reporting success.

    ./venv/bin/python backfill_nfl_postseason.py --season 2025
    ./venv/bin/python backfill_nfl_postseason.py --season 2025 --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from game_types import normalize_game_type, POST  # noqa: E402
from season_keys import normalize_season  # noqa: E402

DB = os.environ.get("LP_DB_PATH", "picks.db")
SOURCE = "espn_core_api:season_type_events"
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"
SITE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
_HDR = {"User-Agent": "Mozilla/5.0 (legendarypicks ingest)"}


def _get(url: str, attempts: int = 4) -> dict:
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers=_HDR)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"{url} failed after {attempts} attempts: {last}")


def real_team_abbrevs() -> set:
    """The 32 abbreviations ESPN publishes as NFL teams.

    The Pro Bowl's AFC/NFC are not among them, which is the whole point: this is
    a published fact about who is a team, not a guess about which games are
    exhibitions.
    """
    doc = _get(f"{SITE}/teams")
    return {t["team"]["abbreviation"]
            for t in doc["sports"][0]["leagues"][0]["teams"]}


def published_event_ids(season: int, season_type: int = 3) -> tuple:
    """(expected_count, [event_id, ...]) straight from the core API envelope."""
    url = f"{CORE}/seasons/{season}/types/{season_type}/events"
    head = _get(f"{url}?limit=1")
    expected = int(head.get("count") or 0)
    ids = []
    page, pages = 1, 1
    while page <= pages:
        doc = _get(f"{url}?limit=100&page={page}")
        pages = int(doc.get("pageCount") or 1)
        for item in doc.get("items", []):
            ids.append(item["$ref"].rstrip("/").split("/")[-1].split("?")[0])
        page += 1
    return expected, ids


def backfill(season: int, dry_run: bool = False) -> int:
    teams = real_team_abbrevs()
    if len(teams) != 32:
        raise RuntimeError(f"expected 32 published NFL teams, got {len(teams)}")

    expected, ids = published_event_ids(season)
    print(f"nfl {season} postseason: publisher says {expected} events, enumerated {len(ids)}")
    if expected != len(ids):
        raise RuntimeError("enumerated a different number of events than published")

    con = sqlite3.connect(DB)
    run_id = f"nfl-postseason-{season}-{int(time.time())}"
    wrote, games, excluded, incomplete = 0, 0, [], 0

    for eid in ids:
        head = (_get(f"{SITE}/summary?event={eid}").get("header") or {})
        comp = (head.get("competitions") or [{}])[0]
        if not ((comp.get("status") or {}).get("type") or {}).get("completed"):
            incomplete += 1
            continue

        comps = comp.get("competitors") or []
        abbrevs = [(c.get("team") or {}).get("abbreviation") for c in comps]
        if len(comps) != 2 or not all(a in teams for a in abbrevs):
            # The Pro Bowl lands here. Named, counted and reported — an excluded
            # row we cannot account for is indistinguishable from one we lost.
            excluded.append((eid, "/".join(str(a) for a in abbrevs)))
            continue

        phase = normalize_game_type("espn", "nfl", (head.get("season") or {}).get("type"))
        yr = normalize_season(SOURCE, "nfl", (head.get("season") or {}).get("year"))
        if phase != POST:
            excluded.append((eid, f"phase={phase}"))
            continue
        if yr != season:
            excluded.append((eid, f"season={yr}"))
            continue

        rows = []
        for mine in comps:
            theirs = next(c for c in comps if c is not mine)
            sf, sa = mine.get("score"), theirs.get("score")
            if sf is None or sa is None:
                rows = []
                break
            win = mine.get("winner")
            rows.append((
                "nfl", str(eid), (mine["team"]["abbreviation"]),
                (comp.get("date") or "")[:10], theirs["team"]["abbreviation"],
                mine.get("homeAway"), float(sf), float(sa),
                1 if win is True else 0 if win is False else None,
                yr, "completed", SOURCE, run_id,
            ))
        if not rows:
            excluded.append((eid, "a competitor had no score"))
            continue

        if not dry_run:
            con.executemany("""INSERT OR REPLACE INTO team_game_results
                (league, game_id, team, game_date, opponent, home_away, score_for,
                 score_against, win, season, status, source, run_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
        wrote += len(rows)
        games += 1

    if not dry_run:
        con.commit()

    print(f"  wrote {wrote} rows over {games} games (dry_run={dry_run})")
    print(f"  run_id={run_id} source={SOURCE}")
    if incomplete:
        print(f"  {incomplete} events not completed — not written")
    for eid, why in excluded:
        print(f"  excluded {eid}: {why}")

    # Reconcile against the table, not against this run's own counters. A count
    # of rows written is a claim about the run; that every game holds both of its
    # teams and that the season now matches the publisher are claims about the
    # data, and those are the ones that have been false before.
    total_games = con.execute(
        "SELECT COUNT(DISTINCT game_id) FROM team_game_results WHERE league='nfl' AND season=?",
        (season,)).fetchone()[0]
    orphans = con.execute(
        "SELECT COUNT(*) FROM (SELECT game_id FROM team_game_results"
        " WHERE league='nfl' AND season=? GROUP BY game_id HAVING COUNT(*)<>2)",
        (season,)).fetchone()[0]
    unattributed = con.execute(
        "SELECT COUNT(*) FROM team_game_results WHERE league='nfl' AND season=?"
        " AND (season IS NULL OR source IS NULL OR source='')", (season,)).fetchone()[0]
    con.close()

    reg, _ = published_event_ids(season, season_type=2)
    want = reg + games
    print(f"  nfl {season} now {total_games} games; publisher: {reg} regular + "
          f"{games} postseason written = {want}")
    print(f"  one-sided games: {orphans}   rows missing season or source: {unattributed}")
    if orphans or unattributed or (total_games != want and not dry_run):
        print("  ^ NOT clean — do not report this run as complete")
        return 1
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2025)
    ap.add_argument("--dry-run", action="store_true")
    raise SystemExit(backfill(ap.parse_args().season, ap.parse_args().dry_run))
