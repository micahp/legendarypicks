#!/usr/bin/env python3
"""
backfill_team_parity.py — Full completed-season team-stats ingest for NBA/NHL/NFL
that satisfies the fail-closed team_stats_contract.

For each league it:
  1. enumerates every completed regular-season game (via per-team schedule),
  2. writes reciprocal team_game_results pairs (scores from the schedule),
  3. fetches each game's /summary and writes paired team_game_stats
     (only games where BOTH teams have every required stat field are kept),
  4. records every game it could not write to team_stats_ingestion_failures.

It does NOT write team_stats_coverage. It used to, and the manifest it wrote was
"expected == fetched, internally consistent" — which was stated as a feature and is
the defect: an expectation copied from the result cannot fail. The verdict is written
by `reconcile_totals.py --write-coverage`, which reads the expected total from the
publisher. Re-running this script clears the league's coverage row, so a re-ingested
season is `unverified` until it is reconciled again — which is the correct state for a
season nobody has checked.

MLB is untouched (it is served from team_game_results directly).

Usage:
  cd backend && LP_DB_PATH=/abs/picks.dev.db venv/bin/python backfill_team_parity.py \
      [--leagues nba,nhl,nfl] [--delay 0.12]

Idempotent: reruns replace each league's rows under a fresh run_id.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import espn_client as espn
from team_stats_contract import extract_espn_team_stats, STAT_FIELDS, EXPECTED_TEAMS
from provenance import sources_for, format_provenance, publishers_for

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"

# Stamped on every row this script writes. Named for the publisher and the exact
# endpoints, because "espn" alone does not distinguish the site API used here
# from the core API reconcile_totals reads — and those two disagree about which
# events exist (see explain_gap). Switched from site.api.espn.com to
# site.web.api.espn.com 2026-08-06 (site.api is walled from this box per the
# espn-request-budget skill; the shared fetcher on site.web adds the disk cache).
SOURCE = "espn_site_web_api:scoreboard+summary"

# league -> (espn sport, espn league, season, seasontype)
LEAGUE_CFG = {
    "nba": ("basketball", "nba", 2026, 2),
    "nhl": ("hockey", "nhl", 2026, 2),
    "nfl": ("football", "nfl", 2025, 2),
    "mls": ("soccer", "usa.1", 2025, 1),
    # NCAAF is group-scoped (FBS = group 80). The per-team schedule path
    # below would walk all 807 league-wide teams — FBS AND FCS — and write
    # FCS games into the FBS table. ncaaf enumerates from the group-scoped
    # events collection instead (see enumerate_games_group).
    "ncaaf": ("football", "college-football", 2025, 2),
}

# Leagues whose games enumerate from a published group (FBS etc.) rather than
# per-team schedules. Mirrors espn_leagues.ESPN_LEAGUES scope_group.
GROUP_SCOPED = {"ncaaf": "80"}

NFL_STAT_COLUMNS = (
    "first_downs", "total_offensive_plays", "total_yards",
    "net_passing_yards", "rushing_yards", "defensive_special_teams_tds",
)

# Leagues whose games can end in a draw. `win INTEGER` is a 0/1 flag and a
# draw is neither 0 nor 1 — it must never be stored as a loss. Soccer rows
# carry the honest three-valued `result` ('W'/'D'/'L') plus a compat `win`
# (1 for W, 0 for D and L) so the integer readers that predate the column
# keep working; `result` is the source of truth. Non-soccer leagues keep
# their historical winner-flag behavior and write NULL result.
SOCCER_LEAGUES = frozenset(("mls",))


def _get(url: str, tries: int = 3, timeout: int = 20):
    # Route through the shared paced_http fetcher (espn_client), not raw
    # urllib: site.api.espn.com is walled from this box (espn-request-budget
    # skill, measured 2026-08-06), while site.web.api.espn.com answers and
    # the shared fetcher adds pacing + the disk cache so re-runs are free.
    # Configured where the work happens (see main), per the skill.
    return espn._get(url, ttl=3600)


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------

def ensure_schema(con: sqlite3.Connection) -> None:
    def add_col(table: str, coldef: str) -> None:
        try:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {coldef}")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc):
                raise

    add_col("team_game_results", "season INTEGER")
    add_col("team_game_results", "status TEXT")
    # Provenance. This table is the spine of the coverage contract and until
    # 2026-08-02 it recorded only WHEN a row landed, never from whom — so nothing
    # anywhere stated that it is ESPN while player_game_logs is nhle.com, and the
    # two publishers' disagreement about what the 2025-26 season is called went
    # unnoticed until it cost NHL its enablement. "One script writes it, so it's
    # obviously ESPN" stops being true the first time a second script writes it,
    # and nothing would say so. See backend/provenance.py.
    add_col("team_game_results", "source TEXT")
    add_col("team_game_results", "run_id TEXT")
    # Three-valued outcome for draw-capable leagues (soccer). Additive: the
    # 0/1 `win` column stays for existing readers; a draw is written as
    # win=0 + result='D', never as a loss.
    add_col("team_game_results", "result TEXT CHECK (result IN ('W','D','L'))")

    add_col("team_game_stats", "run_id TEXT")
    add_col("team_game_stats", "source TEXT")
    for col in NFL_STAT_COLUMNS:
        add_col("team_game_stats", f"{col} INTEGER")

    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS team_stats_coverage (
            run_id TEXT PRIMARY KEY, league TEXT NOT NULL, season INTEGER NOT NULL,
            season_start TEXT NOT NULL, season_end TEXT NOT NULL, status TEXT NOT NULL,
            expected_teams INTEGER NOT NULL, fetched_teams INTEGER NOT NULL,
            expected_games INTEGER, fetched_games INTEGER, paired_games INTEGER,
            paired_stat_games INTEGER, failure_count INTEGER NOT NULL DEFAULT 0,
            completed_at TEXT, source TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS team_stats_team_inventory (
            run_id TEXT NOT NULL, team_id TEXT NOT NULL, team_abbrev TEXT,
            PRIMARY KEY (run_id, team_id)
        );
        CREATE TABLE IF NOT EXISTS team_stats_ingestion_failures (
            run_id TEXT NOT NULL, game_id TEXT, team TEXT, reason TEXT NOT NULL,
            recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_ingestion_failures_run
            ON team_stats_ingestion_failures(run_id);
        """
    )
    # collapse any pre-existing duplicate rows so the unique index can be built
    # (keeps the lowest rowid per key; MLB rows are preserved, one per key)
    con.execute(
        "DELETE FROM team_game_stats WHERE rowid NOT IN "
        "(SELECT MIN(rowid) FROM team_game_stats GROUP BY league,game_id,team_abbrev)"
    )
    con.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_tgs_unique "
        "ON team_game_stats(league, game_id, team_abbrev)"
    )
    con.commit()


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------

