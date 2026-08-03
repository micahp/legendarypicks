#!/usr/bin/env python3
"""
ingest_team_results.py — season-to-date team game results via ESPN team schedules.

One schedule call per team (~30 for MLB) yields every completed game with final
scores — the team-level series (runs for/against, result) that the momentum
engine needs and that no existing table holds (team_game_stats is box-stat
snapshots, prop_games has no finals).

Usage: python3 ingest_team_results.py [--league mlb]

## What this file got wrong for 3,305 rows

Its INSERT named nine columns and stopped there. `season`, `status`, `source` and
`run_id` were added to `team_game_results` by the coverage work and this ingest
was never told, so every MLB row it has ever written carries NULL in all four —
the single largest unattributed block in `COV-source`, and the reason MLB cannot
be offered at all: `league_stats.py` resolves the live season with `MAX(season)`,
and `MAX(NULL)` is NULL.

The season was never missing from the source. ESPN publishes it on every event
(`season.year`), alongside the phase (`seasonType.id`) — both were read into
memory and thrown away. Deriving it from `game_date[:4]` would have worked for
baseball and silently corrupted every other league, since ESPN keys NBA and NHL
by the year a season ENDS. So it goes through `season_keys.normalize_season`,
which refuses rather than guesses.

## And the reason one game had only one team

The loop asks each team for its own schedule and writes one row from it, so a
game is only whole if BOTH teams' documents agree it finished. `_get` caches for
600s and the thirty fetches are minutes apart, so a game ending mid-run lands
from the side fetched later and not from the side fetched earlier: on 2026-08-01
`401816347` ARI @ CLE was written for ARI and not for CLE, leaving CLE one game
short of its own record with nothing anywhere marking the row as partial. Each
event now writes BOTH competitors — the document already carries them — so which
team's schedule an event arrives on stops being able to change what is stored.
"""
import sys, os, json, sqlite3, argparse, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from espn_client import LEAGUES, _get
from season_keys import normalize_season
from game_types import normalize_game_type, REG, POST

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

# This ingest reads ESPN's site API team-schedule document. Named at the level the
# provenance readout groups by, because "which publisher" is the question a reader
# of that table is asking — `espn_site_api` is the same answer the scoreboard path
# gives, and the suffix says which document inside it.
SOURCE = "espn_site_api:team_schedule"

# Columns this ingest writes that the original CREATE never had. Added by ALTER on
# an existing table rather than assumed present: a database old enough to predate
# them is exactly the one that produced the NULL block above, and a KeyError at
# insert time is a better outcome than nine columns written quietly.
_REQUIRED = {
    "season": "INTEGER", "status": "TEXT", "source": "TEXT", "run_id": "TEXT",
}


def ensure_table(con):
    con.execute("""CREATE TABLE IF NOT EXISTS team_game_results(
        league TEXT NOT NULL, game_id TEXT NOT NULL, team TEXT NOT NULL,
        game_date TEXT, opponent TEXT, home_away TEXT,
        score_for REAL, score_against REAL, win INTEGER,
        ingested_at TEXT DEFAULT (datetime('now')),
        season INTEGER, status TEXT, source TEXT, run_id TEXT,
        PRIMARY KEY(league, game_id, team))""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_tgr_team ON team_game_results(league, team, game_date)")
    have = {r[1] for r in con.execute("PRAGMA table_info(team_game_results)")}
    for column, decl in _REQUIRED.items():
        if column not in have:
            con.execute(f"ALTER TABLE team_game_results ADD COLUMN {column} {decl}")


def ingest(league: str = "mlb") -> int:
    path = LEAGUES[league][0]
    teams_doc = _get(f"https://site.api.espn.com/apis/site/v2/sports/{path}/teams", ttl=3600)
    abbrevs = [t["team"]["abbreviation"].lower()
               for t in teams_doc["sports"][0]["leagues"][0]["teams"]]
    con = sqlite3.connect(DB)
    ensure_table(con)
    run_id = f"{league}-team-results-{int(time.time())}"
    wrote, skipped_phase, seen = 0, 0, set()
    for ab in abbrevs:
        try:
            sched = _get(f"https://site.api.espn.com/apis/site/v2/sports/{path}/teams/{ab}/schedule", ttl=600)
        except Exception as e:
            print(f"  {ab}: schedule fetch failed ({e})"); continue
        for ev in sched.get("events", []):
            comp = (ev.get("competitions") or [{}])[0]
            if not comp.get("status", {}).get("type", {}).get("completed"):
                continue
            comps = comp.get("competitors", [])
            if len(comps) != 2:
                continue
            game_id = str(ev.get("id"))
            if game_id in seen:
                continue  # already written from the other team's document

            # Phase and season off the envelope, not off our own request or the
            # calendar. The team-schedule endpoint answers with the season type it
            # feels like: it returned only regular-season games on 2026-08-03, which
            # is why no spring-training row was ever noticed in the 3,305 — that was
            # the publisher's choice on the day, not a filter we were applying.
            try:
                phase = normalize_game_type("espn", league, (ev.get("seasonType") or {}).get("id"))
                season = normalize_season(SOURCE, league, (ev.get("season") or {}).get("year"))
            except ValueError as e:
                print(f"  {ab}: {game_id} skipped — {e}")
                continue
            if phase not in (REG, POST):
                skipped_phase += 1
                continue

            # Both sides, from the one document that names both. Writing only the
            # team whose schedule this is made completeness depend on fetch order.
            rows = []
            for mine in comps:
                theirs = next((c for c in comps if c is not mine), None)
                sf = (mine.get("score") or {}).get("value")
                sa = (theirs.get("score") or {}).get("value") if theirs else None
                if theirs is None or sf is None or sa is None:
                    rows = []
                    break
                win = mine.get("winner")
                rows.append((
                    league, game_id, mine["team"]["abbreviation"],
                    (ev.get("date") or "")[:10], theirs["team"]["abbreviation"],
                    mine.get("homeAway"), float(sf), float(sa),
                    1 if win is True else 0 if win is False else None,
                    season, "completed", SOURCE, run_id,
                ))
            if not rows:
                continue
            con.executemany("""INSERT OR REPLACE INTO team_game_results
                (league, game_id, team, game_date, opponent, home_away, score_for,
                 score_against, win, season, status, source, run_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
            seen.add(game_id)
            wrote += len(rows)
        con.commit()

    # Reconcile before reporting success. A count of rows written is a claim about
    # this run; that every game holds both of its teams is a claim about the table,
    # and it is the one that was false.
    orphans = con.execute(
        "SELECT COUNT(*) FROM (SELECT game_id FROM team_game_results"
        " WHERE league=? GROUP BY game_id HAVING COUNT(*)<>2)", (league,),
    ).fetchone()[0]
    unattributed = con.execute(
        "SELECT COUNT(*) FROM team_game_results WHERE league=?"
        " AND (season IS NULL OR source IS NULL OR source='')", (league,),
    ).fetchone()[0]
    con.close()
    print(f"{league}: wrote {wrote} team-game rows over {len(seen)} games, "
          f"{len(abbrevs)} teams (skipped {skipped_phase} non-REG/POST)")
    print(f"  run_id={run_id} source={SOURCE}")
    print(f"  one-sided games: {orphans}   rows missing season or source: {unattributed}")
    if orphans or unattributed:
        print("  ^ NOT clean — see the module docstring; do not report this run as complete")
    return wrote


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", default="mlb")
    args = ap.parse_args()
    ingest(args.league)
