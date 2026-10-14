#!/usr/bin/env python3
"""Build immutable canonical NHL games and strictly pregame rolling features.

The source DuckDB is opened read-only. Official NHL weekly schedule snapshots
are cached as compact JSONL evidence under this directory. Outputs are versioned
by content hash; existing files are never overwritten.
"""
import csv
import hashlib
import json
import os
import sys
import time
import urllib.request
from collections import Counter, defaultdict, deque
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
DB = os.environ.get("NHL_MODEL_DB", "/root/nhl_database_2025-26-playoffs.duckdb")
SCHEDULE_FILE = HERE / "official_nhl_schedule_evidence.jsonl"
CANONICAL_BASE = HERE / "canonical_games_v1"
FEATURES_BASE = HERE / "pregame_rolling_features_v1"
REPORT = HERE / "historical_data_integrity.md"
PACE_SECONDS = 0.20
USER_AGENT = "LegendaryPicksHistoricalAudit/1.0"

ALIAS_GROUPS = [
    {"PHX", "ARI"}, {"TBL", "T.B"}, {"NJD", "N.J"},
    {"LAK", "L.A"}, {"SJS", "S.J"},
]
ALIAS = {code: min(group) for group in ALIAS_GROUPS for code in group}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_immutable(base, suffix, data):
    tmp = base.with_suffix(base.suffix + ".tmp")
    tmp.write_bytes(data)
    digest = sha256(tmp)
    target = base.parent / f"{base.name}_{digest[:16]}.{suffix}"
    if target.exists():
        if sha256(target) != digest:
            raise RuntimeError(f"Content-address collision at {target}")
        tmp.unlink()
    else:
        os.replace(tmp, target)
    return target, digest


def collect_official_schedule(game_ranges):
    """Fetch each season in week-sized official NHL schedule requests."""
    cached = {}
    if SCHEDULE_FILE.exists():
        with SCHEDULE_FILE.open() as f:
            for line in f:
                if line.strip():
                    row = json.loads(line)
                    cached[row["game_id"]] = row
    wanted_ids = {gid for _, _, ids in game_ranges.values() for gid in ids}
    if wanted_ids.issubset(cached):
        return cached

    seen_requests = set()
    new_records = []
    for season, (start_int, end_int, game_ids) in sorted(game_ranges.items()):
        start = datetime.strptime(str(start_int), "%Y%m%d").date()
        end = datetime.strptime(str(end_int), "%Y%m%d").date()
        cursor = start
        while cursor <= end:
            url = f"https://api-web.nhle.com/v1/schedule/{cursor.isoformat()}"
            if url not in seen_requests:
                seen_requests.add(url)
                if not game_ids.issubset(cached):
                    last_error = None
                    for attempt in range(4):
                        try:
                            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                            with urllib.request.urlopen(req, timeout=30) as resp:
                                raw = resp.read()
                            payload = json.loads(raw)
                            break
                        except Exception as exc:
                            last_error = exc
                            if attempt < 3:
                                time.sleep(1.0 * (attempt + 1))
                    else:
                        raise RuntimeError(f"Official schedule request failed: {url}: {last_error}")
                    source_hash = hashlib.sha256(raw).hexdigest()
                    retrieved = datetime.now(timezone.utc).isoformat()
                    page_records = []
                    for week in payload.get("gameWeek", []):
                        for game in week.get("games", []):
                            gid = int(game["id"])
                            if gid in game_ids and gid not in cached:
                                record = {"game_id": gid, "schedule_date_request": cursor.isoformat(),
                                    "official_schedule_game_date": week.get("date"),
                                    "retrieved_at_utc": retrieved,
                                    "source_url": url, "source_response_sha256": source_hash,
                                    "game": game}
                                cached[gid] = record
                                new_records.append(record)
                                page_records.append(record)
                    if page_records:
                        mode = "a" if SCHEDULE_FILE.exists() else "w"
                        with SCHEDULE_FILE.open(mode) as f:
                            for record in page_records:
                                f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                            f.flush()
                    if new_records and len(new_records) % 250 < 30:
                        print(f"official games cached: {len(cached)}", flush=True)
                    time.sleep(PACE_SECONDS)
            cursor = date.fromordinal(cursor.toordinal() + 7)
    missing = wanted_ids - set(cached)
    if missing:
        raise RuntimeError(f"Official schedules missing {len(missing)} source games: {sorted(missing)[:20]}")
    return cached