def enumerate_games(sport: str, league: str, season: int, stype: int):
    """Return {game_id: {date, teams:{abbrev:{score,home_away,win}}}} for
    completed regular-season games, plus the set of team ids seen."""
    teams = _get(
        f"https://site.web.api.espn.com/apis/site/v2/sports/{sport}/{league}/teams?limit=50"
    )["sports"][0]["leagues"][0]["teams"]
    team_ids = [(t["team"]["id"], t["team"].get("abbreviation")) for t in teams]

    games: dict[str, dict] = {}
    for tid, _abbrev in team_ids:
        try:
            sched = _get(
                f"https://site.web.api.espn.com/apis/site/v2/sports/{sport}/{league}"
                f"/teams/{tid}/schedule?season={season}&seasontype={stype}"
            )
        except Exception:  # noqa: BLE001
            continue
        for e in sched.get("events", []):
            comp = (e.get("competitions") or [{}])[0]
            kind = comp.get("status", {}).get("type", {})
            # `completed`, not `state`. A POSTPONED game is state="post" too, and it
            # carries a score of **0**, not null — so the `val is None` guard below
            # waves it through as a played 0-0 result. Measured 2026-08-02: four NBA
            # 2025-26 postponements (401810384, 401810499, 401810506, 401810507) all
            # report {'MIN': '0', 'GS': '0'} with STATUS_POSTPONED, and each was
            # actually replayed under a NEW event id. Ingesting the shell credits both
            # teams a game they did not play and hands one of them a loss.
            #
            # The field was there the whole time. `state` answers "is this in the past";
            # `completed` answers "was it played", which is the question being asked.
            if not kind.get("completed"):
                continue
            gid = str(e["id"])
            if gid in games:
                continue
            date = (e.get("date") or "")[:10]
            side = {}
            ok = True
            for c in comp.get("competitors", []):
                ab = (c.get("team") or {}).get("abbreviation")
                sc = (c.get("score") or {})
                val = sc.get("value") if isinstance(sc, dict) else sc
                if ab is None or val is None:
                    ok = False
                    break
                side[ab] = {
                    "score": float(val),
                    "home_away": c.get("homeAway"),
                    "win": 1 if c.get("winner") else 0,
                    # raw flag, kept for the three-valued result write: a
                    # draw has winner unset/false on both sides, and `win`
                    # alone cannot express it
                    "winner": c.get("winner"),
                }
            if ok and len(side) == 2:
                games[gid] = {"date": date, "teams": side}
    return team_ids, games


