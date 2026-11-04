#!/usr/bin/env python3
"""Reproducible NFL coaching, postseason, Seattle and forecast evaluation.

Signatures are tuples of recorded nflverse/LP fields. They are not play names,
exact designs, or concepts. All SQLite source reads are read-only; postseason
PBP comes from the pinned local nflverse Parquet snapshot.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import sqlite3
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path
from statistics import mean, median
from urllib.parse import quote

import duckdb


SEASONS = range(2022, 2027)
ALPHA = 0.5
HALF_LIFE_GAMES = 4.0
BOOTSTRAP_REPS = 2000
FAMILIES = ("run_pass", "action", "formation", "personnel")
PERIODS = ((2, 3, "weeks_2_3"), (4, 8, "weeks_4_8"),
           (9, 13, "weeks_9_13"), (14, 18, "weeks_14_18"))

REG_SQL = """
SELECT p.season,p.week,p.game_id,p.play_id,p.posteam,p.defteam,p.play_type,p.receiver_player_id,
       p.run_gap,p.run_location,p.pass_location,p.down,p.ydstogo,
       NULL score_differential,p.game_seconds_remaining,p.shotgun,p.no_huddle,
       (i.nflverse_game_id IS NOT NULL) participation_joined,
       i.offense_formation,i.offense_personnel,
       (c.nflverse_game_id IS NOT NULL) ftn_joined,
       c.is_motion,c.is_play_action
FROM nfl_pbp p
LEFT JOIN nfl_hist_participation i
  ON p.game_id=i.nflverse_game_id AND p.play_id=i.play_id
LEFT JOIN nfl_hist_ftn_charting c
  ON p.game_id=c.nflverse_game_id AND p.play_id=c.nflverse_play_id
WHERE p.season BETWEEN 2022 AND 2026 AND p.week BETWEEN 1 AND 18
  AND p.play_type IN ('run','pass') AND p.posteam IS NOT NULL
