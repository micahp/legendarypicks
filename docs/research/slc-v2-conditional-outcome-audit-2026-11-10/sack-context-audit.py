import collections
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit as audit

DB = audit.DB
OUT = "/tmp/slc-sack-context-audit.json"
METHODS = ("league", "offense_only", "defense_only", "matchup")


def strength_bin(distance):
    return audit.e0.pool_key(3, distance, 50)[1]


def main():
    result = {"database_sha256": "1a775208bc6e38763ef59c38a6cc79bda3636007feb8c6dc44f085f668341daa",
              "evaluations": {}, "notes": [
                  "Sack probability is scored only on observed dropbacks, conditioning on the observed pre-play down, distance, field cell, offense, and defense.",
                  "The 2026 test rows tagged as penalties in the pinned raw PBP parquet are excluded from scoring. The frozen 2026 adaptation still reflects the database as supplied to the run; its penalty column is null, so that adaptation can include tagged plays.",
                  "2025 is the clean primary holdout. 2026 is a sensitivity result because its adaptation database omits penalty flags."]}
    for year in (2025, 2026):
        train_rows, pool, hist, excluded, raw_counts, yard_filters = audit.freeze_base(year)
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)
        test_rows = [dict(zip(audit.e1.COLUMNS, r)) for r in con.execute(
            f"SELECT {', '.join(audit.e1.COLUMNS)} FROM nfl_pbp WHERE season=? ORDER BY game_id,play_id", (year,))]
        sched = [dict(zip(("game_id", "season", "week", "gameday", "gametime"), r)) for r in con.execute(
            "SELECT game_id,season,week,gameday,gametime FROM nfl_schedule WHERE season=? AND game_type='REG'", (year,))]
        detail = {r[0]: (r[1], r[2]) for r in con.execute(
            "SELECT game_id,home_team,away_team FROM nfl_schedule WHERE season=? AND game_type='REG'", (year,))}
        con.close()
        bygame, excluded_test = audit.classify_test_rows(test_rows)
        schedule = {r["game_id"]: r for r in sched}
        current_by_game = collections.defaultdict(list)
        for row in test_rows:
            current_by_game[row["game_id"]].append(row)
        grouped = collections.defaultdict(list)
        manifests = {}
        for gid in bygame:
            sr = schedule.get(gid)
            if not sr or not sr.get("gameday") or not sr.get("gametime"):
                continue
            cutoff = audit.tsa.cutoff_utc(audit.tsa.kickoff_utc(sr["gameday"], sr["gametime"]))
            ids, _ = audit.tsa.available_games(sched, year, cutoff, gid)
            key = tuple(ids)
            grouped[key].append(gid)
            manifests[key] = cutoff

        score = collections.defaultdict(lambda: {m: audit.new_prob() for m in METHODS})
        coverage = collections.Counter()
        for ids, games in grouped.items():
            current = [r for gid in ids for r in current_by_game.get(gid, ())]
            team_games = collections.Counter()
            for gid in ids:
                home, away = detail[gid]
                team_games[home] += 1
                team_games[away] += 1
            table, _ = audit.tsa.adapt(hist, current, n0=4.0, team_games=dict(team_games)) if current else (hist, {})
            probability_cache = {}
            for gid in games:
                for row, ev in bygame[gid]:
                    raw = audit.raw_extra.get((row["game_id"], int(float(row["play_id"]))), {})
                    if raw.get("penalty") == 1:
                        coverage["tagged_test_penalties_excluded"] += 1
                        continue
                    if audit.row_intent(ev, row) != "dropback":
                        continue
                    cell = audit.e0.pool_key(int(row["down"]), row["ydstogo"], row["yardline_100"])
                    key = (cell, row["posteam"], row["defteam"])
                    if key not in probability_cache:
                        probability_cache[key], _ = audit.conditional_probs(
                            pool.get(cell, []), "dropback", row["posteam"], row["defteam"], cell, table)
                    probs = probability_cache[key]
                    if probs is None:
                        coverage["unsupported"] += 1
                        continue
                    y = int(ev == "sack")
                    distance = audit.e0.pool_key(3, row["ydstogo"], row["yardline_100"])[1]
                    bins = ("all", f"offense:{row['posteam']}", f"defense:{row['defteam']}",
                            f"down:{row['down']}", f"distance:{distance}", f"down_distance:{row['down']}:{distance}")
                    for b in bins:
                        for m in METHODS:
                            audit.acc_bin(score[b][m], y, probs[m].get("sack", 0.0))
                    coverage["supported_dropbacks"] += 1
        result["evaluations"][str(year)] = {
            "coverage": dict(coverage),
            "sack_rate_by_context": {b: {m: audit.metric_bin(d) for m, d in ms.items()} for b, ms in score.items()},
            "cutoff_games": sum(len(v) for v in grouped.values()),
            "unique_evidence_sets": len(grouped),
            "training_history_sha256": hist.manifest["sha256"],
            "earliest_cutoff": min((x.isoformat() for x in manifests.values()), default=None),
            "latest_cutoff": max((x.isoformat() for x in manifests.values()), default=None)}
    Path(OUT).write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps({y: {"coverage": result["evaluations"][str(y)]["coverage"],
                         "all": result["evaluations"][str(y)]["sack_rate_by_context"]["all"]}
                      for y in (2025, 2026)}, sort_keys=True))


if __name__ == "__main__":
    main()
