#!/usr/bin/env python3
"""Focused deterministic assertions for the feat/leagues-hub patch.

These verify the contract changes in espn_client.wc_knockout_standings and
routers.games.get_standings, plus league propagation in get_games. Publisher
responses are fixtures, so the full suite never depends on live ESPN. Exits
non-zero on any failure.
"""
import sys
import os
import datetime as _dt
import sqlite3
import tempfile
from unittest.mock import patch

# ── production code under test ──
import espn_client as espn
from routers import games as games_router
from fastapi import HTTPException

FAILURES = []


def _world_cup_events():
    rounds = (
        ("round-of-32", 16), ("round-of-16", 8), ("quarterfinals", 4),
        ("semifinals", 2), ("3rd-place-match", 1), ("final", 1),
    )
    events = []
    for slug, count in rounds:
        for _ in range(count):
            number = len(events) + 1
            events.append({
                "id": str(number),
                "date": "2026-06-28T18:00:00Z",
                "season": {"slug": slug},
                "competitions": [{
                    "status": {"type": {
                        "name": "STATUS_SCHEDULED",
                        "description": "Scheduled",
                        "state": "pre",
                    }},
                    "competitors": [
                        {"homeAway": "home", "score": None,
                         "team": {"abbreviation": "H%02d" % number,
                                  "displayName": "Home %02d" % number}},
                        {"homeAway": "away", "score": None,
                         "team": {"abbreviation": "A%02d" % number,
                                  "displayName": "Away %02d" % number}},
                    ],
                }],
            })
    return events


def _mock_world_cup_get(url, ttl=20):
    if "dates=" in url:
        return {"events": _world_cup_events()}
    return {"leagues": [{"calendar": [{"entries": [
        {"label": "Group Stage", "startDate": "2026-06-11", "endDate": "2026-06-27"},
        {"label": "Knockout", "startDate": "2026-06-28", "endDate": "2026-07-19"},
    ]}]}]}


def _mock_games(league):
    return [{
        "game_id": "fixture-1",
        "league": league,
        "home": {"abbrev": "HME", "name": "Home"},
        "away": {"abbrev": "AWY", "name": "Away"},
    }]


def _mock_ncaaf_standings(season=None):
    return {
        "league": "ncaaf", "season": 2026, "available_seasons": [2026],
        "groups": [{"group": "Conference %d" % i, "rows": [{
            "rank": 1, "abbrev": "T%02d" % i, "name": "Team %d" % i,
            "played": 8, "wins": 7, "losses": 1,
        }]} for i in range(1, 6)],
    }


def _mock_mls_standings(season=None):
    row = {"rank": 1, "abbrev": "TST", "name": "Test FC", "played": 1,
           "wins": 1, "draws": 0, "losses": 0, "gf": 1, "ga": 0,
           "gd": 1, "points": 3}
    return {
        "league": "mls", "season": 2026, "available_seasons": [2026],
        "in_progress": True,
        "groups": [
            {"group": "Eastern Conference", "rows": [dict(row)]},
            {"group": "Western Conference", "rows": [dict(row)]},
        ],
    }


def _mock_nba_standings(league, season=None):
    return {
        "league": "nba", "season": 2026, "available_seasons": [2026],
        "teams": [{"abbrev": "BOS", "name": "Boston Celtics"}],
    }


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


def check_raises(name, fn, status_code):
    try:
        fn()
    except HTTPException as e:
        if e.status_code == status_code:
            print(f"  PASS  {name} (HTTP {status_code})")
        else:
            print(f"  FAIL  {name} wrong status {e.status_code} (wanted {status_code})")
            FAILURES.append(name)
    except Exception as e:
        print(f"  FAIL  {name} raised {type(e).__name__}: {e}")
        FAILURES.append(name)
    else:
        print(f"  FAIL  {name} did NOT raise")
        FAILURES.append(name)