ORDER BY p.season,p.week,p.posteam,p.game_id,p.play_id
"""


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def readonly_db(path: Path) -> sqlite3.Connection:
    resolved = path.resolve()
    if not resolved.is_file():
        raise SystemExit(f"database not found: {resolved}")
    con = sqlite3.connect(f"file:{quote(str(resolved), safe='/')}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    if con.execute("PRAGMA query_only").fetchone()[0] != 1:
        raise RuntimeError("SQLite query_only could not be enabled")
    return con


def record_from_row(row: sqlite3.Row, season_type: str = "REG") -> dict:
    rec = dict(row)
    rec["season_type"] = season_type
    rec["participation_joined"] = bool(rec.get("participation_joined"))
    rec["ftn_joined"] = bool(rec.get("ftn_joined"))
    return rec


def join_postseason_rows(raw_rows: list[tuple], raw_names: list[str], db_path: Path) -> list[dict]:
    """Attach participation and FTN fields to raw playoff rows on exact keys."""
    lookup = sqlite3.connect(":memory:", uri=True)
    lookup.row_factory = sqlite3.Row
    try:
        lookup.execute("ATTACH DATABASE ? AS source", (f"file:{quote(str(db_path.resolve()), safe='/')}?mode=ro",))
        columns = ("season,week,game_id,play_id,posteam,defteam,play_type,receiver_player_id,"
                   "run_gap,run_location,pass_location,down,ydstogo,score_differential,"
                   "game_seconds_remaining,shotgun,no_huddle,home_team,away_team,home_coach,away_coach")
        lookup.execute(f"CREATE TABLE post_keys ({columns})")
        lookup.executemany("INSERT INTO post_keys VALUES (" + ",".join("?" for _ in raw_names) + ")", raw_rows)
        lookup.execute("CREATE UNIQUE INDEX post_key_idx ON post_keys(game_id,play_id)")
        join_sql = """SELECT p.*, (i.nflverse_game_id IS NOT NULL) participation_joined,
                              i.offense_formation,i.offense_personnel,
                              (c.nflverse_game_id IS NOT NULL) ftn_joined,
                              c.is_motion,c.is_play_action
                       FROM post_keys p
                       LEFT JOIN source.nfl_hist_participation i
                         ON p.game_id=i.nflverse_game_id AND p.play_id=i.play_id
                       LEFT JOIN source.nfl_hist_ftn_charting c
                         ON p.game_id=c.nflverse_game_id AND p.play_id=c.nflverse_play_id
                       ORDER BY p.season,p.week,p.posteam,p.game_id,p.play_id"""
        rows = [record_from_row(row, "POST") for row in lookup.execute(join_sql)]
    finally:
        lookup.close()
    if len(rows) != len(raw_rows):
        raise RuntimeError(f"postseason join cardinality changed: {len(raw_rows)} raw vs {len(rows)} joined")
    return rows


def load_regular(db_path: Path, raw_pbp_dir: Path) -> tuple[list[dict], int]:
    con = readonly_db(db_path)
    try:
        rows = [record_from_row(r) for r in con.execute(REG_SQL)]
    finally:
        con.close()
    keys = [(r["game_id"], int(r["play_id"])) for r in rows]
    if len(keys) != len(set(keys)):
        raise RuntimeError("regular PBP game/play keys are not unique")
    source_paths=[raw_pbp_dir/f"play_by_play_{year}.parquet" for year in range(2022,2026)]
    if any(not p.is_file() for p in source_paths):
        raise SystemExit("missing 2022-2025 regular PBP Parquet needed for score-state matching")
    raw_con=duckdb.connect(":memory:")
    try:
        states=raw_con.execute(
            """SELECT game_id,CAST(play_id AS BIGINT),score_differential
               FROM read_parquet(?) WHERE season_type='REG' AND season BETWEEN 2022 AND 2025
                 AND play_type IN ('run','pass') AND posteam IS NOT NULL""",
            [[str(p) for p in source_paths]],
        ).fetchall()
    finally:
        raw_con.close()
    score_by_key={(game,int(play)):diff for game,play,diff in states}
    matched=0
    for row in rows:
        key=(row["game_id"],int(row["play_id"]))
        if key in score_by_key:
            row["score_differential"]=score_by_key[key]
            matched+=1
    return rows,matched


def load_postseason(db_path: Path, raw_pbp_dir: Path) -> tuple[list[dict], dict]:
    paths = [raw_pbp_dir / f"play_by_play_{year}.parquet" for year in range(2022, 2026)]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise SystemExit("missing raw postseason PBP: " + ", ".join(missing))
    raw_con = duckdb.connect(":memory:")
    try:
        raw = raw_con.execute(
            """SELECT season,week,game_id,CAST(play_id AS BIGINT) play_id,posteam,defteam,
                      play_type,receiver_player_id,run_gap,run_location,pass_location,down,ydstogo,
                      score_differential,game_seconds_remaining,shotgun,no_huddle,
                      home_team,away_team,home_coach,away_coach
               FROM read_parquet(?) WHERE season_type='POST' AND season BETWEEN 2022 AND 2025
                 AND play_type IN ('run','pass') AND posteam IS NOT NULL
               ORDER BY season,week,posteam,game_id,play_id""",
            [[str(p) for p in paths]],
        ).fetchall()
        raw_names = [x[0] for x in raw_con.description]
    finally:
        raw_con.close()
    if not raw:
        raise RuntimeError("raw postseason query returned no run/pass rows")

    rows = join_postseason_rows(raw, raw_names, db_path)
    counts = Counter(r["season"] for r in rows)
    coverage = {}
    for season in sorted(counts):
        part = [r for r in rows if r["season"] == season]
        coverage[str(season)] = {
            "run_pass_rows": len(part),
            "participation_joined": sum(r["participation_joined"] for r in part),
            "ftn_joined": sum(r["ftn_joined"] for r in part),
            "games": len({r["game_id"] for r in part}),
        }
    return rows, coverage


def sig_action(row: dict) -> str:
    return canonical({k: row.get(k) for k in ("play_type", "run_gap", "run_location", "pass_location")})


def category(row: dict, family: str) -> str | None:
    if family == "run_pass":
        return row["play_type"]
    if family == "action":
        return sig_action(row)
    if family == "formation":
        return canonical(row.get("offense_formation")) if row["participation_joined"] else None
    if family == "personnel":
        if not row["participation_joined"]:
            return None
        raw=row.get("offense_personnel")
        counts={key:parse_personnel(raw,key) for key in ("RB","TE","WR")}
        return canonical(counts) if all(v is not None for v in counts.values()) else None
    raise ValueError(f"unknown family {family}")


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    columns = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def team_week_counts(rows: list[dict], family: str) -> dict:
    result = defaultdict(Counter)
    for row in rows:
        value = category(row, family)
        if value is None:
            continue
        key = (row["posteam"], int(row["season"]), int(row["week"]))
        result[key][value] += 1
    return result


def merge_counters(counters) -> Counter:
    out = Counter()
    for item in counters:
        out.update(item)
    return out


def total_variation(a: Counter, b: Counter) -> float | None:
    na, nb = sum(a.values()), sum(b.values())
    if not na or not nb:
        return None
    return 0.5 * sum(abs(a.get(k, 0) / na - b.get(k, 0) / nb) for k in a.keys() | b.keys())


def phase3_coaching(db_path: Path, reg: list[dict], out_dir: Path) -> dict:
    con = readonly_db(db_path)
    try:
        schedule = [dict(r) for r in con.execute(
            "SELECT game_id,season,week,home_team,away_team,home_coach,away_coach "
            "FROM nfl_schedule WHERE season BETWEEN 2022 AND 2026 AND game_type='REG'")]
    finally:
        con.close()
    game_hc = {}
    schedule_game_week={}
    for g in schedule:
        game_hc[(g["game_id"], g["home_team"])] = g["home_coach"]
        game_hc[(g["game_id"], g["away_team"])] = g["away_coach"]
        schedule_game_week[g["game_id"]]=g["week"]
    game_plays = Counter((r["season"], r["posteam"], r["game_id"]) for r in reg)
    hc_play_counts = defaultdict(Counter)
    observed_weeks = defaultdict(set)
    unmatched=[]
    for (season, team, game), n in game_plays.items():
        coach = game_hc.get((game, team))
        if coach:
            hc_play_counts[(season, team)][coach] += n
            if schedule_game_week.get(game) is not None:
                observed_weeks[(season, team)].add(int(schedule_game_week[game]))
        else:
            unmatched.append({"season":season,"team":team,"game_id":game,"run_pass_rows":n,
                              "week":schedule_game_week.get(game),"reason":"no matching non-null nfl_schedule coach field"})
    primary = {}
    team_rows = []
    for key in sorted(hc_play_counts):
        season, team = key
        coaches = hc_play_counts[key]
        coach = sorted(coaches, key=lambda x: (-coaches[x], x))[0]
        primary[key] = coach
        team_rows.append({
            "season": season, "team": team, "primary_head_coach": coach,
            "hc_distinct_in_observed_games": len(coaches),
            "head_coach_play_rows": coaches[coach],
            "all_hc_play_rows": sum(coaches.values()),
            "observed_regular_weeks": len(observed_weeks[key]),
            "weeks_observed": ",".join(map(str, sorted(observed_weeks[key]))),
            "schedule_source": "nfl_schedule.home_coach/away_coach joined by game_id and team",
        })

    by_team_season = defaultdict(list)
    for r in reg:
        by_team_season[(r["posteam"], int(r["season"]))].append(r)
    for tr in team_rows:
        team, season = tr["team"], tr["season"]
        previous = primary.get((season - 1, team))
        tr["previous_season_primary_hc"] = previous
        tr["same_primary_hc_as_previous_season"] = (
            None if previous is None else tr["primary_head_coach"] == previous
        )
        current_rows = by_team_season[(team, season)]
        current_actions = Counter(sig_action(r) for r in current_rows)
        prior_actions = Counter(sig_action(r) for r in by_team_season[(team, season - 1)])
        tr["prev_season_action_signature_unique_reuse"] = (
            sum(1 for x in set(current_actions) if x in prior_actions) / len(current_actions)
            if current_actions else None
        )
        tr["prev_season_action_signature_row_reuse"] = (
            sum(n for x, n in current_actions.items() if x in prior_actions) / sum(current_actions.values())
            if current_actions else None
        )
        tr["prev_season_action_distribution_tv"] = total_variation(current_actions, prior_actions)

    continuity_groups = defaultdict(list)
    for tr in team_rows:
        continuity = tr["same_primary_hc_as_previous_season"]
        if continuity is not None:
            continuity_groups[continuity].append(tr)
    group_rows = []
    for continuity, records in sorted(continuity_groups.items()):
        for metric in ("prev_season_action_signature_unique_reuse", "prev_season_action_signature_row_reuse", "prev_season_action_distribution_tv"):
            values = [r[metric] for r in records if r[metric] is not None]
            group_rows.append({
                "primary_hc_continuity": continuity,
                "team_seasons": len(records), "metric": metric,
                "mean": mean(values) if values else None,
                "median": median(values) if values else None,
            })

    moves = []
    coach_teams = defaultdict(dict)
    for (season, team), coach in primary.items():
        coach_teams[coach][season] = team
    for coach, timeline in sorted(coach_teams.items()):
        for season, team in sorted(timeline.items()):
            older = [(yr, tm) for yr, tm in timeline.items() if yr < season and tm != team]
            if older:
                prior_year, prior_team = max(older)
                prior = Counter(sig_action(r) for r in by_team_season[(prior_team, prior_year)])
                now = Counter(sig_action(r) for r in by_team_season[(team, season)])
                moves.append({
                    "head_coach": coach, "previous_observed_season": prior_year,
                    "previous_team": prior_team, "current_season": season,
                    "current_team": team, "prior_action_signature_unique_reuse":
                    sum(1 for x in set(now) if x in prior) / len(now) if now else None,
                    "interpretation": "raw action descriptor overlap only; not imported concepts",
                })
    write_csv(out_dir / "phase3_head_coach_team_season_2026-11-03.csv", team_rows)
    write_csv(out_dir / "phase3_hc_continuity_summary_2026-11-03.csv", group_rows)
    write_csv(out_dir / "phase3_hc_franchise_moves_2026-11-03.csv", moves)
    write_csv(out_dir / "phase3_hc_join_gaps_2026-11-03.csv", unmatched)
    all_coachable=sum(game_plays.values())
    joined_coachable=sum(sum(c.values()) for c in hc_play_counts.values())
    return {
        "schedule_regular_game_rows":len(schedule),
        "schedule_games_with_coach_fields": sum(bool(g["home_coach"] and g["away_coach"]) for g in schedule),
        "regular_run_pass_rows":all_coachable,"head_coach_joined_run_pass_rows":joined_coachable,
        "head_coach_run_pass_coverage":joined_coachable/all_coachable if all_coachable else None,
        "unmatched_team_game_rows":len(unmatched),"unmatched_run_pass_rows":sum(r["run_pass_rows"] for r in unmatched),
        "observed_team_seasons": len(team_rows),
        "team_seasons_with_in_season_hc_change": sum(r["hc_distinct_in_observed_games"] > 1 for r in team_rows),
        "team_seasons_with_same_primary_hc_as_prior_year": sum(r["same_primary_hc_as_previous_season"] is True for r in team_rows),
        "team_seasons_with_changed_primary_hc": sum(r["same_primary_hc_as_previous_season"] is False for r in team_rows),
        "continuity_summary": group_rows,
        "league_wide_oc_playcaller_coverage": "not available in these sources; not inferred from titles",
        "coach_move_rows": len(moves),
    }


def state_bucket(row: dict) -> tuple:
    down = row.get("down")
    ytg = row.get("ydstogo")
    diff = row.get("score_differential")
    d = int(down) if down is not None else "UNK"
    dist = "UNK" if ytg is None else ("short" if float(ytg) <= 3 else "medium" if float(ytg) <= 7 else "long")
    if diff is None:
        score = "UNK"
    elif diff <= -8:
        score = "trail_8plus"
    elif diff < 0:
        score = "trail_1_7"
    elif diff == 0:
        score = "tied"
    elif diff < 8:
        score = "lead_1_7"
    else:
        score = "lead_8plus"
    return d, dist, score


def controlled_context(row: dict) -> tuple | None:
    """Return an opponent/state cell only when every control is observed."""
    if (row.get("defteam") is None or row.get("down") is None
            or row.get("ydstogo") is None or row.get("score_differential") is None):
        return None
    return (int(row["season"]), row["posteam"], row["defteam"], *state_bucket(row))


def postseason_feature_value(row: dict, feature: str):
    if feature == "run_pass":
        return row.get("play_type")
    if feature == "formation":
        return row.get("offense_formation") if row.get("participation_joined") else None
    if feature == "personnel":
        if not row.get("participation_joined"):
            return None
        parsed = {role: parse_personnel(row.get("offense_personnel"), role)
                  for role in ("RB", "TE", "WR")}
        return canonical(parsed) if all(value is not None for value in parsed.values()) else None
    if feature == "motion":
        return bool(row["is_motion"]) if row.get("ftn_joined") and row.get("is_motion") is not None else None
    if feature == "shotgun":
        return bool(row["shotgun"]) if row.get("shotgun") is not None else None
    if feature == "play_action":
        if row.get("play_type") != "pass" or not row.get("ftn_joined"):
            return None
        return bool(row["is_play_action"]) if row.get("is_play_action") is not None else None
    raise ValueError(f"unknown postseason feature {feature}")


def context_adjusted_postseason(reg: list[dict], post: list[dict], out_dir: Path) -> dict:
    """Compare playoff attribute distributions with regular plays in same opponent/state cells."""
    features = ("run_pass", "personnel", "formation", "motion", "shotgun", "play_action")
    regular_cells = {feature: defaultdict(Counter) for feature in features}
    for row in reg:
        context = controlled_context(row)
        if context is None:
            continue
        for feature in features:
            value = postseason_feature_value(row, feature)
            if value is not None:
                regular_cells[feature][context][value] += 1

    summary_rows, category_rows = [], []
    pooled = {feature: {"eligible": 0, "matched": 0, "unsupported": 0, "incomplete": 0,
                        "unsupported_contexts": set(), "observed": Counter(), "expected": Counter()}
              for feature in features}
    for season in sorted({int(row["season"]) for row in post}):
        season_post = [row for row in post if int(row["season"]) == season]
        for feature in features:
            eligible = matched = incomplete = unsupported = 0
            unsupported_contexts = set()
            observed, expected = Counter(), Counter()
            for row in season_post:
                value = postseason_feature_value(row, feature)
                if value is None:
                    continue
                eligible += 1
                context = controlled_context(row)
                if context is None:
                    incomplete += 1
                    continue
                baseline = regular_cells[feature].get(context)
                if not baseline:
                    unsupported += 1
                    unsupported_contexts.add(context)
                    continue
                matched += 1
                observed[value] += 1
                baseline_n = sum(baseline.values())
                for category, count in baseline.items():
                    expected[category] += count / baseline_n

            if feature in ("motion", "shotgun", "play_action") and matched:
                playoff_rate = observed[True] / matched
                regular_rate = expected[True] / matched
                difference = playoff_rate - regular_rate
                tv = None
            elif matched:
                categories = observed.keys() | expected.keys()
                tv = 0.5 * sum(abs(observed[k] / matched - expected[k] / matched)
                               for k in categories)
                if feature == "run_pass":
                    playoff_rate = observed["run"] / matched
                    regular_rate = expected["run"] / matched
                    difference = playoff_rate - regular_rate
                else:
                    playoff_rate = regular_rate = difference = None
            else:
                playoff_rate = regular_rate = difference = tv = None

            summary_rows.append({
                "season": season, "feature": feature, "eligible_postseason_rows": eligible,
                "matched_postseason_rows": matched,
                "unsupported_context_rows": unsupported,
                "incomplete_control_rows": incomplete,
                "unsupported_unique_contexts": len(unsupported_contexts),
                "matched_share_of_eligible": matched / eligible if eligible else None,
                "postseason_positive_rate": playoff_rate,
                "regular_rate_standardized_to_matched_postseason_contexts": regular_rate,
                "rate_difference": difference,
                "distribution_total_variation": tv,
                "controls": "same season, offense, opponent, down, distance bucket, and score-margin bucket",
                "identity_scope": "recorded attribute; not play/concept identity",
            })
            for category in sorted(observed.keys() | expected.keys(), key=lambda value: canonical(value)):
                post_share = observed[category] / matched if matched else None
                regular_share = expected[category] / matched if matched else None
                category_rows.append({
                    "season": season, "feature": feature, "category": canonical(category),
                    "matched_postseason_rows": matched,
                    "postseason_share": post_share,
                    "regular_context_standardized_share": regular_share,
                    "difference": post_share - regular_share if matched else None,
                })
            aggregate = pooled[feature]
            aggregate["eligible"] += eligible
            aggregate["matched"] += matched
            aggregate["unsupported"] += unsupported
            aggregate["incomplete"] += incomplete
            aggregate["unsupported_contexts"].update(unsupported_contexts)
            aggregate["observed"].update(observed)
            aggregate["expected"].update(expected)

    pooled_rows = []
    for feature in features:
        values = pooled[feature]
        matched = values["matched"]
        observed, expected = values["observed"], values["expected"]
        if feature in ("motion", "shotgun", "play_action") and matched:
            playoff_rate = observed[True] / matched
            regular_rate = expected[True] / matched
            difference = playoff_rate - regular_rate
            tv = None
        elif matched:
            tv = 0.5 * sum(abs(observed[k] / matched - expected[k] / matched)
                           for k in observed.keys() | expected.keys())
            if feature == "run_pass":
                playoff_rate = observed["run"] / matched
                regular_rate = expected["run"] / matched
                difference = playoff_rate - regular_rate
            else:
                playoff_rate = regular_rate = difference = None
        else:
            playoff_rate = regular_rate = difference = tv = None
        pooled_rows.append({
            "season": "ALL", "feature": feature, "eligible_postseason_rows": values["eligible"],
            "matched_postseason_rows": matched, "unsupported_context_rows": values["unsupported"],
            "incomplete_control_rows": values["incomplete"],
            "unsupported_unique_contexts": len(values["unsupported_contexts"]),
            "matched_share_of_eligible": matched / values["eligible"] if values["eligible"] else None,
            "postseason_positive_rate": playoff_rate,
            "regular_rate_standardized_to_matched_postseason_contexts": regular_rate,
            "rate_difference": difference, "distribution_total_variation": tv,
            "controls": "same season, offense, opponent, down, distance bucket, and score-margin bucket",
            "identity_scope": "recorded attribute; not play/concept identity",
        })
    summary_rows.extend(pooled_rows)

    write_csv(out_dir / "phase4_postseason_context_adjusted_summary_2026-11-03.csv", summary_rows)
    write_csv(out_dir / "phase4_postseason_context_adjusted_categories_2026-11-03.csv", category_rows)
    return {
        "controls": "same season, offense, opponent, down, distance bucket, and score-margin bucket; incomplete controls and unsupported cells excluded",
        "summary_rows": summary_rows,
        "pooled_summary": pooled_rows,
        "features": list(features),
    }


def phase4_postseason(reg: list[dict], post: list[dict], out_dir: Path) -> dict:
    regular_groups = defaultdict(list)
    postseason_groups = defaultdict(list)
    for row in reg:
        regular_groups[(row["posteam"], int(row["season"]))].append(row)
    for row in post:
        postseason_groups[(row["posteam"], int(row["season"]))].append(row)
    # Include next-season catalog for reuse analysis (2026 is only the current DB cutoff).
    next_catalog = defaultdict(set)
    for r in reg:
        next_catalog[(r["posteam"], int(r["season"]))].add(sig_action(r))

    team_rows = []
    novel_detail_rows=[]
    all_novel, all_rows = 0, 0
    for (team, season), plays in sorted(postseason_groups.items()):
        regular = regular_groups[(team, season)]
        reg_action = Counter(sig_action(r) for r in regular)
        post_action = Counter(sig_action(r) for r in plays)
        unique_post = set(post_action)
        novel = unique_post - set(reg_action)
        novel_rows = sum(n for sig, n in post_action.items() if sig in novel)
        tv = total_variation(reg_action, post_action)
        next_seen = next_catalog[(team, season + 1)]
        reused_unique = unique_post & next_seen
        reused_rows = sum(n for sig, n in post_action.items() if sig in next_seen)
        part_rows = [r for r in plays if r["participation_joined"]]
        ftn_rows = [r for r in plays if r["ftn_joined"]]
        regular_part=[r for r in regular if r["participation_joined"]]
        regular_ftn=[r for r in regular if r["ftn_joined"]]
        def field_counter(items,field):
            return Counter(canonical(r.get(field)) for r in items)
        formation_reg=field_counter(regular_part,"offense_formation")
        formation_post=field_counter(part_rows,"offense_formation")
        personnel_reg=field_counter(regular_part,"offense_personnel")
        personnel_post=field_counter(part_rows,"offense_personnel")
        motion_reg=Counter(r.get("is_motion") for r in regular_ftn if r.get("is_motion") is not None)
        motion_post=Counter(r.get("is_motion") for r in ftn_rows if r.get("is_motion") is not None)
        pa_reg=Counter(r.get("is_play_action") for r in regular_ftn if r["play_type"]=="pass" and r.get("is_play_action") is not None)
        pa_post=Counter(r.get("is_play_action") for r in ftn_rows if r["play_type"]=="pass" and r.get("is_play_action") is not None)
        def novel_field(prior,current):
            new_keys=set(current)-set(prior)
            new_rows=sum(current[x] for x in new_keys)
            return len(new_keys),new_rows,new_rows/sum(current.values()) if sum(current.values()) else None
        for sig in sorted(novel):
            novel_detail_rows.append({"season":season,"team":team,"recorded_action_signature_json":sig,
                                      "postseason_rows":post_action[sig],"identity":"four-field raw PBP descriptor; not a named play/concept"})
        row = {
            "season": season,"team": team,"postseason_run_pass_rows": len(plays),
            "regular_run_pass_rows": len(regular),"unique_action_signatures_regular": len(reg_action),
            "unique_action_signatures_postseason": len(unique_post),
            "postseason_signatures_first_observed_vs_regular": len(novel),
            "postseason_rows_first_observed_vs_regular": novel_rows,
            "postseason_novel_row_share_vs_regular": novel_rows/len(plays) if plays else None,
            "action_distribution_total_variation_regular_vs_post": tv,
            "post_unique_signatures_reused_next_regular": len(reused_unique),
            "post_unique_signature_reuse_rate_next_regular": len(reused_unique)/len(unique_post) if unique_post else None,
            "post_rows_with_signature_reused_next_regular": reused_rows,
            "post_row_reuse_rate_next_regular": reused_rows/len(plays) if plays else None,
            "next_regular_cutoff": "weeks 1-8 only" if season == 2025 else "complete regular season",
            "participation_joined_rows": len(part_rows),"ftn_joined_rows": len(ftn_rows),
            "regular_participation_joined_rows":len(regular_part),
            "formation_unique_signatures_first_observed_post":novel_field(formation_reg,formation_post)[0],
            "formation_rows_first_observed_post":novel_field(formation_reg,formation_post)[1],
            "formation_novel_row_share_post":novel_field(formation_reg,formation_post)[2],
            "formation_usage_tv_regular_vs_post":total_variation(formation_reg,formation_post),
            "personnel_unique_signatures_first_observed_post":novel_field(personnel_reg,personnel_post)[0],
            "personnel_rows_first_observed_post":novel_field(personnel_reg,personnel_post)[1],
            "personnel_novel_row_share_post":novel_field(personnel_reg,personnel_post)[2],
            "personnel_usage_tv_regular_vs_post":total_variation(personnel_reg,personnel_post),
            "motion_share_regular_charted":sum(bool(v) for v,n in motion_reg.items() for _ in range(n))/sum(motion_reg.values()) if sum(motion_reg.values()) else None,
            "motion_share_post_charted":sum(bool(v) for v,n in motion_post.items() for _ in range(n))/sum(motion_post.values()) if sum(motion_post.values()) else None,
            "play_action_pass_share_regular_charted":sum(bool(v) for v,n in pa_reg.items() for _ in range(n))/sum(pa_reg.values()) if sum(pa_reg.values()) else None,
            "play_action_pass_share_post_charted":sum(bool(v) for v,n in pa_post.items() for _ in range(n))/sum(pa_post.values()) if sum(pa_post.values()) else None,
        }
        team_rows.append(row)
        all_rows += len(plays)
        all_novel += novel_rows
    write_csv(out_dir / "phase4_postseason_team_2026-11-03.csv", team_rows)
    write_csv(out_dir / "phase4_first_observed_action_signatures_2026-11-03.csv", novel_detail_rows)
    controlled = context_adjusted_postseason(reg, post, out_dir)
    run_context = next(row for row in controlled["pooled_summary"] if row["feature"] == "run_pass")
    context = {
        "context_keys": "same season × offense × defense opponent × down × distance bucket × score margin bucket",
        "distance_buckets": "<=3, 4-7, >7 yards to go; rows missing a required control are excluded",
        "score_buckets": "trail 1-7, trail 8+, tied, lead 1-7, lead 8+; rows missing score are excluded",
        "eligible_play_rows": run_context["eligible_postseason_rows"],
        "matched_play_rows": run_context["matched_postseason_rows"],
        "unsupported_context_rows": run_context["unsupported_context_rows"],
        "incomplete_control_rows": run_context["incomplete_control_rows"],
        "playoff_run_rate_in_context_matched_rows": run_context["postseason_positive_rate"],
        "regular_run_rate_standardized_to_playoff_contexts": run_context["regular_rate_standardized_to_matched_postseason_contexts"],
        "difference_observed_minus_standardized": run_context["rate_difference"],
        "interpretation": "empirical regular-season run-rate standardized to postseason rows with complete opponent/state support; descriptive, not causal",
    }
    return {
        "postseason_run_pass_rows": all_rows,
        "postseason_rows_first_observed_signature_vs_regular": all_novel,
        "postseason_novel_row_share_vs_regular": all_novel/all_rows if all_rows else None,
        "team_season_rows": len(team_rows),
        "mean_team_season_action_tv": mean(r["action_distribution_total_variation_regular_vs_post"] for r in team_rows if r["action_distribution_total_variation_regular_vs_post"] is not None),
        "mean_team_season_post_novel_row_share": mean(r["postseason_novel_row_share_vs_regular"] for r in team_rows if r["postseason_novel_row_share_vs_regular"] is not None),
        "context_adjustment": context,
        "controlled_attribute_comparison": controlled,
        "limits": ["four postseasons; selected teams and small per-team samples", "four-field action signatures are descriptors, not play identity or concept novelty", "2025-to-2026 reuse covers only 2026 weeks 1-8"],
    }


def parse_personnel(value: str | None, label: str) -> int | None:
    if not value:
        return None
    m = re.search(rf"(?:^|,\s*)(\d+)\s+{label}(?:,|$)", value)
    return int(m.group(1)) if m else None


def infer_team_offense_snaps(rows: list[dict]) -> dict:
    """Infer an integer team total from player snaps and rounded offense_pct values."""
    low_total, high_total = 1, None
    constraints = 0
    max_player_snaps = max((int(float(r.get("offense_snaps") or 0)) for r in rows), default=0)
    for row in rows:
        snaps = Decimal(str(row.get("offense_snaps") or 0))
        pct_value = row.get("offense_pct")
        if snaps <= 0 or pct_value is None:
            continue
        pct = Decimal(str(pct_value))
        if pct > 1:
            pct /= Decimal(100)
        if pct <= 0 or pct > 1 or snaps != snaps.to_integral_value():
            return {"total": None, "candidate_min": None, "candidate_max": None,
                    "constraints": constraints, "max_player_snaps": max_player_snaps,
                    "status": "invalid_percentage_or_snap_count"}
        # nflverse stores offense_pct as a proportion rounded to .01. Include
        # exact half-way endpoints conservatively because the source value may
        # have been rounded from binary floating point with either tie result.
        tolerance = Decimal("0.005")
        upper = pct + tolerance
        lower = pct - tolerance
        upper_ratio = snaps / upper
        lower_ratio = snaps / lower if lower > 0 else None
        this_min = int(upper_ratio.to_integral_value(rounding=ROUND_CEILING))
        this_max = (int(lower_ratio.to_integral_value(rounding=ROUND_FLOOR))
                    if lower_ratio is not None else None)
        low_total = max(low_total, this_min)
        if this_max is not None:
            high_total = this_max if high_total is None else min(high_total, this_max)
        constraints += 1
        if high_total is not None and low_total > high_total:
            return {"total": None, "candidate_min": low_total, "candidate_max": high_total,
                    "constraints": constraints, "max_player_snaps": max_player_snaps,
                    "status": "inconsistent_percentage_constraints"}
    if not constraints:
        return {"total": None, "candidate_min": None, "candidate_max": None,
                "constraints": 0, "max_player_snaps": max_player_snaps,
                "status": "no_positive_snap_percentage_constraints"}
    if high_total is None or low_total != high_total:
        return {"total": None, "candidate_min": low_total, "candidate_max": high_total,
                "constraints": constraints, "max_player_snaps": max_player_snaps,
                "status": "ambiguous_integer_denominator"}
    return {"total": low_total, "candidate_min": low_total, "candidate_max": high_total,
            "constraints": constraints, "max_player_snaps": max_player_snaps,
            "status": "resolved_from_rounded_offense_pct"}


def phase5_seahawks(reg: list[dict], post: list[dict], db_path: Path, out_dir: Path) -> dict:
    segments = [
        ("2024_REG", [r for r in reg if r["posteam"]=="SEA" and r["season"]==2024]),
        ("2025_REG", [r for r in reg if r["posteam"]=="SEA" and r["season"]==2025]),
        ("2025_REG_W1_8", [r for r in reg if r["posteam"]=="SEA" and r["season"]==2025 and 1<=r["week"]<=8]),
        ("2025_POST", [r for r in post if r["posteam"]=="SEA" and r["season"]==2025]),
        ("2026_REG_W1_8", [r for r in reg if r["posteam"]=="SEA" and r["season"]==2026]),
    ]
    segment_rows = []
    action_counts = {}
    action_examples = []
    for name, plays in segments:
        action = Counter(sig_action(r) for r in plays)
        action_counts[name] = action
        has_part = [r for r in plays if r["participation_joined"]]
        has_ftn = [r for r in plays if r["ftn_joined"]]
        observed_wr = [parse_personnel(r.get("offense_personnel"),"WR") for r in has_part]
        observed_te = [parse_personnel(r.get("offense_personnel"),"TE") for r in has_part]
        valid_wr = [x for x in observed_wr if x is not None]
        valid_te = [x for x in observed_te if x is not None]
        pa = [r["is_play_action"] for r in has_ftn if r["play_type"]=="pass" and r.get("is_play_action") is not None]
        motion = [r["is_motion"] for r in has_ftn if r.get("is_motion") is not None]
        segment_rows.append({
            "segment":name,"run_pass_rows":len(plays),"unique_action_signatures":len(action),
            "participation_joined_rows":len(has_part),"ftn_joined_rows":len(has_ftn),
            "3plus_wr_share_joined":sum(x>=3 for x in valid_wr)/len(valid_wr) if valid_wr else None,
            "2plus_te_share_joined":sum(x>=2 for x in valid_te)/len(valid_te) if valid_te else None,
            "play_action_share_charted":sum(bool(x) for x in pa)/len(pa) if pa else None,
            "play_action_pass_rows_charted":len(pa),
            "motion_share_charted":sum(bool(x) for x in motion)/len(motion) if motion else None,
            "shotgun_share_pbp":sum(bool(r.get("shotgun")) for r in plays if r.get("shotgun") is not None)/sum(r.get("shotgun") is not None for r in plays) if any(r.get("shotgun") is not None for r in plays) else None,
            "shotgun_rows_pbp":sum(r.get("shotgun") is not None for r in plays),
            "no_huddle_share_pbp":sum(bool(r.get("no_huddle")) for r in plays if r.get("no_huddle") is not None)/sum(r.get("no_huddle") is not None for r in plays) if any(r.get("no_huddle") is not None for r in plays) else None,
            "no_huddle_rows_pbp":sum(r.get("no_huddle") is not None for r in plays),
            "personnel_comparable":bool(has_part),
            "note":"2026 per-play participation/FTN is unavailable; do not compare blank metrics",
        })
    comparisons = (("2024_REG","2025_REG"),("2025_REG","2025_POST"),
                   ("2025_REG","2026_REG_W1_8"),("2025_REG_W1_8","2026_REG_W1_8"))
    for left,right in comparisons:
        ca,cb=action_counts[left],action_counts[right]
        common=set(ca)&set(cb)
        for sig in sorted(common,key=lambda x:(-min(ca[x],cb[x]),x))[:12]:
            action_examples.append({"left_segment":left,"right_segment":right,"recorded_action_signature_json":sig,"left_rows":ca[sig],"right_rows":cb[sig]})
    write_csv(out_dir / "phase5_seahawks_segment_summary_2026-11-03.csv", segment_rows)
    write_csv(out_dir / "phase5_seahawks_exact_action_matches_2026-11-03.csv", action_examples)

    # Player snap shares use source player-level game/week rows; they do not infer
    # who participated on any particular 2026 snap.
    con=readonly_db(db_path)
    try:
        hist=[dict(r) for r in con.execute(
            "SELECT season,game_type,week,game_id,pfr_player_id player_id,player,position,team,offense_snaps,offense_pct "
            "FROM nfl_hist_snap_counts WHERE team='SEA' AND season IN (2024,2025)")]
        current=[dict(r) for r in con.execute(
            "SELECT s.season,'REG' game_type,s.week,CAST(s.week AS TEXT) game_id,CAST(s.player_id AS TEXT) player_id,p.name player,p.position,"
            "s.team,s.off_snaps offense_snaps,s.off_pct offense_pct "
            "FROM nfl_snap_counts s LEFT JOIN players p ON p.id=s.player_id AND p.league='nfl' "
            "WHERE s.team='SEA' AND s.season=2026")]
    finally:
        con.close()
    con=readonly_db(db_path)
    try:
        player_names={r["nfl_gsis_id"]:{"name":r["name"],"position":r["position"]} for r in con.execute(
            "SELECT nfl_gsis_id,name,position FROM players WHERE league='nfl' AND nfl_gsis_id IS NOT NULL")}
    finally:
        con.close()
    target_rows=[]
    target_coverage=[]
    for name,plays in segments:
        passes=[r for r in plays if r["play_type"]=="pass"]
        with_target=Counter(str(r["receiver_player_id"]) for r in passes if r.get("receiver_player_id") is not None)
        target_n=sum(with_target.values())
        target_coverage.append({"segment":name,"pass_rows":len(passes),"rows_with_receiver_id":target_n,
                                "receiver_id_coverage":target_n/len(passes) if passes else None})
        for player_id,n in with_target.most_common():
            meta=player_names.get(player_id,{})
            target_rows.append({"segment":name,"receiver_gsis_id":player_id,"receiver_name":meta.get("name"),
                                "position":meta.get("position"),"targets_recorded":n,
                                "share_of_rows_with_receiver_id":n/target_n if target_n else None,
                                "share_of_pass_rows":n/len(passes) if passes else None,
                                "source":"nfl_pbp.receiver_player_id joined to LP players.nfl_gsis_id"})
    write_csv(out_dir / "phase5_seahawks_targets_2026-11-03.csv",target_rows)
    write_csv(out_dir / "phase5_seahawks_target_coverage_2026-11-03.csv",target_coverage)
    snap_rows=[]
    snap_audit_rows=[]
    for season,game_types,low_week,high_week,tag,source in [
        (2024,{"REG"},1,18,"2024_REG","nfl_hist_snap_counts"),
        (2025,{"REG"},1,18,"2025_REG","nfl_hist_snap_counts"),
        (2025,{"REG"},1,8,"2025_REG_W1_8","nfl_hist_snap_counts"),
        (2025,{"WC","DIV","CON","SB"},19,22,"2025_POST","nfl_hist_snap_counts"),
        (2026,{"REG"},1,8,"2026_REG_W1_8","nfl_snap_counts"),
    ]:
        subset=[r for r in (hist if season<2026 else current) if r["season"]==season and r["game_type"] in game_types and low_week<=r["week"]<=high_week]
        team_game_rows=defaultdict(list)
        per_player=defaultdict(lambda:{"snaps":0,"games":set(),"name":None,"position":None})
        for r in subset:
            game_key=str(r.get("game_id") or f"{r['season']}-W{r['week']}")
            team_game_rows[game_key].append(r)
            p=per_player[r["player_id"]]
            p["snaps"]+=r["offense_snaps"] or 0
            p["games"].add(game_key)
            p["name"] = r["player"] or p["name"]
            p["position"] = r["position"] or p["position"]
        game_denominators=[]
        for game_key,game_rows in sorted(team_game_rows.items()):
            inferred=infer_team_offense_snaps(game_rows)
            game_denominators.append(inferred["total"])
            snap_audit_rows.append({"segment":tag,"game_key":game_key,"week":game_rows[0]["week"],
                                    "player_rows":len(game_rows),"percentage_constraints":inferred["constraints"],
                                    "inferred_team_offense_snaps":inferred["total"],
                                    "candidate_min":inferred["candidate_min"],"candidate_max":inferred["candidate_max"],
                                    "max_individual_player_snaps":inferred["max_player_snaps"],
                                    "max_denominator_understatement":(inferred["total"]-inferred["max_player_snaps"])
                                        if inferred["total"] is not None else None,
                                    "resolution_status":inferred["status"],
                                    "method":"integer totals reconciled against offense_pct rounded to 0.01 share; half-way endpoints included conservatively"})
        denominators_resolved=sum(value is not None for value in game_denominators)
        total_team_snaps=(sum(game_denominators) if game_denominators and denominators_resolved==len(game_denominators) else None)
        for player_id,p in sorted(per_player.items(),key=lambda x:-x[1]["snaps"]):
            snap_rows.append({"segment":tag,"player_id":player_id,"player":p["name"],"position":p["position"],
                              "player_offense_snaps":p["snaps"],"team_offense_snaps":total_team_snaps,
                              "share_of_team_offense_snaps":p["snaps"]/total_team_snaps if total_team_snaps else None,
                              "games_with_row":len(p["games"]),"denominator_games":len(game_denominators),
                              "denominator_games_resolved":denominators_resolved,
                              "denominator_method":"offense_snaps reconciled against rounded offense_pct per game",
                              "source":source})
    write_csv(out_dir / "phase5_seahawks_player_snap_share_2026-11-03.csv", snap_rows)
    write_csv(out_dir / "phase5_seahawks_snap_denominator_audit_2026-11-03.csv", snap_audit_rows)
    return {
        "segments":segment_rows,
        "exact_action_matches_exported":len(action_examples),
        "player_snap_rows_exported":len(snap_rows),
        "snap_denominator_audit_rows":len(snap_audit_rows),
        "snap_denominator_unresolved_games":sum(r["resolution_status"] != "resolved_from_rounded_offense_pct" for r in snap_audit_rows),
        "target_coverage":target_coverage,
        "player_snap_sources":{"2024-25":"nfl_hist_snap_counts; denominator inferred per game from offense_snaps/offense_pct","2026":"nfl_snap_counts, through week 8; denominator inferred per team-week from off_snaps/off_pct"},
        "limits":["same raw action descriptor does not prove the same designed play", "2026 participation and FTN tags are absent", "aggregate snap counts do not identify player on each PBP snap"],
    }


def weighted_train_counter(game_keys: list, game_counter: dict, family: str, decay_at: int | None = None) -> Counter:
    out=Counter()
    for idx,key in enumerate(game_keys):
        weight=1.0 if decay_at is None else 2.0**(-(decay_at-idx)/HALF_LIFE_GAMES)
        for cat,n in game_counter[key][family].items():
            out[cat]+=weight*n
    return out


def predictive_distribution(train: Counter, family: str) -> dict:
    """Return a normalized categorical distribution plus an explicit unseen bucket."""
    n = sum(train.values())
    if family == "run_pass":
        categories = ("run", "pass")
        denom = n + ALPHA * len(categories)
        return {"known": {cat: (train.get(cat, 0) + ALPHA) / denom for cat in categories},
                "unseen": 0.0}
    k = len(train)
    denom = n + ALPHA * (k + 1)
    return {"known": {cat: (count + ALPHA) / denom for cat, count in train.items()},
            "unseen": ALPHA / denom}


def score_distribution(train: Counter, test: Counter, family: str) -> dict:
    n=sum(train.values())
    distribution=predictive_distribution(train,family)
    if family=="run_pass":
        probs=distribution["known"]
        loss=sum(count*(-math.log2(probs[cat])) for cat,count in test.items())
        cats=("run","pass")
        brier=sum(sum(count*((probs[pred]-(1 if actual==pred else 0))**2) for actual,count in test.items()) for pred in cats)
        return {"n":sum(test.values()),"loss":loss,"novel_n":0,"p_new":None,"novel_brier_sum":None,"multiclass_brier_sum":brier}
    p_new=distribution["unseen"]
    loss=novel_n=novel_brier=0.0
    test_n=sum(test.values())
    for cat,count in test.items():
        if cat in train:
            p=distribution["known"][cat]
        else:
            p=p_new
            novel_n+=count
        loss-=count*math.log2(p)
    known_n=test_n-novel_n
    novel_brier=known_n*p_new*p_new+novel_n*(1-p_new)*(1-p_new)
    return {"n":test_n,"loss":loss,"novel_n":novel_n,"p_new":p_new,"novel_brier_sum":novel_brier,"multiclass_brier_sum":None}


def phase6_source_coverage(reg: list[dict]) -> dict:
    target = [row for row in reg if 2023 <= int(row["season"]) <= 2026 and int(row["week"]) >= 2]
    base = len(target)
    part = [row for row in target if row.get("participation_joined")]
    ftn = [row for row in target if row.get("ftn_joined")]
    formation = [row for row in part if row.get("offense_formation") is not None]
    personnel = [row for row in part if all(parse_personnel(row.get("offense_personnel"), role) is not None
                                             for role in ("RB", "TE", "WR"))]
    motion = [row for row in ftn if row.get("is_motion") is not None]
    play_action = [row for row in ftn if row.get("play_type") == "pass" and row.get("is_play_action") is not None]
    def record(rows):
        return {"rows": len(rows), "share_of_walkforward_run_pass_targets": len(rows) / base if base else None}
    return {"walkforward_run_pass_target_rows": base,
            "participation_joined": record(part), "ftn_joined": record(ftn),
            "formation_nonnull": record(formation), "personnel_parseable_rb_te_wr": record(personnel),
            "motion_tag_nonnull": record(motion), "play_action_pass_tag_nonnull": record(play_action),
            "limitations": ["per-play participation and FTN charting are unavailable in 2026",
                            "formation source vocabulary changes between 2022 and 2023",
                            "personnel scores use parseable recorded RB/TE/WR counts; they are not play identity"]}


def build_phase6_records(reg: list[dict]):
    game_counter=defaultdict(lambda:{family:Counter() for family in FAMILIES})
    team_games=defaultdict(list)
    team_season_weeks=defaultdict(set)
    for row in reg:
        key=(row["posteam"],int(row["season"]),int(row["week"]),row["game_id"])
        team_games[(row["posteam"],int(row["season"]))].append(row)
        team_season_weeks[(row["posteam"],int(row["season"]))].add(int(row["week"]))
        for family in FAMILIES:
            cat=category(row,family)
            if cat is not None:
                game_counter[key][family][cat]+=1
    keys_by_team=defaultdict(list)
    for key in game_counter:
        team,season,week,game=key
        keys_by_team[team].append(key)
    for team in keys_by_team:
        keys_by_team[team].sort(key=lambda k:(k[1],k[2],k[3]))
    records=[]
    for team in sorted(keys_by_team):
        ordered=keys_by_team[team]
        global_index={k:i for i,k in enumerate(ordered)}
        by_season=defaultdict(list)
        for k in ordered:
            by_season[k[1]].append(k)
        for season in range(2023,2027):
            if season not in by_season:
                continue
            season_games=by_season[season]
            weeks=sorted({k[2] for k in season_games})
            for week in weeks:
                target_keys=[k for k in season_games if k[2]==week]
                if not target_keys or week == 1:
                    continue
                # Regular-season team schedule has one game per week; retain all keys if not.
                target={fam:merge_counters(game_counter[k][fam] for k in target_keys) for fam in FAMILIES}
                hist=[k for k in ordered if (k[1]<season or (k[1]==season and k[2]<week))]
                prior=[k for k in by_season.get(season-1,[])]
                expanding=[k for k in by_season.get(season,[]) if k[2]<week]
                last4=expanding[-4:]
                # Aggregate per family. Recompute adaptive weights for each family.
                models={
                    "previous_season_static":prior,
                    "current_season_expanding":expanding,
                    "last_4_team_games":last4,
                }
                for family in FAMILIES:
                    test=target[family]
                    if family in ("formation","personnel") and season>=2026:
                        continue
                    for model,train_keys in models.items():
                        if family=="formation" and season==2023 and model=="previous_season_static":
                            continue # 2022 formation vocabulary differs (e.g. SINGLEBACK vs UNDER CENTER).
                        train=merge_counters(game_counter[k][family] for k in train_keys)
                        sc=score_distribution(train,test,family)
                        records.append({"team":team,"season":season,"week":week,"family":family,"model":model,**sc})
                    if family=="formation" and season==2023:
                        continue # keep adaptive cross-season history inside the stable 2023+ encoding.
                    if hist:
                        decay_at=global_index[hist[-1]]
                        train=Counter()
                        adaptive_hist=[k for k in hist if family!="formation" or k[1]>=2023]
                        decay_at=global_index[adaptive_hist[-1]] if adaptive_hist else None
                        for k in adaptive_hist:
                            weight=2.0**(-(decay_at-global_index[k])/HALF_LIFE_GAMES)
                            for cat,n in game_counter[k][family].items():
                                train[cat]+=weight*n
                    else:
                        train=Counter()
                    sc=score_distribution(train,test,family)
                    records.append({"team":team,"season":season,"week":week,"family":family,"model":"adaptive_half_life_4_games",**sc})
    return records


def aggregate_phase6(records: list[dict], out_dir: Path) -> tuple[list[dict],list[dict]]:
    weekly=[]
    for row in records:
        n=row["n"]
        weekly.append({"team":row["team"],"season":row["season"],"week":row["week"],"family":row["family"],"model":row["model"],
                       "test_rows":n,"log_loss_bits":row["loss"]/n if n else None,
                       "realized_novelty_rate":row["novel_n"]/n if n and row["p_new"] is not None else None,
                       "mean_predicted_novelty_probability":row["p_new"],
                       "novelty_brier":row["novel_brier_sum"]/n if n and row["novel_brier_sum"] is not None else None,
                       "multiclass_brier":row["multiclass_brier_sum"]/n if n and row["multiclass_brier_sum"] is not None else None})
    write_csv(out_dir/"phase6_walkforward_weekly_2026-11-03.csv",weekly)
    aggregated=defaultdict(lambda:{"n":0,"loss":0.0,"novel_n":0.0,"novel_brier":0.0,"pred_novel":0.0,"novelty_n":0,"multiclass_brier":0.0,"multiclass_n":0})
    for row in records:
        period=next((name for lo,hi,name in PERIODS if lo<=row["week"]<=hi),"outside_defined_periods")
        k=(row["family"],row["model"],row["season"],period)
        a=aggregated[k]
        a["n"]+=row["n"]; a["loss"]+=row["loss"]
        if row["p_new"] is not None:
            a["novel_n"]+=row["novel_n"]
            a["novel_brier"]+=row["novel_brier_sum"]
            a["pred_novel"]+=row["p_new"]*row["n"]
            a["novelty_n"]+=row["n"]
        if row.get("multiclass_brier_sum") is not None:
            a["multiclass_brier"]+=row["multiclass_brier_sum"]
            a["multiclass_n"]+=row["n"]
    summary=[]
    models_by_family=defaultdict(set)
    rows_by_family_model_key=defaultdict(dict)
    for row in records:
        if row["n"] <= 0:
            continue
        family=row["family"]
        model=row["model"]
        key=(row["team"],row["season"],row["week"])
        models_by_family[family].add(model)
        if key in rows_by_family_model_key[(family,model)]:
            raise RuntimeError(f"duplicate Phase 6 evaluation group for {family} {model} {key}")
        rows_by_family_model_key[(family,model)][key]=row
    matched_by_family={}
    for family,models_for_family in models_by_family.items():
        model_keys=[set(rows_by_family_model_key[(family,model)]) for model in sorted(models_for_family)]
        common=set.intersection(*model_keys) if model_keys else set()
        models_sorted=sorted(models_for_family)
        for key in common:
            cohort_sizes={rows_by_family_model_key[(family,model)][key]["n"] for model in models_sorted}
            if len(cohort_sizes) != 1:
                raise RuntimeError(f"Phase 6 models do not share test-row counts for {family} {key}")
        matched_by_family[family]={"models":models_sorted,"keys":common,
                                   "test_rows":sum(rows_by_family_model_key[(family,models_sorted[0])][key]["n"]
                                                   for key in common) if common else 0}
    for (family,model,season,period),a in sorted(aggregated.items()):
        matched=matched_by_family.get(family,{"models":[],"keys":set(),"test_rows":0})
        matched_rows=[rows_by_family_model_key[(family,model)][key]
                      for key in matched["keys"] if key in rows_by_family_model_key[(family,model)]]
        matched_n=sum(row["n"] for row in matched_rows)
        matched_loss=sum(row["loss"] for row in matched_rows)
        summary.append({"family":family,"model":model,"season":season,"period":period,"test_rows":a["n"],
                        "log_loss_bits":a["loss"]/a["n"] if a["n"] else None,
                        "realized_novelty_rate":a["novel_n"]/a["novelty_n"] if a["novelty_n"] else None,
                        "mean_predicted_novelty_probability":a["pred_novel"]/a["novelty_n"] if a["novelty_n"] else None,
                        "novelty_brier":a["novel_brier"]/a["novelty_n"] if a["novelty_n"] else None,
                        "multiclass_brier":a["multiclass_brier"]/a["multiclass_n"] if a["multiclass_n"] else None,
                        "matched_population_test_rows":matched["test_rows"],
                        "matched_population_test_groups":len(matched["keys"]),
                        "matched_population_team_seasons":len({(key[0],key[1]) for key in matched["keys"]}),
                        "matched_population_log_loss_bits":matched_loss/matched_n if matched_n else None,
                        "matched_population_models":";".join(matched["models"])})
    write_csv(out_dir/"phase6_model_comparison_2026-11-03.csv",summary)
    matched_summary=[]
    for family,matched in sorted(matched_by_family.items()):
        for model in matched["models"]:
            rows=[rows_by_family_model_key[(family,model)][key] for key in matched["keys"]]
            n=sum(row["n"] for row in rows)
            loss=sum(row["loss"] for row in rows)
            matched_summary.append({"family":family,"model":model,
                                    "matched_test_rows":matched["test_rows"],
                                    "matched_team_week_groups":len(matched["keys"]),
                                    "matched_team_seasons":len({(key[0],key[1]) for key in matched["keys"]}),
                                    "matched_log_loss_bits":loss/n if n else None,
                                    "models_in_common_population":";".join(matched["models"])})
    write_csv(out_dir/"phase6_matched_model_comparison_2026-11-03.csv",matched_summary)
    # Paired franchise-cluster bootstrap on the same team-week test population.
    by_family_model_team=defaultdict(lambda:defaultdict(lambda:[0.0,0]))
    for family,matched in matched_by_family.items():
        for model in matched["models"]:
            for key in matched["keys"]:
                row=rows_by_family_model_key[(family,model)][key]
                cluster=(key[0],key[1])
                by_family_model_team[(family,model)][cluster][0]+=row["loss"]
                by_family_model_team[(family,model)][cluster][1]+=row["n"]
    ci_rows=[]
    rng=random.Random(20261103)
    for family,matched in sorted(matched_by_family.items()):
        base=by_family_model_team[(family,"current_season_expanding")]
        for model in matched["models"]:
            if model=="current_season_expanding" or not by_family_model_team[(family,model)]:
                continue
            other=by_family_model_team[(family,model)]
            paired=[k for k in other if k in base and other[k][1]>0 and base[k][1]>0]
            on=sum(other[k][0] for k in paired); od=sum(other[k][1] for k in paired)
            bn=sum(base[k][0] for k in paired); bd=sum(base[k][1] for k in paired)
            point=on/od-bn/bd if od and bd else None
            paired_teams=sorted({k[0] for k in paired})
            draws=[]
            for _ in range(BOOTSTRAP_REPS):
                chosen=[rng.choice(paired_teams) for _ in paired_teams] if paired_teams else []
                on=odraw=bn=bdraw=0.0
                for team in chosen:
                    team_pairs=[k for k in paired if k[0]==team]
                    for k in team_pairs:
                        o=other[k]; b=base[k]
                        on+=o[0]; odraw+=o[1]; bn+=b[0]; bdraw+=b[1]
                if odraw and bdraw: draws.append(on/odraw-bn/bdraw)
            draws.sort()
            ci_rows.append({"family":family,"model":model,"reference_model":"current_season_expanding",
                            "log_loss_difference_bits_per_play":point,"paired_team_seasons":len(paired),"franchise_clusters":len(paired_teams),"cluster_bootstrap_reps":len(draws),
                            "franchise_cluster_95_low":draws[int(.025*len(draws))] if draws else None,
                            "franchise_cluster_95_high":draws[min(len(draws)-1,int(.975*len(draws)))] if draws else None,
                            "matched_test_rows":matched["test_rows"],
                            "matched_team_week_groups":len(matched["keys"]),
                            "models_in_common_population":";".join(matched["models"]),
                            "interpretation":"positive means model has higher/worse log loss than reference; all models score the same matched team-week rows"})
    write_csv(out_dir/"phase6_franchise_bootstrap_2026-11-03.csv",ci_rows)
    # Novelty reliability table; each probability is an explicit unknown-signature bucket.
    bins=defaultdict(lambda:{"n":0,"pred":0.0,"observed":0.0})
    for row in records:
        if row["p_new"] is None or not row["n"]:
            continue
        b=min(9,int(row["p_new"]*10))
        x=bins[(row["family"],row["model"],b)]
        x["n"]+=row["n"]
        x["pred"]+=row["p_new"]*row["n"]
        x["observed"]+=row["novel_n"]
    calibration=[]
    for (family,model,b),x in sorted(bins.items()):
        calibration.append({"family":family,"model":model,"predicted_novelty_bin":f"{b/10:.1f}-{(b+1)/10:.1f}",
                            "test_rows":x["n"],"mean_predicted_novelty":x["pred"]/x["n"],
                            "observed_novelty_rate":x["observed"]/x["n"],
                            "absolute_calibration_gap":abs(x["pred"]/x["n"]-x["observed"]/x["n"])})
    write_csv(out_dir/"phase6_novelty_calibration_2026-11-03.csv",calibration)
    return summary,ci_rows


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db",type=Path,required=True)
    parser.add_argument("--raw-pbp-dir",type=Path,required=True)
    parser.add_argument("--out-dir",type=Path,required=True)
    args=parser.parse_args()
    args.out_dir.mkdir(parents=True,exist_ok=True)
    reg,score_diff_joined=load_regular(args.db,args.raw_pbp_dir)
    post,post_coverage=load_postseason(args.db,args.raw_pbp_dir)
    phase3=phase3_coaching(args.db,reg,args.out_dir)
    phase4=phase4_postseason(reg,post,args.out_dir)
    phase5=phase5_seahawks(reg,post,args.db,args.out_dir)
    scores=build_phase6_records(reg)
    comparison,bootstrap=aggregate_phase6(scores,args.out_dir)
    phase6_coverage=phase6_source_coverage(reg)
    manifest={
        "inventory_date":"2026-11-03",
        "inputs":{"dev_db":str(args.db.resolve()),"postseason_raw_pbp_dir":str(args.raw_pbp_dir.resolve()),
                  "regular_run_pass_rows":len(reg),"postseason_run_pass_rows":len(post),
                  "regular_score_differential_exact_joined_rows_2022_25":score_diff_joined,
                  "regular_seasons":{str(y):sum(r["season"]==y for r in reg) for y in SEASONS},
                  "postseason_join_coverage":post_coverage},
        "phase3_coaching":phase3,"phase4_postseason":phase4,"phase5_seahawks":phase5,
        "phase6":{"walkforward_rows":len(scores),"comparison_rows":len(comparison),"bootstrap_rows":len(bootstrap),
                  "source_coverage":phase6_coverage,
                  "models":["previous_season_static","current_season_expanding","last_4_team_games","adaptive_half_life_4_games"],
        "adaptive_half_life_team_games":HALF_LIFE_GAMES,"dirichlet_alpha":ALPHA,
                  "confidence_interval":"2,000 franchise-cluster bootstrap resamples; fixed seed 20261103",
                  "formation_personnel_evaluation_seasons":"2023-2025 only; 2026 per-play participation unavailable; raw formation cross-season scoring starts in 2024 because 2022 uses a different source vocabulary; personnel is normalized to recorded RB/TE/WR counts",
                  "closed_loop_workload":"not evaluated; no model-code changes, and observed snaps are not a counterfactual simulation"},
        "identity_policy":"all action/presentation signatures are recorded-field identities only; no exact play or concept labels",
    }
    path=args.out_dir/"phase3_6_analysis_dev_2026-11-03.json"
    path.write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"manifest":str(path),"regular_rows":len(reg),"postseason_rows":len(post),
                      "phase3_team_seasons":phase3["observed_team_seasons"],
                      "phase4_team_season_rows":phase4["team_season_rows"],
                      "phase4_context_adjusted_rows":len(phase4["controlled_attribute_comparison"]["summary_rows"]),
                      "phase5_snap_denominator_unresolved_games":phase5["snap_denominator_unresolved_games"],
                      "phase6_scored_group_rows":len(scores)},indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
