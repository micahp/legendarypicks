import collections
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_2026_penalty_overlay as audit

DB = audit.DB
OUT = "/tmp/slc-sack-context-2026-penalty-overlay.json"
METHODS = ("league", "offense_only", "defense_only", "matchup")


def strength_bin(distance):
    return audit.e0.pool_key(3, distance, 50)[1]


def main():
    result = {"database_sha256": "1a775208bc6e38763ef59c38a6cc79bda3636007feb8c6dc44f085f668341daa",
              "evaluations": {}, "notes": [
                  "Sack probability is scored only on observed dropbacks, conditioning on the observed pre-play down, distance, field cell, offense, and defense.",
                  "The 2026 penalty source overlay is joined by season, week, game_id, and play_id. Confirmed penalty and unknown-status rows are excluded from test scoring; confirmed penalty rows and unknown-status rows are excluded from corrected current-season adaptation.",
                  "The paired legacy-null-input scores use the same source-confirmed non-penalty test dropbacks but reproduce the old database behavior in which all current-season penalty fields were null."]}
    for year in (2026,):
        train_rows, pool, hist, excluded, raw_counts, yard_filters = audit.freeze_base(year)
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)
        test_rows = [dict(zip(audit.e1.COLUMNS, r)) for r in con.execute(
            f"SELECT {', '.join(audit.e1.COLUMNS)} FROM nfl_pbp WHERE season=? ORDER BY game_id,play_id", (year,))]
        sched = [dict(zip(("game_id", "season", "week", "gameday", "gametime"), r)) for r in con.execute(
            "SELECT game_id,season,week,gameday,gametime FROM nfl_schedule WHERE season=? AND game_type='REG'", (year,))]
        detail = {r[0]: (r[1], r[2]) for r in con.execute(
            "SELECT game_id,home_team,away_team FROM nfl_schedule WHERE season=? AND game_type='REG'", (year,))}
        con.close()
        penalty_mapping = audit.patch_2026_penalty_status(test_rows)
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
        legacy_score = collections.defaultdict(lambda: {m: audit.new_prob() for m in METHODS})
        coverage = collections.Counter()
        coverage.update({f'db_penalty_status_{k}':v for k,v in penalty_mapping.items()})
        coverage['test_unknown_penalty_status_excluded'] = excluded_test.get('penalty status unknown (excluded)', 0)
        coverage['test_penalty_tagged_excluded'] = excluded_test.get('penalty (not modelled)', 0)
        for ids, games in grouped.items():
            current_all = [r for gid in ids for r in current_by_game.get(gid, ())]
            current = [r for r in current_all if r.get('_penalty_status_known') is not False]
            legacy_current = [dict(r, penalty=None) for r in current_all]
            coverage['adaptation_rows_available'] += len(current_all)
            coverage['adaptation_unknown_status_excluded'] += sum(r.get('_penalty_status_known') is False for r in current_all)
            coverage['adaptation_known_status_used'] += len(current)
            coverage['adaptation_penalty_rows_excluded'] += sum(r.get('penalty') == 1 for r in current)
            team_games = collections.Counter()
            for gid in ids:
                home, away = detail[gid]
                team_games[home] += 1
                team_games[away] += 1
            table, _ = audit.tsa.adapt(hist, current, n0=4.0, team_games=dict(team_games)) if current else (hist, {})
            legacy_table, _ = audit.tsa.adapt(hist, legacy_current, n0=4.0, team_games=dict(team_games)) if legacy_current else (hist, {})
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
                    legacy_key = (key, 'legacy-null-status')
                    if legacy_key not in probability_cache:
                        probability_cache[legacy_key], _ = audit.conditional_probs(
                            pool.get(cell, []), 'dropback', row['posteam'], row['defteam'], cell, legacy_table)
                    legacy_probs = probability_cache[legacy_key]
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
                            if legacy_probs is not None:
                                audit.acc_bin(legacy_score[b][m], y, legacy_probs[m].get('sack', 0.0))
                    coverage["supported_dropbacks"] += 1
        result["evaluations"][str(year)] = {
            "coverage": dict(coverage),
            "sack_rate_by_context": {b: {m: audit.metric_bin(d) for m, d in ms.items()} for b, ms in score.items()},
            "same_cohort_penalty_ingestion_comparison": {
                'corrected_overlay': {b: {m: audit.metric_bin(d) for m, d in ms.items()} for b, ms in score.items()},
                'legacy_null_status_input': {b: {m: audit.metric_bin(d) for m, d in ms.items()} for b, ms in legacy_score.items()},
                'scoring_population': 'identical dropbacks with source penalty=0; source penalty=1 and null rows excluded'},
            "cutoff_games": sum(len(v) for v in grouped.values()),
            "unique_evidence_sets": len(grouped),
            "training_history_sha256": hist.manifest["sha256"],
            "earliest_cutoff": min((x.isoformat() for x in manifests.values()), default=None),
            "latest_cutoff": max((x.isoformat() for x in manifests.values()), default=None)}
    Path(OUT).write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps({y: {"coverage": result["evaluations"][str(y)]["coverage"],
                         "all": result["evaluations"][str(y)]["sack_rate_by_context"]["all"]}
                         for y in (2026,)}, sort_keys=True))


if __name__ == "__main__":
    main()