def rows_as_csv(rows, columns):
    from io import StringIO
    buf = StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode()


def rolling_mean_before(history, target_day, key):
    prior = [x for x in history if x["date"] < target_day][-10:]
    values = [x[key] for x in prior if x.get(key) is not None]
    return sum(values) / len(values) if len(values) >= 5 else None


def main():
    con = duckdb.connect(DB, read_only=True)
    per_game = con.execute("""
        SELECT season, gameId, min(gameDate) AS game_date,
               count(DISTINCT team) AS team_count,
               max(CASE WHEN situation='all' THEN team END) AS team_placeholder
        FROM teams_gamelogs WHERE situation='all'
        GROUP BY season, gameId ORDER BY season, gameId
    """).fetchall()
    # One row per team/game, retaining all-strength outcomes and 5v5 chance stats.
    logs = con.execute("""
        SELECT a.season, a.gameId, a.gameDate, a.team, a.opposingTeam,
               a.home_or_away, a.goalsFor, a.goalsAgainst,
               a.xGoalsFor AS all_xgf, a.xGoalsAgainst AS all_xga,
               a.shotAttemptsFor AS all_attempts_for,
               a.shotAttemptsAgainst AS all_attempts_against,
               b.xGoalsFor AS xgf_5v5, b.xGoalsAgainst AS xga_5v5,
               b.scoreVenueAdjustedxGoalsFor AS svi_xgf_5v5,
               b.scoreVenueAdjustedxGoalsAgainst AS svi_xga_5v5,
               b.shotAttemptsFor AS attempts_for_5v5,
               b.shotAttemptsAgainst AS attempts_against_5v5,
               a.playoffGame
        FROM teams_gamelogs a
        LEFT JOIN teams_gamelogs b
          ON a.season=b.season AND a.gameId=b.gameId AND a.team=b.team
         AND b.situation='5on5'
        WHERE a.situation='all'
        ORDER BY a.season,a.gameDate,a.gameId,a.team
    """).fetchall()
    cols = [d[0] for d in con.description]
    logs = [dict(zip(cols, row)) for row in logs]
    con.close()
    by_game = defaultdict(list)
    game_ranges = {}
    for row in logs:
        season, gid = int(row["season"]), int(row["gameId"])
        by_game[(season, gid)].append(row)
    for (season, gid), team_rows in by_game.items():
        d = int(team_rows[0]["gameDate"])
        if season not in game_ranges:
            game_ranges[season] = [d, d, set()]
        game_ranges[season][0] = min(game_ranges[season][0], d)
        game_ranges[season][1] = max(game_ranges[season][1], d)
        game_ranges[season][2].add(gid)
    official = collect_official_schedule(game_ranges)

    canonical = []
    corrections = []
    tied_classifications = []
    for (season, gid), team_rows in sorted(by_game.items()):
        if len(team_rows) != 2:
            raise RuntimeError(f"Expected 2 team rows for {gid}; got {len(team_rows)}")
        src = official[gid]
        game = src["game"]
        home, away = game["homeTeam"], game["awayTeam"]
        home_code, away_code = home["abbrev"], away["abbrev"]
        normalized = {ALIAS.get(str(r["team"]), str(r["team"])): r for r in team_rows}
        hkey, akey = ALIAS.get(home_code, home_code), ALIAS.get(away_code, away_code)
        if hkey not in normalized or akey not in normalized:
            raise RuntimeError(f"Team identity mismatch game {gid}: log={list(normalized)}, official={home_code}/{away_code}")
        hr, ar = normalized[hkey], normalized[akey]
        raw_home_away = {str(r["team"]): r["home_or_away"] for r in team_rows}
        venue_error_home = hr["home_or_away"] != "HOME"
        venue_error_away = ar["home_or_away"] != "AWAY"
        if venue_error_home or venue_error_away:
            corrections.append({"game_id": gid, "season": season, "game_date": game.get("gameDate") or src["official_schedule_game_date"],
                "correction_type": "venue", "source_team_codes": f"{hr['team']}|{ar['team']}",
                "original_home_or_away": f"{hr['home_or_away']}|{ar['home_or_away']}",
                "canonical_home_away": f"{home_code}|{away_code}",
                "official_home": home_code, "official_away": away_code,
                "evidence_url": src["source_url"], "evidence_sha256": src["source_response_sha256"]})
        period = (game.get("gameOutcome") or {}).get("lastPeriodType") or (game.get("periodDescriptor") or {}).get("periodType")
        hs, aws = float(home["score"]), float(away["score"])
        winner = home_code if hs > aws else away_code if aws > hs else None
        ht, at = float(hr["goalsFor"]), float(ar["goalsFor"])
        tied_logs = ht == at
        if tied_logs:
            if winner is None:
                raise RuntimeError(f"Official NHL score does not settle tied team-log game {gid}")
            expected_home_model = int(hs) - int(period == "SO" and winner == home_code)
            expected_away_model = int(aws) - int(period == "SO" and winner == away_code)
            if period == "SO" and (int(ht), int(at)) == (expected_home_model, expected_away_model):
                tie_class = "shootout_tie_matches_team_log"
            elif period == "OT":
                tie_class = "overtime_game_but_team_log_tied"
            elif period == "SO":
                tie_class = "shootout_game_with_additional_team_log_score_conflict"
            else:
                tie_class = "regulation_game_with_team_log_tie_conflict"
            tied_classifications.append({"game_id": gid, "season": season, "game_date": game.get("gameDate") or src["official_schedule_game_date"],
                "team_log_tie_class": tie_class, "official_last_period_type": period,
                "official_home": home_code, "official_away": away_code,
                "home_team_log_goals": int(ht), "away_team_log_goals": int(at),
                "official_home_score": int(hs), "official_away_score": int(aws),
                "official_regulation_or_overtime_goals_home": expected_home_model,
                "official_regulation_or_overtime_goals_away": expected_away_model,
                "official_winner": winner, "official_loser": away_code if winner == home_code else home_code,
                "evidence_url": src["source_url"], "evidence_sha256": src["source_response_sha256"]})
        # Canonical scoring targets come from NHL records. For shootouts, remove
        # the official deciding goal so the goal target remains regulation/OT goals.
        model_home_goals = int(hs) - int(period == "SO" and winner == home_code)
        model_away_goals = int(aws) - int(period == "SO" and winner == away_code)
        if (int(ht), int(at)) != (model_home_goals, model_away_goals):
            corrections.append({"game_id": gid, "season": season, "game_date": game.get("gameDate") or src["official_schedule_game_date"],
                "correction_type": "team_log_score", "source_team_log_score": f"{home_code} {int(ht)} - {int(at)} {away_code}",
                "canonical_model_goal_targets": f"{home_code} {model_home_goals} - {model_away_goals} {away_code}",
                "official_final_including_shootout_decider": f"{home_code} {int(hs)} - {int(aws)} {away_code}",
                "last_period_type": period, "official_winner": winner,
                "evidence_url": src["source_url"], "evidence_sha256": src["source_response_sha256"]})
        source_metrics_eligible = (int(ht), int(at)) == (model_home_goals, model_away_goals)
        winner_label = int(winner == home_code)
        shot = con = None
        # Shot table labels are reconciled separately; canonical winner always follows NHL schedule.
        canonical.append({
            "game_id": gid, "season": season, "game_type": int(game["gameType"]),
            "game_date": src["official_schedule_game_date"], "start_time_utc": game.get("startTimeUTC"),
            "home_team": home_code, "away_team": away_code,
            "home_goals_model_target": model_home_goals, "away_goals_model_target": model_away_goals,
            "official_home_score": int(hs), "official_away_score": int(aws),
            "last_period_type": period, "official_home_winner": winner_label,
            "neutral_site": bool(game.get("neutralSite", False)),
            "team_log_venue_corrected": bool(venue_error_home or venue_error_away),
            "team_log_score_matches_canonical_target": source_metrics_eligible,
            "team_log_score_tied": bool(tied_logs),
            "source_team_home_code": str(hr["team"]), "source_team_away_code": str(ar["team"]),
            "source_schedule_url": src["source_url"], "source_schedule_sha256": src["source_response_sha256"],
            "source_retrieved_at_utc": src["retrieved_at_utc"],
            "home_xgf_5v5": hr["xgf_5v5"], "home_xga_5v5": hr["xga_5v5"],
            "home_svi_xgf_5v5": hr["svi_xgf_5v5"], "home_svi_xga_5v5": hr["svi_xga_5v5"],
            "home_attempts_for_5v5": hr["attempts_for_5v5"], "home_attempts_against_5v5": hr["attempts_against_5v5"],
            "away_xgf_5v5": ar["xgf_5v5"], "away_xga_5v5": ar["xga_5v5"],
            "away_svi_xgf_5v5": ar["svi_xgf_5v5"], "away_svi_xga_5v5": ar["svi_xga_5v5"],
            "away_attempts_for_5v5": ar["attempts_for_5v5"], "away_attempts_against_5v5": ar["attempts_against_5v5"],
        })
        if int(gid) in (2018020808, 2024020002):
            corrections.append({"game_id": gid, "season": season, "game_date": src["official_schedule_game_date"],
                "correction_type": "shot_homeTeamWon", "original_value": 0, "canonical_home_winner": winner_label,
                "official_home": home_code, "official_away": away_code,
                "official_home_score": int(hs), "official_away_score": int(aws),
                "evidence_url": src["source_url"], "evidence_sha256": src["source_response_sha256"]})
        if int(gid) == 2021021028:
            corrections.append({"game_id": gid, "season": season, "game_date": src["official_schedule_game_date"],
                "correction_type": "missing_shot_game_outcome", "original_value": "no shots-table game key",
                "canonical_situation": period, "canonical_winner": winner,
                "team_log_goals": f"{home_code} {int(ht)} - {int(at)} {away_code}",
                "official_final": f"{home_code} {int(hs)} - {int(aws)} {away_code}",
                "evidence_url": src["source_url"], "evidence_sha256": src["source_response_sha256"]})

    # Cross-season, strictly-before-game rolling features. Same-date games are excluded.
    team_game = {}
    for (season, gid), rows in by_game.items():
        off = official[gid]["game"]
        date_text = official[gid]["official_schedule_game_date"] if "official_schedule_game_date" in official[gid] else official[gid]["schedule_date_request"]
        # Schedule entry's exact day comes from the stored record.
        kickoff = off.get("startTimeUTC")
        game_day = datetime.fromisoformat(kickoff.replace("Z", "+00:00")).date() if kickoff else datetime.strptime(str(rows[0]["gameDate"]), "%Y%m%d").date()
        home = off["homeTeam"]["abbrev"]
        away = off["awayTeam"]["abbrev"]
        normalized = {ALIAS.get(str(r["team"]), str(r["team"])): r for r in rows}
        team_game[(gid, ALIAS.get(home,home))] = (game_day, normalized[ALIAS.get(home,home)])
        team_game[(gid, ALIAS.get(away,away))] = (game_day, normalized[ALIAS.get(away,away)])
    histories = defaultdict(list)
    feature_rows = []
    canonical_by_id = {r["game_id"]: r for r in canonical}
    for cg in sorted(canonical, key=lambda r: (r["game_date"], r["game_id"])):
        gid = cg["game_id"]
        day = datetime.strptime(cg["game_date"], "%Y-%m-%d").date()
        pair = []
        source_dates = []
        for side, team in (("home", cg["home_team"]), ("away", cg["away_team"])):
            hist = [x for x in histories[team] if x["date"] < day]
            last10 = hist[-10:]
            def avg(key):
                return rolling_mean_before(hist, day, key)
            row = {
                "team": team,
                "prior_games_available": len(hist),
                "prior_games_in_last10": len(last10),
                "rolling10_5v5_xgf": avg("xgf_5v5"),
                "rolling10_5v5_xga": avg("xga_5v5"),
                "rolling10_5v5_score_venue_xgf": avg("svi_xgf_5v5"),
                "rolling10_5v5_score_venue_xga": avg("svi_xga_5v5"),
                "rolling10_5v5_attempts_for": avg("attempts_for_5v5"),
                "rolling10_5v5_attempts_against": avg("attempts_against_5v5"),
                "rolling10_goals_for": avg("goals_for"),
                "rolling10_goals_against": avg("goals_against"),
                "days_since_previous_game": (day - hist[-1]["date"]).days if hist else None,
                "max_feature_source_date": max((x["date"] for x in last10), default=None),
                "feature_source_game_ids": [x["game_id"] for x in last10],
            }
            pair.append((side, row))
            source_dates.extend(x["date"] for x in last10)
        home_features = dict(pair[0][1])
        away_features = dict(pair[1][1])
        feature_rows.append({
            "game_id": gid, "season": cg["season"], "game_date": cg["game_date"],
            "home_team": cg["home_team"], "away_team": cg["away_team"],
            "home_win_label": cg["official_home_winner"],
            "home_goals_target": cg["home_goals_model_target"], "away_goals_target": cg["away_goals_model_target"],
            "home_days_rest": home_features["days_since_previous_game"],
            "away_days_rest": away_features["days_since_previous_game"],
            **{f"home_{k}": v for k,v in home_features.items() if k not in ("team","feature_source_game_ids")},
            **{f"away_{k}": v for k,v in away_features.items() if k not in ("team","feature_source_game_ids")},
            "home_feature_source_game_ids": ";".join(map(str,home_features["feature_source_game_ids"])),
            "away_feature_source_game_ids": ";".join(map(str,away_features["feature_source_game_ids"])),
            "required_features_complete": all(home_features[k] is not None and away_features[k] is not None for k in
                ("rolling10_5v5_xgf","rolling10_5v5_xga","rolling10_5v5_score_venue_xgf","rolling10_5v5_score_venue_xga","rolling10_5v5_attempts_for","rolling10_5v5_attempts_against","rolling10_goals_for","rolling10_goals_against")),
        })
        # Add current game to each team's history only after both teams' features were computed.
        for team in (cg["home_team"], cg["away_team"]):
            _, raw = team_game[(gid, ALIAS.get(team,team))]
            canonical_team_goals = (cg["home_goals_model_target"] if team == cg["home_team"]
                                    else cg["away_goals_model_target"])
            opponent_goals = (cg["away_goals_model_target"] if team == cg["home_team"]
                              else cg["home_goals_model_target"])
            metrics_ok = cg["team_log_score_matches_canonical_target"]
            histories[team].append({"game_id":gid,"date":day,
                "xgf_5v5":raw["xgf_5v5"] if metrics_ok else None,
                "xga_5v5":raw["xga_5v5"] if metrics_ok else None,
                "svi_xgf_5v5":raw["svi_xgf_5v5"] if metrics_ok else None,
                "svi_xga_5v5":raw["svi_xga_5v5"] if metrics_ok else None,
                "attempts_for_5v5":raw["attempts_for_5v5"] if metrics_ok else None,
                "attempts_against_5v5":raw["attempts_against_5v5"] if metrics_ok else None,
                "goals_for":canonical_team_goals,"goals_against":opponent_goals})

    # Leakage assertions: every feature source is a distinct, earlier-date game.
    byid = {x["game_id"]: x for x in feature_rows}
    for row in feature_rows:
        target_day = datetime.strptime(row["game_date"], "%Y-%m-%d").date()
        for prefix in ("home", "away"):
            ids = [int(v) for v in row[f"{prefix}_feature_source_game_ids"].split(";") if v]
            if row["game_id"] in ids:
                raise RuntimeError(f"Leakage: target game {row['game_id']} appears in its features")
            for source_id in ids:
                src = byid[source_id]
                if datetime.strptime(src["game_date"], "%Y-%m-%d").date() >= target_day:
                    raise RuntimeError(f"Leakage: non-prior source game {source_id} in {row['game_id']}")
    # Perturbation test: adding extreme current/future observations must leave
    # all pregame rolling values unchanged for sampled early/middle/late games.
    all_history_by_team = histories
    metric_columns = {
        "rolling10_5v5_xgf": "xgf_5v5", "rolling10_5v5_xga": "xga_5v5",
        "rolling10_5v5_score_venue_xgf": "svi_xgf_5v5",
        "rolling10_5v5_score_venue_xga": "svi_xga_5v5",
        "rolling10_5v5_attempts_for": "attempts_for_5v5",
        "rolling10_5v5_attempts_against": "attempts_against_5v5",
        "rolling10_goals_for": "goals_for", "rolling10_goals_against": "goals_against",
    }
    sample_rows = feature_rows[::max(1, len(feature_rows)//100)]
    for row in sample_rows:
        target_day = datetime.strptime(row["game_date"], "%Y-%m-%d").date()
        for side in ("home", "away"):
            team = row[f"{side}_team"]
            history = all_history_by_team[team]
            for feature, source_key in metric_columns.items():
                before = rolling_mean_before(history, target_day, source_key)
                poisoned = history + [{"game_id": -1, "date": target_day, source_key: 1e12},
                    {"game_id": -2, "date": date.fromordinal(target_day.toordinal()+1), source_key: -1e12}]
                after = rolling_mean_before(poisoned, target_day, source_key)
                actual = row[f"{side}_{feature}"]
                if before != after or actual != before:
                    raise RuntimeError(f"Temporal perturbation test failed for game {row['game_id']} {side} {feature}")

    canonical_cols = list(canonical[0])
    canonical_file, canonical_hash = write_immutable(CANONICAL_BASE, "csv", rows_as_csv(canonical, canonical_cols))
    feature_cols = list(feature_rows[0])
    feature_file, feature_hash = write_immutable(FEATURES_BASE, "csv", rows_as_csv(feature_rows, feature_cols))
    corrections_file = HERE / "historical_corrections.csv"
    correction_cols = sorted(set().union(*(r.keys() for r in corrections)))
    correction_file, correction_hash = write_immutable(HERE / "historical_corrections_v1", "csv", rows_as_csv(corrections, correction_cols))
    tied_file, tied_hash = write_immutable(HERE / "tied_team_log_classification_v1", "csv", rows_as_csv(tied_classifications, list(tied_classifications[0])))

    seasons = []
    seasons_count = Counter()
    for row in feature_rows:
        seasons_count[row["season"]] += 1
    for season in sorted(seasons_count):
        rows = [x for x in feature_rows if x["season"] == season]
        seasons.append({"season": season,"canonical_games":len(rows),
            "complete_required_features":sum(x["required_features_complete"] for x in rows),
            "trainable_games":sum(x["required_features_complete"] and x["home_win_label"] in (0,1) for x in rows)})
    summary = {
        "source_database_read_only": DB,
        "canonical_games": len(canonical), "venue_corrections": sum(x["correction_type"]=="venue" for x in corrections),
        "winner_label_corrections": sum(x["correction_type"]=="shot_homeTeamWon" for x in corrections),
        "team_log_score_corrections": sum(x["correction_type"]=="team_log_score" for x in corrections),
        "missing_shot_game_reconciled": sum(x["correction_type"]=="missing_shot_game_outcome" for x in corrections),
        "tied_team_log_games_classified": len(tied_classifications),
        "tied_situation_counts": dict(Counter(x["official_last_period_type"] for x in tied_classifications)),
        "tied_team_log_class_counts": dict(Counter(x["team_log_tie_class"] for x in tied_classifications)),
        "tied_official_winner_counts": dict(Counter(x["official_winner"] for x in tied_classifications)),
        "leakage_assertions": "passed: excluded same-date/current game; all declared source game dates precede target date",
        "feature_policy": "rolling last 10 prior games; at least 5 valid values; strict prior calendar date; cross-season history retained; exclude xG/shot observations from games whose team-log score conflicts with official canonical goals",
        "season_feature_coverage": seasons,
        "artifacts": {"canonical_games":{"path":canonical_file.name,"sha256":canonical_hash},
            "pregame_rolling_features":{"path":feature_file.name,"sha256":feature_hash},
            "corrections":{"path":correction_file.name,"sha256":correction_hash},
            "tied_classifications":{"path":tied_file.name,"sha256":tied_hash},
            "official_schedule_evidence":{"path":SCHEDULE_FILE.name,"sha256":sha256(SCHEDULE_FILE)}},
    }
    (HERE / "historical_integrity_summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    report_lines = [
        "# NHL historical canonicalization and feature readiness",
        "",
        "The separate modeling DuckDB was read-only throughout. No production database, market join, training run, or official backtest was performed.",
        "",
        "## Reconciliation results",
        "",
        f"- Canonical games: **{len(canonical):,}** across seasons {min(seasons_count)}–{max(seasons_count)}.",
        f"- Venue label corrections: **{summary['venue_corrections']}**. Each game ID, original venue label, NHL canonical venue, source URL, and response hash is in `{correction_file.name}`.",
        f"- Shot-table winner label corrections: **{summary['winner_label_corrections']}**. Both are resolved to the NHL home winner in the correction file.",
        f"- Team-log goal-target corrections to NHL records, including shootout-decider handling: **{summary['team_log_score_corrections']}**.",
        f"- Missing-shot game reconciled from NHL records: **{summary['missing_shot_game_reconciled']}**.",
        f"- Tied team-log records classified: **{len(tied_classifications):,}**, by official last period {json.dumps(summary['tied_situation_counts'], sort_keys=True)} and classification {json.dumps(summary['tied_team_log_class_counts'], sort_keys=True)}. Full game-level outcome and evidence are in `{tied_file.name}`.",
        "- Shootout awarded goal is retained in official final score/winner fields and excluded from the team-log goals model targets.",
        "",
        "The NHL schedule snapshot response hash and endpoint are carried on each canonical game. The complete cached game-level response evidence is in `official_nhl_schedule_evidence.jsonl`.",
        "",
        "## Pregame features",
        "",
        "Features are rolling means over up to the prior 10 games, requiring at least five non-missing values. Same-calendar-date games are excluded because final completion ordering is not available in the source logs. History carries across seasons.",
        "Included: 5-on-5 xGF/xGA, score- and venue-adjusted 5-on-5 xG for/against, 5-on-5 shot attempts for/against, all-situation goals for/against, and days since the previous game. For prior games whose team-log goals disagree with official score-derived regulation/OT goals, xG and shot observations are excluded from rolling averages; official goals remain the target/history value.",
        "",
        "Temporal checks passed: all declared source games precede the target game date; target game is absent from its own source IDs; and adding extreme current-day/future observations leaves sampled rolling features unchanged.",
        "",
        "## Feature coverage and trainable rows",
        "",
        "Trainable means both teams have all eight required rolling-stat features and an official binary winner label. It is a feature-readiness count only, not a backtest sample or claim of model performance.",
        "",
        "| Season | Canonical games | Complete features | Trainable games |",
        "| ---: | ---: | ---: | ---: |",
    ]
    for x in seasons:
        report_lines.append(f"| {x['season']} | {x['canonical_games']} | {x['complete_required_features']} | {x['trainable_games']} |")
    report_lines += ["", "## Immutable artifacts", "",
        f"- Canonical game table: `{canonical_file.name}` (SHA-256 `{canonical_hash}`).",
        f"- Pregame feature table: `{feature_file.name}` (SHA-256 `{feature_hash}`).",
        f"- All corrections: `{correction_file.name}` (SHA-256 `{correction_hash}`).",
        f"- Tied-game classifications: `{tied_file.name}` (SHA-256 `{tied_hash}`).",
        "- Content-addressed filenames are write-once; rebuilds create a new file if content changes."]
    (HERE / "canonicalization_discrepancy_report.md").write_text("\n".join(report_lines)+"\n")
    print(json.dumps(summary,indent=2))


if __name__ == "__main__":
    main()