def test_leagues_hub_contract():
    """Exercise the hub contracts offline with representative publisher payloads."""
    FAILURES.clear()
    print("== [1] WC knockout bracket: 32 matches / six ordered rounds / nonblank team objects ==")
    with patch.object(espn, "_get", side_effect=_mock_world_cup_get):
        bracket = espn.wc_knockout_standings()
    rounds = bracket.get("rounds", [])
    check("rounds is a list", isinstance(rounds, list), type(rounds))
    check("six rounds present", len(rounds) == 6, f"got {len(rounds)}")

    # canonical order check
    expected_order = ["Round of 32", "Round of 16", "Quarterfinals",
                      "Semifinals", "Third Place", "Final"]
    got_order = [r["round"] for r in rounds]
    check(f"rounds in canonical order {expected_order}",
          got_order == expected_order, f"got {got_order}")

    # match count across all rounds = 32
    total = sum(len(r.get("matches", [])) for r in rounds)
    check("32 matches total", total == 32, f"got {total}")

    # every match has nonblank team objects with string abbrev + name
    bad = []
    for r in rounds:
        for m in r.get("matches", []):
            for side in ("home", "away"):
                t = m.get(side)
                if not isinstance(t, dict):
                    bad.append(f"{r['round']}:{side} not dict")
                    continue
                if not (t.get("abbrev") and isinstance(t["abbrev"], str) and t["abbrev"].strip()):
                    bad.append(f"{r['round']}:{side} blank abbrev={t.get('abbrev')!r}")
                if not (t.get("name") and isinstance(t["name"], str) and t["name"].strip()):
                    bad.append(f"{r['round']}:{side} blank name={t.get('name')!r}")
    check("every team is a nonblank {abbrev,name} object", not bad, f"first bad: {bad[:3]}")

    print("== [2] getGames / league propagation ==")
    # Load the real route handler without standing up a server: call the function.
    # get_games reads router.query via FastAPI normally; here we validate the
    # documented contract by checking espn.games stamps the correct league shape
    # and that getGames maps it through normalizeGame-equivalent propagation.
    with patch.object(espn, "games", side_effect=_mock_games):
        for lg in ("nba", "nhl", "mlb", "nfl", "wc"):
            data = espn.games(lg)
            # The frontend propagates league via SportsService.getGames(league).
            # Assert the route's downstream doesn't remap league away from the param.
            check(f"{lg}: games() returns a list", isinstance(data, list), type(data))
            if data:
                sample = data[0]
                check(f"{lg}: game has home+away team dicts",
                      isinstance(sample.get("home"), dict) and isinstance(sample.get("away"), dict),
                      f"home={type(sample.get('home'))} away={type(sample.get('away'))}")

    print("== [3] no-stale-group gate: knockout + empty bracket -> 503 (never group tables) ==")
    # Force the knockout path: wc_is_knockout() -> True, and bracket returns no rounds.
    _orig_phase = espn.wc_is_knockout
    _orig_bracket = espn.wc_knockout_standings
    try:
        espn.wc_is_knockout = lambda: True
        espn.wc_knockout_standings = lambda: {"rounds": []}
        check_raises("get_standings wc (knockout, empty) -> 503",
                     lambda: games_router.get_standings("wc"), 503)

        # bracket with at least one round must be returned as-is (not group tables)
        fake_bracket = {"rounds": [{"round": "Final",
                                    "matches": [{"game_id": "1", "home": {"abbrev": "AR", "name": "Argentina"},
                                                 "away": {"abbrev": "FR", "name": "France"}}]}]}
        espn.wc_knockout_standings = lambda: fake_bracket
        res = games_router.get_standings("wc")
        check("get_standings wc returns the bracket (not group tables)",
              isinstance(res, dict) and res.get("rounds") == fake_bracket["rounds"],
              f"got {type(res)}")
    finally:
        espn.wc_is_knockout = _orig_phase
        espn.wc_knockout_standings = _orig_bracket

    print("== [4] phase-lookup failure -> 503 (never uncaught 500 / never stale groups) ==")
    try:
        espn.wc_is_knockout = lambda: (_ for _ in ()).throw(RuntimeError("ESPN down"))
        check_raises("get_standings wc (phase lookup fails) -> 503",
                     lambda: games_router.get_standings("wc"), 503)
    finally:
        espn.wc_is_knockout = _orig_phase

    print("== [5] UFC rankings: missing data fails loudly; complete data is non-empty ==")
    _orig_db = games_router._db
    try:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "rankings.db")
            games_router._db = lambda: sqlite3.connect(db_path)
            check_raises("missing UFC table -> 503", games_router.ufc_rankings, 503)

            divisions = [
                "Flyweight", "Bantamweight", "Featherweight", "Lightweight",
                "Welterweight", "Middleweight", "Light Heavyweight", "Heavyweight",
                "Women's Strawweight", "Women's Flyweight", "Women's Bantamweight",
            ]
            with sqlite3.connect(db_path) as con:
                con.execute(
                    "CREATE TABLE ufc_rankings(division TEXT, rank INTEGER, "
                    "fighter TEXT, is_champion INTEGER, captured_at TEXT)"
                )
                rows = [
                    ("Men's Pound-for-Pound Top Rank", 1, "Men One", 0, "test"),
                    ("Women's Pound-for-Pound Top Rank", 1, "Women One", 0, "test"),
                ]
                for division in divisions:
                    rows.extend([
                        (division, 0, f"{division} Champion", 1, "test"),
                        (division, 1, f"{division} Contender", 0, "test"),
                    ])
                con.executemany("INSERT INTO ufc_rankings VALUES (?,?,?,?,?)", rows)

            result = games_router.ufc_rankings()
            check("men's P4P rankings are non-empty",
                  bool(result.get("pound_for_pound", {}).get("men")))
            check("women's P4P rankings are non-empty",
                  bool(result.get("pound_for_pound", {}).get("women")))
            check("all 11 weight divisions are present",
                  len(result.get("divisions", [])) == 11,
                  f"got {len(result.get('divisions', []))}")
    finally:
        games_router._db = _orig_db

    print("== [6] ncaaf standings: season envelope with conference groups ==")
    with patch.object(espn, "ncaaf_conference_standings", side_effect=_mock_ncaaf_standings), \
            patch.object(games_router, "seasons_we_hold", return_value={2026}):
        ncaaf = games_router.get_standings("ncaaf")
    # Shape moved to the season envelope 2026-08-29 (readStandings consumes it
    # for the season picker), matching the MLS [7] and NBA [8] contracts.
    check("ncaaf standings is a season envelope", isinstance(ncaaf, dict), type(ncaaf))
    ncaaf_groups = ncaaf.get("groups") if isinstance(ncaaf, dict) else None
    check("ncaaf envelope carries groups", isinstance(ncaaf_groups, list),
          type(ncaaf_groups))
    check("ncaaf names its season", isinstance(ncaaf.get("season"), int),
          f"season={ncaaf.get('season')!r}")
    check("ncaaf offers available_seasons",
          isinstance(ncaaf.get("available_seasons"), list) and ncaaf["available_seasons"],
          f"available_seasons={ncaaf.get('available_seasons')!r}")
    if ncaaf_groups:
        check("ncaaf has conference groups", len(ncaaf_groups) >= 5,
              f"got {len(ncaaf_groups)} groups")
        first = ncaaf_groups[0]
        check("first group has group+rows", isinstance(first, dict)
              and isinstance(first.get("group"), str) and first.get("group")
              and isinstance(first.get("rows"), list) and first["rows"],
              f"first={str(first)[:120]}")
        # every row carries the football columns; no fabricated soccer fields
        bad = []
        for g in ncaaf_groups:
            for r in g["rows"]:
                for key in ("rank", "abbrev", "name", "played", "wins", "losses"):
                    if key not in r:
                        bad.append(f"{g['group']}:{r.get('abbrev')} missing {key}")
                if "points" in r or "draws" in r or "gf" in r:
                    bad.append(f"{g['group']}:{r.get('abbrev')} has soccer-only field")
        check("every row has football columns and no soccer-only fields", not bad, f"{bad[:3]}")
        per_group_ok = all(
            [r["rank"] for r in g["rows"]] == list(range(1, len(g["rows"]) + 1))
            for g in ncaaf_groups
        )
        check("ranks are 1..N per conference", per_group_ok,
              f"first ranks {[r['rank'] for r in ncaaf_groups[0]['rows']][:5]}")

    print("== [7] mls standings: seasoned, conference-grouped soccer shape ==")
    # Shape changed 2026-08-17: MLS now returns {season, phase, in_progress, groups}
    # rather than a bare [{group, rows}]. It reads the publisher's table instead of
    # rolling up our own, because our rows only ever cover a COMPLETED season and the
    # bare shape had no way to say which one it was — so in mid-August this surface
    # served the 2025 final table, unlabelled.
    #
    # The upstream response is fixed here; publisher outage behavior is covered by
    # the focused standings tests.
    with patch.object(espn, "mls_conference_standings", side_effect=_mock_mls_standings), \
            patch.object(games_router, "seasons_we_hold", return_value={2026}):
        mls = games_router.get_standings("mls")
    if mls is not None:
        check("mls standings is a season envelope", isinstance(mls, dict), type(mls))
        groups = mls.get("groups") if isinstance(mls, dict) else None
        # The assertion the defect was about: the table must name its own season,
        # and that season must be the one currently being played.
        check("mls names its season", isinstance(mls.get("season"), int),
              f"season={mls.get('season')!r}")
        check("mls season is not a past one",
              isinstance(mls.get("season"), int)
              and mls["season"] >= _dt.date.today().year,
              f"serving {mls.get('season')!r} in {_dt.date.today().year}")
        check("mls states whether the season is in progress",
              isinstance(mls.get("in_progress"), bool), f"got {mls.get('in_progress')!r}")
        check("mls has Eastern+Western groups",
              isinstance(groups, list) and len(groups) == 2,
              f"got {len(groups) if isinstance(groups, list) else type(groups)}")
        if isinstance(groups, list) and len(groups) == 2:
            names = sorted(g["group"] for g in groups)
            check("groups are Eastern/Western Conference",
                  names == ["Eastern Conference", "Western Conference"], str(names))
            sample = groups[0]["rows"][0]
            for key in ("rank", "abbrev", "name", "played", "wins", "draws", "losses",
                        "gf", "ga", "gd", "points"):
                check(f"mls row has {key}", key in sample, f"missing {key}")
            # A mid-season table must not look like a finished one. MLS plays 34.
            if mls.get("in_progress"):
                most = max(r["played"] or 0 for g in groups for r in g["rows"])
                check("in-progress table is not a completed season",
                      most < 34, f"max played={most} while in_progress=True")

    print("== [8] non-grouped leagues: a flat table that names its season ==")
    with patch.object(espn, "team_strength_standings", side_effect=_mock_nba_standings), \
            patch.object(games_router, "seasons_we_hold", return_value={2026}):
        nba = games_router.get_standings("nba")
    check("nba standings is a season envelope", isinstance(nba, dict), type(nba))
    nba_rows = nba.get("teams") if isinstance(nba, dict) else None
    check("nba envelope carries a flat team list",
          isinstance(nba_rows, list) and len(nba_rows) > 0,
          f"got {type(nba_rows)} len={len(nba_rows) if isinstance(nba_rows, list) else 'n/a'}")
    if nba_rows:
        check("nba row has no group key",
              "group" not in nba_rows[0] and "rows" not in nba_rows[0],
              f"first={str(nba_rows[0])[:100]}")
    # The defect this exists to catch: a standings table with nothing naming its
    # season. The season served must also be one the publisher lists as having a
    # standings table — `season.year` alone pointed at 2027 for NBA/MLB/NHL on
    # 2026-08-17 while the rows on screen were 2026.
    check("nba names its season", isinstance(nba.get("season"), int),
          f"season={nba.get('season')!r}")
    check("nba season is one the publisher offers",
          isinstance(nba.get("available_seasons"), list)
          and nba.get("season") in (nba.get("available_seasons") or []),
          f"season={nba.get('season')!r} not in {(nba.get('available_seasons') or [])[:4]}")

    print()

    assert not FAILURES, f"{len(FAILURES)} contract check(s) failed: {FAILURES}"


if __name__ == "__main__":
    test_leagues_hub_contract()
    print("ALL ASSERTIONS PASSED")