def enumerate_games_group(sport: str, league: str, esp_league: str,
                          season: int, stype: int, group_id: str):
    """Group-scoped game enumeration (NCAAF FBS). Returns the same
    {game_id: {date, teams:{abbrev:{score, home_away, win, winner}}}} shape
    as enumerate_games, but from the published group's events collection —
    one request per page — instead of one request per team (807 league-wide
    teams for college football, FBS + FCS: the FCS games would pollute the
    FBS table). team_ids is populated from the group's teams collection.
    ``league`` is our key (espn_leagues registry lookup); ``esp_league`` is
    the site-API path segment (football/college-football) for the summary URL.
    """
    from espn_leagues import ESPN_LEAGUES
    core_path = ESPN_LEAGUES[league]["path"]
    base = (
        "https://sports.core.api.espn.com/v2/sports/{0}/seasons/{1}"
        "/types/{2}/groups/{3}".format(core_path, season, stype, group_id)
    )
    teams_doc = _get(f"{base}/teams?limit=200")
    team_ids = []
    for item in teams_doc.get("items", []):
        m = __import__("re").search(r"/teams/(\d+)", item.get("$ref", ""))
        if m:
            team_ids.append((m.group(1), ""))
    games: dict[str, dict] = {}
    events_doc = _get(f"{base}/events?limit=1")
    total = int(events_doc.get("count") or 0)
    page = 1
    seen: set[str] = set()
    while True:
        doc = _get(f"{base}/events?limit=100&page={page}")
        items = doc.get("items") or []
        if not items:
            break
        for item in items:
            m = __import__("re").search(r"/events/(\d+)", item.get("$ref", ""))
            if not m:
                continue
            gid = m.group(1)
            if gid in seen:
                continue
            seen.add(gid)
            try:
                sm = _get(
                    "https://site.web.api.espn.com/apis/site/v2/sports/"
                    f"{sport}/{esp_league}/summary?event={gid}"
                )
            except Exception:  # noqa: BLE001
                continue
            comp = ((sm.get("header") or {}).get("competitions") or [{}])[0]
            kind = comp.get("status", {}).get("type", {})
            if not kind.get("completed"):
                continue
            date = (comp.get("date") or "")[:10]
            side = {}
            ok = True
            for c in comp.get("competitors", []):
                ab = (c.get("team") or {}).get("abbreviation")
                sc = (c.get("score") or {})
                val = sc.get("value") if isinstance(sc, dict) else sc
                if ab is None or val is None:
                    ok = False
                    break
                side[ab] = {
                    "score": float(val),
                    "home_away": c.get("homeAway"),
                    "win": 1 if c.get("winner") else 0,
                    "winner": c.get("winner"),
                }
            if ok and len(side) == 2:
                games[gid] = {"date": date, "teams": side}
        if page >= int(doc.get("pageCount", 1) or 1):
            break
        page += 1
    print(f"  group {group_id}: {total} published events, {len(games)} completed")
    return team_ids, games


