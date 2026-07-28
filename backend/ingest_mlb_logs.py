#!/usr/bin/env python3
"""
ingest_mlb_logs.py — per-GAME MLB hitting logs derived from Statcast events.

The season-aggregate ingest (ingest_statcast.py) groups all pitches by batter.
This groups by (batter, game) instead, deriving a per-game box line from the
pitch-level `events` column: H, 2B, 3B, HR, BB, K, TB. Runs and RBI are
fetched from the MLB Stats API boxscore (same source as settlement.py) because
they require whole-game baserunner tracking that per-batter Statcast rows
cannot provide.

Usage: python3 ingest_mlb_logs.py [--days 60]
       python3 ingest_mlb_logs.py --start 2026-03-15 --end 2026-03-22

--start/--end pull an explicit date window instead of a trailing --days lookback
from now — needed to backfill history in chunks. Internally this fetches ONE DAY
at a time via pybaseball.statcast(day, day, parallel=False) and writes it to the
DB before moving to the next day, freeing each day's DataFrame immediately after.
pybaseball's default parallel=True spins up a thread per day in the range, each
holding a full day's wide pitch-level DataFrame concurrently, then pd.concat's
them all — on this box that blew load to 189+ and swap to near-full from a
single 7-day chunk. Day-by-day + parallel=False bounds peak memory to ~1 day's
data regardless of how wide the --start/--end window is.
"""
import sys, os, gc, json, sqlite3, datetime as dt, time as _time, urllib.request as _ur
from typing import Optional
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest_nfl_logs import ensure_table  # reuse the shared schema
from team_codes import normalize

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

HIT_EVENTS = {"single": 1, "double": 2, "triple": 3, "home_run": 4}  # event -> total bases

_MLB_BOXSCORE_URL = "https://statsapi.mlb.com/api/v1/game/{gamePk}/boxscore"
_MLB_HDR = {"User-Agent": "Mozilla/5.0"}

# Per-run cache: game_pk → boxscore JSON. One API call per unique game.
_boxscore_cache: dict = {}


def _fetch_boxscore(game_pk: int) -> Optional[dict]:
    """Fetch MLB Stats API boxscore for a game. Cached per game_pk in memory."""
    if game_pk in _boxscore_cache:
        return _boxscore_cache[game_pk]
    try:
        url = _MLB_BOXSCORE_URL.format(gamePk=game_pk)
        req = _ur.Request(url, headers=_MLB_HDR)
        with _ur.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
    except Exception:
        data = None
    _boxscore_cache[game_pk] = data
    return data


def _get_runs_rbi(game_pk: int, mlbam: int) -> tuple:
    """Return (runs, rbi) for a batter from the boxscore, or (None, None).
    Navigates teams.{home,away}.players.ID{mlbam}.stats.batting.{runs,rbi}.
    """
    box = _fetch_boxscore(game_pk)
    if not box:
        return None, None
    for side in ("away", "home"):
        team_data = box.get("teams", {}).get(side, {})
        players_dict = team_data.get("players", {})
        player_key = f"ID{mlbam}"
        pdata = players_dict.get(player_key)
        if pdata is None:
            continue
        batting = pdata.get("stats", {}).get("batting", {})
        runs = batting.get("runs")
        rbi = batting.get("rbi")
        if runs is not None or rbi is not None:
            return runs, rbi
    return None, None


