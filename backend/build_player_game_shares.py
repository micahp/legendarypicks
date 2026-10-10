"""build_player_game_shares.py -- NFL per-game shares, and the season table rebuilt from them.

Denominator: nflverse's published team totals (stats_team_week_YEAR.parquet). Each team-game's
targets, air yards and carries come from there, so a share is always a player's count over the
count the publisher calls the team's. Published team codes (LA, WAS) map to ESPN's (LAR, WSH) here,
once, at the boundary.

Air yards: the denominator is TEAM PASSING air yards. The publisher names the column
receiving_air_yards, but on every team-game it equals passing_air_yards (checked 2025 and 2026).
Player air yards are assigned only on target records, so the residual (team total minus assigned)
is kept as air_yards_unassigned and never renormalized into the players. The residual is signed:
no-receiver passes (throwaways) can carry negative air yards, so it can be negative and player shares
can sum above 100% of the team. Consumers must not force these shares to total 100%.

Numerators and shares, per player per game:
  targets, air_yards: copy the publisher's target_share / air_yards_share, then check them against
      our log value over the published total (a mismatch above 1e-6 raises).
  carries: nflverse publishes no per-game carry share, so it is derived: player carries over the
      published team carries.

The season row is the sum ratio over the team's published games, not an average of weekly shares.
Only targets, air_yards and carries are owned here; build_player_shares.py owns the rest.

Usage: LP_DB_PATH=... python3 build_player_game_shares.py --season 2026 [--dry-run]
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sqlite3
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_player_shares  # noqa: E402
from migrate_player_game_shares import migrate  # noqa: E402

LEAGUE = "nfl"
PER_GAME_METRICS = build_player_shares.PER_GAME_METRICS
TEAM_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_%d.parquet"
TEAM_CODE_VOCAB = {"LA": "LAR", "WAS": "WSH"}
SHARE_TOLERANCE = 1e-6
TEAM_COLUMNS = ["season", "week", "team", "season_type", "game_id",
                "carries", "targets", "receiving_air_yards"]


def fetch_team_file(season, cache_dir):
    """Download the publisher's team-week file. Returns (path, sha256, bytes, fetched_at)."""
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, "stats_team_week_%d.parquet" % season)
    if not os.path.exists(path):
        part = path + ".part"
        with urllib.request.urlopen(TEAM_URL % season, timeout=60) as resp, open(part, "wb") as out:
            out.write(resp.read())
        os.replace(part, path)
    with open(path, "rb") as f:
        data = f.read()
    fetched = dt.datetime.fromtimestamp(os.path.getmtime(path), dt.timezone.utc).isoformat()
    return path, hashlib.sha256(data).hexdigest(), len(data), fetched


def totals_from_rows(rows, season):
    """{(game_id, team): {week, targets, air_yards, carries}} for the season's regular season."""
    totals = {}
    for r in rows:
        if r["season"] != season or r["season_type"] != "REG":
            continue
        for col in ("carries", "targets", "receiving_air_yards"):
            if r[col] is None:
                raise RuntimeError("published team-game %s %s has null %s"
                                   % (r["game_id"], r["team"], col))
        team = TEAM_CODE_VOCAB.get(r["team"], r["team"])
        key = (r["game_id"], team)
        if key in totals:
            raise RuntimeError("duplicate published team-game %s %s" % key)
        totals[key] = {"week": r["week"], "carries": r["carries"], "targets": r["targets"],
                       "air_yards": r["receiving_air_yards"]}
    return totals


def read_team_totals(path, season):
    import pyarrow.parquet as pq
    rows = pq.read_table(path, columns=TEAM_COLUMNS).to_pylist()
    return totals_from_rows(rows, season)


def build_game_rows(log_rows, totals, season, now):
    """log_rows: (player_id, team, game_id, stats_json). Returns (rows, report)."""
    rows = []
    report = {m: {"copied": 0, "derived": 0, "unpublished": 0, "max_err": 0.0}
              for m in PER_GAME_METRICS}
    missing, joined, no_player = [], 0, 0
    assigned = {}
    for player_id, team, game_id, stats_json in log_rows:
        tt = totals.get((game_id, team))
        if tt is None:
            missing.append((game_id, team))
            continue
        joined += 1
        s = json.loads(stats_json)
        assigned[(game_id, team)] = assigned.get((game_id, team), 0) + (s.get("rec_air_yds") or 0)
        if player_id is None:
            no_player += 1
            continue
        checks = (
            ("targets", s.get("targets"), s.get("target_share"), tt["targets"]),
            ("air_yards", s.get("rec_air_yds"), s.get("air_yards_share"), tt["air_yards"]),
            ("carries", s.get("carries"), None, tt["carries"]),
        )
        for metric, value, published, total in checks:
            if value is None:
                continue
            if total == 0 and value != 0:
                raise RuntimeError("%s %s: player %s has %s %s on a published team total of 0"
                                   % (game_id, team, player_id, value, metric))
            computed = value / total if total else None
            r = report[metric]
            if metric == "carries":
                share, source = computed, "derived_carries"
                r["derived"] += 1
            elif published is None:
                share, source = None, "nflverse_weekly"
                r["unpublished"] += 1
            else:
                if computed is not None:
                    err = abs(published - computed)
                    r["max_err"] = max(r["max_err"], err)
                    if err > SHARE_TOLERANCE:
                        raise RuntimeError("%s %s %s: published share %r != computed %r"
                                           % (game_id, team, metric, published, computed))
                share, source = published, "nflverse_weekly"
                r["copied"] += 1
            rows.append((LEAGUE, season, tt["week"], game_id, team, player_id, metric,
                         share, value, total, source, now))
    if missing:
        raise RuntimeError("%d log rows have no published team-game, e.g. %r"
                           % (len(missing), sorted(set(missing))[:5]))
    negative = []
    for key, tt in totals.items():
        tt["air_yards_unassigned"] = tt["air_yards"] - assigned.get(key, 0)
        if tt["air_yards_unassigned"] < -SHARE_TOLERANCE:
            negative.append((key[0], key[1], tt["air_yards_unassigned"]))
    unassigned = sum(tt["air_yards_unassigned"] for tt in totals.values())
    team_air = sum(tt["air_yards"] for tt in totals.values())
    return rows, {"joined": joined, "no_player": no_player, "metrics": report,
                  "air_yards_unassigned": unassigned, "air_yards_team": team_air,
                  "air_yards_negative": sorted(negative)}