def _result_for(league: str, mine: dict, theirs: dict) -> tuple:
    """Return (result, win) for one team's row.

    Soccer: `result` is the honest three-valued outcome — 'W' when the
    competitor's winner flag is set, 'D' when the completed game's scores
    are level (both teams get 'D'), 'L' otherwise. `win` stays integer-
    compatible for the readers that predate `result`: 1 for W, 0 for D
    and L — a draw is a not-win, never a loss. Non-soccer leagues keep
    the historical winner-flag behavior and write NULL result.
    """
    if league not in SOCCER_LEAGUES:
        return None, mine["win"]
    if mine.get("winner") is True:
        return "W", 1
    if mine["score"] == theirs["score"]:
        return "D", 0
    return "L", 0


def run_league(con: sqlite3.Connection, league: str, run_id: str,
               delay: float) -> dict:
    sport, esp_league, season, stype = LEAGUE_CFG[league]
    print(f"[{league}] enumerating games (season {season})...", flush=True)
    group_id = GROUP_SCOPED.get(league)
    if group_id:
        team_ids, games = enumerate_games_group(
            sport, league, esp_league, season, stype, group_id)
    else:
        team_ids, games = enumerate_games(sport, esp_league, season, stype)
    print(f"[{league}] {len(games)} completed games, {len(team_ids)} teams",
          flush=True)

    # fresh slate for this league (keep MLB + other leagues intact). Dropping the
    # coverage row is deliberate: a re-ingested season is `unverified` — nobody has
    # checked it yet — until reconcile_totals.py writes a new verdict. The old
    # failure rows go too, or a clean run inherits a previous run's ghosts and the
    # verdict is about a run that no longer exists.
    con.execute("DELETE FROM team_game_results WHERE league=?", (league,))
    con.execute("DELETE FROM team_game_stats WHERE league=?", (league,))
    con.execute("DELETE FROM team_stats_coverage WHERE league=?", (league,))
    con.execute("DELETE FROM team_stats_ingestion_failures WHERE run_id LIKE ?",
                (f"{league}-%",))
    con.commit()

    captured_at = datetime.now(timezone.utc).isoformat()
    teams_seen: set[str] = set()
    games_written = 0
    dates: list[str] = []
    fields = STAT_FIELDS[league]

    gids = list(games)
    for i, gid in enumerate(gids):
        g = games[gid]
        path = f"{sport}/{esp_league}"
        try:
            sm = _get(f"https://site.web.api.espn.com/apis/site/v2/sports/{path}"
                      f"/summary?event={gid}")
        except Exception as exc:  # noqa: BLE001
            con.execute(
                "INSERT INTO team_stats_ingestion_failures(run_id,game_id,team,reason)"
                " VALUES(?,?,?,?)", (run_id, gid, "", f"summary fetch: {exc}"))
            continue

        rows = extract_espn_team_stats(league, sm)
        # require both teams complete + both present in the schedule pair
        if len(rows) != 2 or any(
            r["home_away"] not in ("home", "away")
            or r["team_abbrev"] not in g["teams"]
            or any(r["stats"].get(f) is None for f in fields)
            for r in rows
        ):
            con.execute(
                "INSERT INTO team_stats_ingestion_failures(run_id,game_id,team,reason)"
                " VALUES(?,?,?,?)", (run_id, gid, "", "incomplete stat fields"))
            if delay:
                time.sleep(delay)
            continue

        abbrevs = [r["team_abbrev"] for r in rows]
        try:
            con.execute("BEGIN")
            # reciprocal result rows
            for r in rows:
                me = r["team_abbrev"]
                opp = abbrevs[1] if abbrevs[0] == me else abbrevs[0]
                mine = g["teams"][me]
                theirs = g["teams"][opp]
                result, win = _result_for(league, mine, theirs)
                con.execute(
                    "INSERT OR REPLACE INTO team_game_results"
                    "(league,game_id,team,game_date,opponent,score_for,score_against,"
                    "win,result,season,status,home_away,source,run_id) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (league, gid, me, g["date"], opp, mine["score"],
                     theirs["score"], win, result, season, "completed",
                     mine["home_away"], SOURCE, run_id))
            # paired stat rows
            for r in rows:
                s = r["stats"]
                con.execute(
                    "INSERT OR REPLACE INTO team_game_stats"
                    "(league,game_id,captured_at,team_abbrev,home_away,run_id,source,"
                    "fgm_fga,tpm_tpa,ftm_fta,rebounds,off_rebounds,def_rebounds,"
                    "assists,steals,blocks,turnovers,"
                    "shots,blocked_shots,hits,takeaways,giveaways,faceoff_pct,"
                    "powerplay_goals,powerplay_opps,shorthanded_goals,penalty_min,"
                    "first_downs,total_offensive_plays,total_yards,net_passing_yards,"
                    "rushing_yards,defensive_special_teams_tds) "
                    "VALUES(?,?,?,?,?,?,?, ?,?,?,?,?,?,?,?,?,?, ?,?,?,?,?,?,?,?,?,?, "
                    "?,?,?,?,?,?)",
                    (league, gid, captured_at, r["team_abbrev"], r["home_away"], run_id,
                     SOURCE,
                     s.get("fgm_fga"), s.get("tpm_tpa"), s.get("ftm_fta"),
                     s.get("rebounds"), s.get("off_rebounds"), s.get("def_rebounds"),
                     s.get("assists"), s.get("steals"), s.get("blocks"), s.get("turnovers"),
                     s.get("shots"), s.get("blocked_shots"), s.get("hits"),
                     s.get("takeaways"), s.get("giveaways"), s.get("faceoff_pct"),
                     s.get("powerplay_goals"), s.get("powerplay_opps"),
                     s.get("shorthanded_goals"), s.get("penalty_min"),
                     s.get("first_downs"), s.get("total_offensive_plays"),
                     s.get("total_yards"), s.get("net_passing_yards"),
                     s.get("rushing_yards"), s.get("defensive_special_teams_tds")))
            con.commit()
        except Exception as exc:  # noqa: BLE001
            # ROLLBACK is only legal if a transaction is actually open. Under
            # autocommit the BEGIN may itself be what failed, and a bare ROLLBACK
            # would then raise *inside the handler* and lose the failure record —
            # the one piece of evidence that made §9 solvable.
            if con.in_transaction:
                con.execute("ROLLBACK")
            con.execute(
                "INSERT INTO team_stats_ingestion_failures(run_id,game_id,team,reason)"
                " VALUES(?,?,?,?)", (run_id, gid, "", f"write: {exc}"))
            con.commit()
            continue

        for r in rows:
            teams_seen.add(r["team_abbrev"])
        games_written += 1
        dates.append(g["date"])
        if i % 50 == 0:
            print(f"[{league}] {i+1}/{len(gids)} games, written={games_written}",
                  flush=True)
        if delay:
            time.sleep(delay)

    # inventory
    for r_id, ab in team_ids:
        con.execute(
            "INSERT OR REPLACE INTO team_stats_team_inventory(run_id,team_id,team_abbrev)"
            " VALUES(?,?,?)", (run_id, str(r_id), ab))

    expected = EXPECTED_TEAMS[league]
    fetched_teams = len(teams_seen)
    failures = con.execute(
        "SELECT COUNT(*) FROM team_stats_ingestion_failures WHERE run_id=?",
        (run_id,)).fetchone()[0]
    con.commit()

    # NO team_stats_coverage WRITE HERE. This function is not in a position to
    # judge its own completeness, and when it tried it wrote
    # `expected_games = fetched_games = paired_games = games_written` — four columns,
    # one variable, incapable of disagreeing — alongside a hardcoded
    # `failure_count=0` while this very loop was recording failures, and a `status`
    # that only ever compared team counts. The result said `complete` over a season
    # missing four games for nineteen days.
    #
    # The expectation comes from the publisher, so the check belongs where the
    # publisher is read:  reconcile_totals.py --write-coverage.
    print(f"[{league}] DONE: {games_written} games, {fetched_teams}/{expected} teams, "
          f"{failures} failures — coverage NOT written; run "
          f"`reconcile_totals.py --league {league} --write-coverage` to judge it",
          flush=True)
    return {"league": league, "games": games_written, "teams": fetched_teams,
            "expected_teams": expected, "failures": failures,
            "run_id": run_id, "season": season,
            "season_start": min(dates) if dates else None,
            "season_end": max(dates) if dates else None}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--leagues", default="nba,nhl,nfl")
    ap.add_argument("--delay", type=float, default=0.12)
    args = ap.parse_args()

    # The shared fetcher's settings must be configured where the work happens
    # (espn-request-budget skill §4): roster_sync burned 128 requests by
    # configuring in main only and being entered through another door. This
    # backfill is the same shape — run_league() calls espn._get directly.
    espn.set_retry_waits((5.0, 30.0, 120.0))
    espn.set_min_interval(float(os.environ.get("LP_ESPN_MIN_INTERVAL", "0.5")))
    espn.set_disk_cache(
        os.environ.get("LP_ESPN_CACHE_DIR")
        or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "data", "espn-cache"),
        ttl=float(os.environ.get("LP_ESPN_CACHE_TTL", "43200")),
    )

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # isolation_level=None puts sqlite3 in autocommit and makes BEGIN/COMMIT/ROLLBACK
    # mean exactly what they say. Under the default (implicit) mode the driver opens a
    # transaction on its own before a DML statement, and the explicit `BEGIN` in
    # run_league() then raises "cannot start a transaction within a transaction" — which
    # is not hypothetical: it silently cost four NBA games and one NHL game on
    # 2026-07-14. See docs/DATA-COVERAGE-CONTRACT.md §9.
    con = sqlite3.connect(DB, timeout=60, isolation_level=None)
    con.execute("PRAGMA busy_timeout=60000")
    ensure_schema(con)

    results = []
    for lg in [x.strip() for x in args.leagues.split(",") if x.strip()]:
        if lg not in LEAGUE_CFG:
            print(f"skip unknown league {lg}")
            continue
        results.append(run_league(con, lg, f"{lg}-parity-{ts}", args.delay))

    print("\n=== SUMMARY ===")
    for r in results:
        print(r)

    # Provenance, printed at the one moment someone is definitely looking: the
    # end of the ingest that just wrote. The NHL season-key split survived
    # because no run ever stated which publisher its rows came from, so nobody
    # had cause to ask whether two tables were speaking the same language.
    # Multiple publishers for one league is not an error — it is a list of
    # boundaries that each need a translation, and it belongs on screen.
    print("\n=== PROVENANCE (what this database now holds, by source) ===")
    for r in results:
        lg = r["league"]
        pubs = publishers_for(con, lg)
        for line in format_provenance(sources_for(con, lg)):
            print(line)
        if len(pubs) > 1:
            print(f"  NOTE {lg}: {len(pubs)} publishers — {', '.join(pubs)}. "
                  f"Every join across their tables crosses a vocabulary boundary "
                  f"(season keys: season_keys.py, team codes: team_codes.py).")
    con.close()


if __name__ == "__main__":
    main()