def _process_day(data, con, mlbam_to_player: dict, season: int) -> int:
    """Derive per-game box lines from one day's Statcast DataFrame and write to DB."""
    bat = data[data["events"].notna()].copy()
    del data
    if len(bat) == 0:
        return 0
    ingested = 0
    for (batter, game_pk), g in bat.groupby(["batter", "game_pk"]):
        mlbam = int(batter)
        pid = mlbam_to_player.get(mlbam)
        ev = g["events"].value_counts().to_dict()
        h = sum(ev.get(k, 0) for k in HIT_EVENTS)
        tb = sum(ev.get(k, 0) * v for k, v in HIT_EVENTS.items())
        stats = {
            "H": int(h),
            "2B": int(ev.get("double", 0)),
            "3B": int(ev.get("triple", 0)),
            "HR": int(ev.get("home_run", 0)),
            "BB": int(ev.get("walk", 0)),
            "K": int(ev.get("strikeout", 0)),
            "TB": int(tb),
            "PA": int(len(g)),
        }
        # Merge R/RBI from MLB Stats API boxscore (Statcast events can't derive these)
        runs, rbi = _get_runs_rbi(int(game_pk), mlbam)
        if runs is not None:
            stats["R"] = int(runs)
        if rbi is not None:
            stats["RBI"] = int(rbi)
        gdate = str(g["game_date"].iloc[0])[:10]
        team = None
        opponent = None
        home_away = None
        # home/away team abbrevs exist as 'home_team'/'away_team'; batter's team = inferred via inning_topbot
        if "inning_topbot" in g.columns and "home_team" in g.columns and "away_team" in g.columns:
            top = (g["inning_topbot"].iloc[0] == "Top")  # away bats in top
            team = normalize("mlb", g["away_team"].iloc[0]) if top else normalize("mlb", g["home_team"].iloc[0])
            opponent = normalize("mlb", g["home_team"].iloc[0]) if top else normalize("mlb", g["away_team"].iloc[0])
            home_away = "away" if top else "home"
        con.execute(
            """INSERT OR REPLACE INTO player_game_logs
               (player_id, league, season, game_no, game_id, game_date, team,
                opponent, home_away, stats, source, source_player_key)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (pid, "mlb", season, gdate, str(int(game_pk)), gdate, team,
             opponent, home_away, json.dumps(stats), "statcast", str(mlbam)))
        ingested += 1
    del bat
    return ingested


def ingest(days: int = 60, start_date: Optional[str] = None, end_date: Optional[str] = None) -> int:
    from pybaseball import statcast

    if start_date and end_date:
        end = dt.datetime.strptime(end_date, "%Y-%m-%d")
        start = dt.datetime.strptime(start_date, "%Y-%m-%d")
    else:
        end = dt.datetime.now()
        start = end - dt.timedelta(days=days)
    print(f"Pulling Statcast {start.date()}..{end.date()} (per-game derive), one day at a time...")

    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    ensure_table(con)
    season = end.year
    mlbam_to_player = {
        r["mlbam_id"]: r["id"]
        for r in con.execute("SELECT mlbam_id, id FROM players WHERE league='mlb' AND mlbam_id IS NOT NULL AND mlbam_id != 0")
    }

    ingested = 0
    cur = start
    while cur <= end:
        day = cur.strftime("%Y-%m-%d")
        # parallel=False: pybaseball's default spins up a thread per day in the range,
        # each holding a full day's wide pitch-level DataFrame concurrently — fine for a
        # single day (this call), but that concurrency is what OOM'd a multi-day range.
        data = statcast(day, day, verbose=False, parallel=False)
        if data is not None and len(data) > 0:
            n = _process_day(data, con, mlbam_to_player, season)
            ingested += n
            con.commit()
            print(f"  {day}: {n} game-logs")
        else:
            print(f"  {day}: no games")
        del data
        gc.collect()
        cur += dt.timedelta(days=1)
        _time.sleep(1)  # brief pause between days, don't hammer Savant or this box back-to-back

    resolved = con.execute(
        "SELECT COUNT(*) FROM player_game_logs WHERE league='mlb' AND season=? AND player_id IS NOT NULL",
        (season,)).fetchone()[0]
    print(f"  Ingested {ingested} MLB game-logs total ({resolved} spine-resolved for {season})")
    con.close()
    return ingested


if __name__ == "__main__":
    days = 60
    start_date = end_date = None
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])
    if "--start" in sys.argv:
        start_date = sys.argv[sys.argv.index("--start") + 1]
    if "--end" in sys.argv:
        end_date = sys.argv[sys.argv.index("--end") + 1]
    ingest(days, start_date, end_date)