def season_rows(game_rows, totals, season, now):
    team_sum, team_games, through = {}, {}, {}
    for (game_id, team), tt in totals.items():
        team_games[team] = team_games.get(team, 0) + 1
        through[team] = max(through.get(team, 0), tt["week"])
        for metric in PER_GAME_METRICS:
            team_sum[(team, metric)] = team_sum.get((team, metric), 0) + tt[metric]
    player, games = {}, {}
    for row in game_rows:
        _, _, _, game_id, team, player_id, metric, _, value, _, _, _ = row
        key = (team, player_id, metric)
        player[key] = player.get(key, 0) + value
        games.setdefault((team, player_id), set()).add(game_id)
    out = []
    for (team, player_id, metric), value in player.items():
        if not value:
            continue
        total = team_sum[(team, metric)]
        out.append((LEAGUE, season, team, player_id, metric, value, total,
                    value / total if total else None,
                    len(games[(team, player_id)]), team_games[team], str(through[team]),
                    "player_game_shares", now))
    return out


def write(con, season, totals, fetch_meta, game_rows, season_out):
    build_player_shares.ensure_table(con)
    _, sha, _, fetched = fetch_meta
    con.execute("DELETE FROM nfl_team_game_totals WHERE league=? AND season=?", (LEAGUE, season))
    con.execute("DELETE FROM player_game_shares WHERE league=? AND season=?", (LEAGUE, season))
    marks = ",".join("?" * len(PER_GAME_METRICS))
    con.execute("DELETE FROM player_team_shares WHERE league=? AND season=? AND metric IN (%s)"
                % marks, (LEAGUE, season, *PER_GAME_METRICS))
    con.executemany(
        "INSERT INTO nfl_team_game_totals (league, season, week, game_id, team, carries, targets, "
        "air_yards, air_yards_unassigned, source, sha256, fetched_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [(LEAGUE, season, tt["week"], game_id, team, tt["carries"], tt["targets"],
          tt["air_yards"], tt["air_yards_unassigned"], "nflverse_stats_team_week", sha, fetched)
         for (game_id, team), tt in totals.items()])
    con.executemany("INSERT INTO player_game_shares VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", game_rows)
    con.executemany("INSERT INTO player_team_shares VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", season_out)
    con.commit()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, required=True, help="LP season key (ESPN start year)")
    ap.add_argument("--cache-dir", default="/tmp/lp-nfl-team-totals")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    db_path = os.environ.get("LP_DB_PATH")
    if not db_path:
        raise SystemExit("LP_DB_PATH is required (this builder never defaults to prod)")

    fetch_meta = fetch_team_file(args.season, args.cache_dir)
    path, sha, nbytes, _ = fetch_meta
    print("published team file %s: %d bytes sha256=%s" % (path, nbytes, sha))
    totals = read_team_totals(path, args.season)
    print("published team-games (REG, %d): %d" % (args.season, len(totals)))

    con = sqlite3.connect(db_path, timeout=60)
    migrate(con)
    log_rows = con.execute(
        "SELECT player_id, team, game_id, stats FROM player_game_logs "
        "WHERE league=? AND season=? AND source='nflverse_weekly' "
        "AND (game_type='REG' OR game_type IS NULL) AND team IS NOT NULL",
        (LEAGUE, args.season)).fetchall()
    print("log rows: %d" % len(log_rows))

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    game_rows, report = build_game_rows(log_rows, totals, args.season, now)
    print("joined %d of %d log rows to published team-games; %d with null player_id "
          "(in team totals, no player row)" % (report["joined"], len(log_rows), report["no_player"]))
    for metric, r in report["metrics"].items():
        print("  %-10s copied=%d derived=%d unpublished=%d max_abs_err=%.9f" % (
            metric, r["copied"], r["derived"], r["unpublished"], r["max_err"]))
    print("per-game rows: %d" % len(game_rows))
    print("air yards: team passing total %d, assigned to logged players %d, unassigned %d (%.2f%%)" % (
        report["air_yards_team"], report["air_yards_team"] - report["air_yards_unassigned"],
        report["air_yards_unassigned"], 100 * report["air_yards_unassigned"] / report["air_yards_team"]))
    print("air yards: team-games where logged players exceed the team total: %d, e.g. %r" % (
        len(report["air_yards_negative"]), report["air_yards_negative"][:3]))

    season_out = season_rows(game_rows, totals, args.season, now)
    counts = {m: sum(1 for r in season_out if r[4] == m) for m in PER_GAME_METRICS}
    print("season rows: %s" % ", ".join("%s=%d" % kv for kv in counts.items()))
    if args.dry_run:
        print("dry run: nothing written")
        return 0
    write(con, args.season, totals, fetch_meta, game_rows, season_out)
    print("written: team totals %d, per-game %d, season %d" % (
        len(totals), len(game_rows), len(season_out)))
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
