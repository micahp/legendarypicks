#!/usr/bin/env python3
"""NHL event-data coverage audit: how much of a game can we reconstruct?

Answers, per start season, on the pinned official-outcome frame's stratified
sample: shots and locations, shot types, period scoring, strength states,
penalties, player deployment, shifts — plus ID reconciliation against the
official label foundation and the contradictions those checks surface.

Read-only. Writes only inside this directory. Fits nothing.

Contradiction checks compare two independent instruments (official label vs
event feed). A mismatch is reported as a mismatch, never silently reconciled:
the audit's job is to say where the feed and the labels disagree before anyone
builds a simulator on top of either.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABELS = HERE.parent / "official-outcome-backfill-2026-10-20"
CACHE = Path("/root/lp-data/nhl-event-data-audit-2026-10-20/raw")

SHOT_TYPES = {"shot-on-goal", "goal", "missed-shot", "blocked-shot"}
SOG_TYPES = {"shot-on-goal", "goal"}
COORD_LIMIT_X, COORD_LIMIT_Y = 100.0, 42.5
TOI_TOLERANCE_S = 30
TOI_CONTRADICTION_S = 60


# ---------------------------------------------------------------------------
# payload access
# ---------------------------------------------------------------------------
def load_payload(gid: str, kind: str) -> dict | None:
    p = CACHE / kind / f"{gid}.json.gz"
    if not p.exists():
        return None
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def mmss(value) -> int | None:
    if not isinstance(value, str) or ":" not in value:
        return None
    try:
        m, s = value.split(":")
        return int(m) * 60 + int(s)
    except ValueError:
        return None


def strength_class(code) -> str | None:
    """`situationCode` is [awayGoalie, awaySkaters, homeSkaters, homeGoalie]."""
    if not isinstance(code, str) or len(code) != 4 or not code.isdigit():
        return None
    ag, ask, hsk, hg = (int(c) for c in code)
    if ag == 0 and hg == 1:
        return "EN_away_pulled"
    if hg == 0 and ag == 1:
        return "EN_home_pulled"
    if ag == 0 and hg == 0:
        return "both_pulled"
    if ask == hsk:
        return f"EV_{ask}v{hsk}"
    if ask > hsk:
        return f"PP_away_{ask}v{hsk}"
    return f"PP_home_{hsk}v{ask}"


# ---------------------------------------------------------------------------
# label foundation
# ---------------------------------------------------------------------------
def load_labels() -> tuple[dict, dict, dict]:
    sides: dict[str, dict] = defaultdict(dict)
    with (LABELS / "official_game_sides.csv").open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            sides[r["game_id"]][r["side"]] = r

    skaters: dict[str, dict[int, dict]] = defaultdict(dict)
    with (LABELS / "official_skater_outcomes.csv").open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                skaters[r["game_id"]][int(r["player_id"])] = r
            except ValueError:
                continue

    goalies: dict[str, dict[int, dict]] = defaultdict(dict)
    with (LABELS / "official_goalie_outcomes.csv").open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                goalies[r["game_id"]][int(r["player_id"])] = r
            except ValueError:
                continue
    return sides, skaters, goalies


# ---------------------------------------------------------------------------
# per-game audit
# ---------------------------------------------------------------------------
def audit_game(gid: str, sample_row: dict, sides, skaters, goalies) -> tuple[dict, list]:
    pbp = load_payload(gid, "pbp")
    shifts = load_payload(gid, "shifts")
    m: dict = {"game_id": gid, "season": int(sample_row["season"]),
               "game_date": sample_row["game_date"], "pbp": pbp is not None,
               "shifts": shifts is not None}
    bad: list[dict] = []

    def flag(kind: str, detail: str) -> None:
        bad.append({"game_id": gid, "season": m["season"], "issue": kind, "detail": detail})

    home_side = sides.get(gid, {}).get("home")
    away_side = sides.get(gid, {}).get("away")
    if not pbp:
        flag("PBP_MISSING", "no play-by-play body")
        return m, bad

    plays = pbp["plays"]
    events = [p for p in plays if p.get("typeDescKey")]
    m["events"] = len(plays)
    m["periods"] = len({p["periodDescriptor"]["number"] for p in plays
                        if p.get("periodDescriptor")})
    m["has_shootout"] = any(p.get("periodDescriptor", {}).get("periodType") == "SO" for p in plays)

    shots = [p for p in events if p.get("typeDescKey") in SHOT_TYPES]
    sog = [p for p in events if p.get("typeDescKey") in SOG_TYPES]
    goals = [p for p in events if p.get("typeDescKey") == "goal"]
    pens = [p for p in events if p.get("typeDescKey") == "penalty"]

    def d(p):
        return p.get("details") or {}

    m["shot_events"] = len(shots)
    m["shot_events_with_xy"] = sum(1 for p in shots
                                   if d(p).get("xCoord") is not None and d(p).get("yCoord") is not None)
    m["shot_xy_out_of_box"] = sum(
        1 for p in shots
        if d(p).get("xCoord") is not None and d(p).get("yCoord") is not None
        and (abs(float(d(p)["xCoord"])) > COORD_LIMIT_X or abs(float(d(p)["yCoord"])) > COORD_LIMIT_Y))
    m["shot_events_with_type"] = sum(1 for p in shots if d(p).get("shotType"))
    unblocked = [p for p in shots if p.get("typeDescKey") != "blocked-shot"]
    m["unblocked_shot_events"] = len(unblocked)
    m["unblocked_with_type"] = sum(1 for p in unblocked if d(p).get("shotType"))
    m["blocked_shot_events"] = sum(1 for p in shots if p.get("typeDescKey") == "blocked-shot")
    m["blocked_with_type"] = sum(1 for p in shots
                                 if p.get("typeDescKey") == "blocked-shot" and d(p).get("shotType"))
    m["shot_type_vocabulary"] = sorted({d(p).get("shotType") for p in shots if d(p).get("shotType")})

    # period scoring
    by_period = Counter()
    for p in goals:
        by_period[int(p["periodDescriptor"]["number"])] += 1
    m["goals_in_pbp"] = len(goals)
    m["goals_by_period"] = json.dumps({str(k): v for k, v in sorted(by_period.items())})

    # strength states over every event that carries one (shots/goals/hits/...)
    with_state = [p for p in events if p.get("situationCode")]
    parsable = [p for p in with_state if strength_class(p["situationCode"])]
    m["events_with_situation"] = len(with_state)
    m["events_with_parsable_situation"] = len(parsable)
    m["states_seen"] = sorted({strength_class(p["situationCode"]) for p in parsable})
    goal_states = Counter(strength_class(p["situationCode"]) for p in goals if p.get("situationCode"))
    m["goal_states"] = json.dumps({k: v for k, v in sorted(goal_states.items())})
    m["goals_with_parsable_state"] = sum(goal_states.values())

    # penalties
    m["penalty_events"] = len(pens)
    m["penalties_with_duration"] = sum(1 for p in pens if d(p).get("duration"))
    m["penalties_with_desc"] = sum(1 for p in pens if d(p).get("descKey"))
    m["penalties_with_player"] = sum(1 for p in pens if d(p).get("committedByPlayerId"))
    m["penalty_minutes"] = sum(int(d(p).get("duration") or 0) for p in pens)

    # team-level SOG / goals from the feed, all periods and regulation-only.
    # Shootout attempts are recorded as shot/goal events but are NOT part of the
    # official SOG total, and the official final score credits only the shootout
    # winner with +1. Both counts are therefore kept and compared separately.
    team_of = {}
    if pbp.get("homeTeam") and pbp.get("awayTeam"):
        team_of[int(pbp["homeTeam"]["id"])] = "home"
        team_of[int(pbp["awayTeam"]["id"])] = "away"

    def by_team(events, exclude_so):
        c = Counter()
        for p in events:
            if exclude_so and p.get("periodDescriptor", {}).get("periodType") == "SO":
                continue
            side = team_of.get(int(d(p).get("eventOwnerTeamId") or -1))
            if side:
                c[side] += 1
        return c

    sog_all, sog_reg = by_team(sog, False), by_team(sog, True)
    goal_all, goal_reg = by_team(goals, False), by_team(goals, True)
    for side in ("home", "away"):
        m[f"sog_{side}_pbp"] = sog_all.get(side, 0)
        m[f"sog_{side}_pbp_reg"] = sog_reg.get(side, 0)
        m[f"goals_{side}_pbp"] = goal_all.get(side, 0)
        m[f"goals_{side}_pbp_reg"] = goal_reg.get(side, 0)
    m["shootout_goals_in_feed"] = sum(goal_all.values()) - sum(goal_reg.values())
    m["shootout_shots_in_feed"] = sum(sog_all.values()) - sum(sog_reg.values())

    # contradictions against the official labels. Regulation-only counts are the
    # comparable quantity. For a shootout game the official final score credits
    # the winner with exactly +1, which the regulation goal events cannot contain
    # — that bonus is applied before comparing, and recorded.
    if home_side and away_side:
        official = {}
        for side, lab in (("home", home_side), ("away", away_side)):
            try:
                official[side] = int(lab["canonical_score"] or lab["score"])
            except (KeyError, ValueError):
                official[side] = None
        if all(v is not None for v in official.values()):
            winner = "home" if official["home"] > official["away"] else "away"
            bonus = (1 if m.get("has_shootout") else 0)
            for side, lab in (("home", home_side), ("away", away_side)):
                m[f"goals_{side}_official"] = official[side]
                so_bonus = bonus if side == winner else 0
                m[f"goals_{side}_pbp_adj"] = m[f"goals_{side}_pbp_reg"] + so_bonus
                if m[f"goals_{side}_pbp_adj"] != official[side]:
                    flag("GOALS_FEED_VS_OFFICIAL",
                         f"{side}: feed(reg{'+so' if so_bonus else ''}) "
                         f"{m[f'goals_{side}_pbp_adj']} vs official {official[side]}")
            if bonus:
                flag("SHOOTOUT_GOAL_BONUS_APPLIED",
                     f"official credits winner {winner} +1 for the shootout")
        for side, lab in (("home", home_side), ("away", away_side)):
            try:
                official_sog = int(lab["team_sog"])
            except (KeyError, ValueError):
                official_sog = None
            if official_sog is not None:
                m[f"sog_{side}_official"] = official_sog
                if m[f"sog_{side}_pbp_reg"] != official_sog:
                    flag("SOG_FEED_VS_OFFICIAL",
                         f"{side}: feed(reg) {m[f'sog_{side}_pbp_reg']} vs official {official_sog}")

    # roster spots -> ID reconciliation
    roster_ids = {int(r["playerId"]) for r in pbp.get("rosterSpots", []) if r.get("playerId")}
    m["roster_ids"] = len(roster_ids)
    official_ids = set(skaters.get(gid, {})) | set(goalies.get(gid, {}))
    appeared_ids = {pid for pid, r in {**skaters.get(gid, {}), **goalies.get(gid, {})}.items()
                    if str(r.get("appeared")) == "1"}
    m["official_ids"] = len(official_ids)
    m["official_appeared_ids"] = len(appeared_ids)
    unknown = roster_ids - official_ids
    m["roster_ids_not_in_official"] = len(unknown)
    if unknown:
        flag("ROSTER_ID_NOT_IN_LABELS", f"{sorted(unknown)[:8]}")
    scorer_ids = {int(d(p).get("scoringPlayerId")) for p in goals if d(p).get("scoringPlayerId")}
    missing_scorers = scorer_ids - roster_ids
    m["scorers_not_in_roster"] = len(missing_scorers)
    if missing_scorers:
        flag("SCORER_NOT_IN_ROSTER", f"{sorted(missing_scorers)[:8]}")

    # shifts: deployment and TOI reconciliation
    if not shifts:
        flag("SHIFTS_MISSING", "no shift chart body")
        return m, bad
    rows = shifts["data"]
    shift_rows = [r for r in rows if int(r.get("typeCode") or 0) == 517]
    m["shift_rows"] = len(shift_rows)
    m["shift_players"] = len({int(r["playerId"]) for r in shift_rows if r.get("playerId")})
    m["shift_rows_bad_duration"] = sum(1 for r in shift_rows if mmss(r.get("duration")) is None)
    toi_by_player: dict[int, int] = defaultdict(int)
    for r in shift_rows:
        pid = r.get("playerId")
        secs = mmss(r.get("duration"))
        if pid is None or secs is None:
            continue
        toi_by_player[int(pid)] += secs

    deltas, goalie_deltas, ratios = [], [], []
    for pid, secs in toi_by_player.items():
        lab = {**skaters.get(gid, {}), **goalies.get(gid, {})}.get(pid)
        if not lab:
            continue
        try:
            off = int(lab.get("toi_seconds") or "")
        except ValueError:
            continue
        deltas_add = goalie_deltas if pid in goalies.get(gid, {}) else deltas
        deltas_add.append(abs(secs - off))
        if off > 300:                     # ignore cameo shifts in the ratio test
            ratios.append(secs / off)
    # A duplicated shift chart doubles every player's TOI; that is a game-level
    # feed defect, not a modelling tolerance, so it is detected rather than tuned.
    m["shift_toi_ratio_median"] = round(float(statistics.median(ratios)), 3) if ratios else 0.0
    m["shift_chart_duplicated"] = bool(ratios and abs(statistics.median(ratios) - 2.0) < 0.15)
    m["toi_compared"] = len(deltas)
    m["toi_within_30s"] = sum(1 for x in deltas if x <= TOI_TOLERANCE_S)
    m["toi_over_60s"] = sum(1 for x in deltas if x > TOI_CONTRADICTION_S)
    m["toi_max_delta_s"] = max(deltas) if deltas else 0
    m["toi_median_delta_s"] = int(statistics.median(deltas)) if deltas else 0
    m["toi_goalie_compared"] = len(goalie_deltas)
    m["toi_goalie_within_30s"] = sum(1 for x in goalie_deltas if x <= TOI_TOLERANCE_S)
    m["toi_goalie_over_60s"] = sum(1 for x in goalie_deltas if x > TOI_CONTRADICTION_S)
    m["toi_goalie_max_delta_s"] = max(goalie_deltas) if goalie_deltas else 0
    if m["toi_over_60s"]:
        flag("TOI_SHIFT_VS_OFFICIAL",
             f"{m['toi_over_60s']} skater(s) differ by >60s")
    if m["shift_chart_duplicated"]:
        flag("DUPLICATE_SHIFT_CHART",
             f"median shift/official TOI ratio {m['shift_toi_ratio_median']:.2f}x")
    if m["toi_goalie_over_60s"]:
        flag("GOALIE_SHIFT_TOI",
             f"{m['toi_goalie_over_60s']} goalie(s) differ by >60s "
             f"(max {m['toi_goalie_max_delta_s']}s)")

    shift_ids = {int(r["playerId"]) for r in shift_rows if r.get("playerId")}
    m["shift_ids_not_in_roster"] = len(shift_ids - roster_ids)
    m["shift_ids_not_in_labels"] = len(shift_ids - official_ids)
    m["appeared_without_shifts"] = len(appeared_ids - shift_ids)
    if m["shift_ids_not_in_roster"]:
        flag("SHIFT_ID_NOT_IN_ROSTER", f"{m['shift_ids_not_in_roster']} id(s)")
    if m["shift_ids_not_in_labels"]:
        flag("SHIFT_ID_NOT_IN_LABELS", f"{m['shift_ids_not_in_labels']} id(s)")
    if m["appeared_without_shifts"]:
        flag("APPEARED_WITHOUT_SHIFTS", f"{m['appeared_without_shifts']} player(s)")

    # on-ice plausibility: max simultaneous skaters per team, from shift intervals
    shift_intervals: dict[int, list[tuple[int, int, int, str]]] = defaultdict(list)
    for r in shift_rows:
        st, en = mmss(r.get("startTime")), mmss(r.get("endTime"))
        if st is None or en is None or en <= st:
            continue
        shift_intervals[int(r.get("period") or 0)].append(
            (st, en, int(r["playerId"]), str(r.get("teamId"))))
    worst = 0
    for period, intervals in shift_intervals.items():
        per_team: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for st, en, _pid, team in intervals:
            per_team[team].append((st, en))
        for team, ivs in per_team.items():
            points = sorted({x for iv in ivs for x in iv})
            for t in points:
                live = sum(1 for a, b in ivs if a <= t < b)
                worst = max(worst, live)
    m["max_concurrent_shift_players_all_teams"] = worst
    if worst > 12:
        flag("SHIFT_OVERLAP", f"{worst} concurrent players across both teams (>12)")
    return m, bad


# ---------------------------------------------------------------------------
# aggregation + report
# ---------------------------------------------------------------------------
def rate(num, den):
    return 0.0 if not den else 100.0 * num / den


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", default=str(HERE / "sample_games.csv"))
    ap.add_argument("--out", default=str(HERE))
    args = ap.parse_args()

    with open(args.sample, newline="", encoding="utf-8") as fh:
        sample = list(csv.DictReader(fh))
    sides, skaters, goalies = load_labels()

    metrics, issues = [], []
    for row in sample:
        m, bad = audit_game(row["game_id"], row, sides, skaters, goalies)
        metrics.append(m)
        issues.extend(bad)

    keys = []
    for m in metrics:
        for k in m:
            if k not in keys:
                keys.append(k)
    with (Path(args.out) / "event_game_metrics.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(metrics)
    with (Path(args.out) / "contradictions.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["game_id", "season", "issue", "detail"])
        w.writeheader()
        w.writerows(issues)

    seasons = sorted({int(m["season"]) for m in metrics})
    rows = []
    for s in seasons:
        g = [m for m in metrics if int(m["season"]) == s]
        n = len(g)
        with_pbp = [m for m in g if m.get("pbp")]
        with_shifts = [m for m in g if m.get("shifts")]
        shots = sum(m.get("shot_events", 0) for m in with_pbp)
        rows.append({
            "season": s, "games": n,
            "pbp_games": len(with_pbp), "shift_games": len(with_shifts),
            "shot_events": shots,
            "pct_shots_with_xy": rate(sum(m.get("shot_events_with_xy", 0) for m in with_pbp), shots),
            "pct_shots_with_type": rate(sum(m.get("shot_events_with_type", 0) for m in with_pbp), shots),
            "unblocked_shot_events": sum(m.get("unblocked_shot_events", 0) for m in with_pbp),
            "unblocked_with_type": sum(m.get("unblocked_with_type", 0) for m in with_pbp),
            "blocked_shot_events": sum(m.get("blocked_shot_events", 0) for m in with_pbp),
            "blocked_with_type": sum(m.get("blocked_with_type", 0) for m in with_pbp),
            "xy_out_of_box": sum(m.get("shot_xy_out_of_box", 0) for m in with_pbp),
            "pct_events_with_situation": rate(
                sum(m.get("events_with_parsable_situation", 0) for m in with_pbp),
                sum(m.get("events_with_situation", 0) for m in with_pbp)),
            "events_with_situation": sum(m.get("events_with_situation", 0) for m in with_pbp),
            "events_parsable": sum(m.get("events_with_parsable_situation", 0) for m in with_pbp),
            "games_goals_match": sum(1 for m in with_pbp
                                     if m.get("goals_home_pbp_adj") == m.get("goals_home_official")
                                     and m.get("goals_away_pbp_adj") == m.get("goals_away_official")),
            "games_sog_match": sum(1 for m in with_pbp
                                   if m.get("sog_home_pbp_reg") == m.get("sog_home_official")
                                   and m.get("sog_away_pbp_reg") == m.get("sog_away_official")),
            "shootout_games": sum(1 for m in with_pbp if m.get("has_shootout")),
            "shootout_goals_in_feed": sum(m.get("shootout_goals_in_feed", 0) for m in with_pbp),
            "shootout_shots_in_feed": sum(m.get("shootout_shots_in_feed", 0) for m in with_pbp),
            "toi_within_30s": sum(m.get("toi_within_30s", 0) for m in with_shifts),
            "toi_over_60s": sum(m.get("toi_over_60s", 0) for m in with_shifts),
            "duplicate_shift_chart_games": sum(1 for m in with_shifts if m.get("shift_chart_duplicated")),
            "toi_goalie_compared": sum(m.get("toi_goalie_compared", 0) for m in with_shifts),
            "toi_goalie_within_30s": sum(m.get("toi_goalie_within_30s", 0) for m in with_shifts),
            "toi_goalie_over_60s": sum(m.get("toi_goalie_over_60s", 0) for m in with_shifts),
            "penalty_events": sum(m.get("penalty_events", 0) for m in with_pbp),
            "pct_penalties_complete": rate(
                sum(m.get("penalties_with_duration", 0) for m in with_pbp),
                sum(m.get("penalty_events", 0) for m in with_pbp)),
            "shift_players": sum(m.get("shift_players", 0) for m in with_shifts),
            "toi_compared": sum(m.get("toi_compared", 0) for m in with_shifts),
            "pct_toi_within_30s": rate(sum(m.get("toi_within_30s", 0) for m in with_shifts),
                                       sum(m.get("toi_compared", 0) for m in with_shifts)),
            "toi_over_60s": sum(m.get("toi_over_60s", 0) for m in with_shifts),
            "roster_ids_not_in_official": sum(m.get("roster_ids_not_in_official", 0) for m in with_pbp),
            "scorers_not_in_roster": sum(m.get("scorers_not_in_roster", 0) for m in with_pbp),
            "shift_ids_not_in_labels": sum(m.get("shift_ids_not_in_labels", 0) for m in with_shifts),
            "appeared_without_shifts": sum(m.get("appeared_without_shifts", 0) for m in with_shifts),
            "shift_overlap_games": sum(1 for m in with_shifts
                                       if m.get("max_concurrent_shift_players_all_teams", 0) > 12),
            "contradictions": sum(1 for i in issues if int(i["season"]) == s),
        })

    with (Path(args.out) / "coverage_by_season.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    issue_counts = Counter(i["issue"] for i in issues)
    summary = {"games_sampled": len(metrics), "by_season": rows,
               "issue_counts": dict(sorted(issue_counts.items())),
               "shot_type_vocabulary": sorted({t for m in metrics
                                               for t in (m.get("shot_type_vocabulary") or [])}),
               "states_seen": sorted({s for m in metrics for s in (m.get("states_seen") or [])})}
    (Path(args.out) / "coverage_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")

    print(f"games audited: {len(metrics)}  contradictions: {len(issues)}")
    print("issue counts:", dict(sorted(issue_counts.items())))
    for r in rows:
        print(f"  {r['season']}: pbp {r['pbp_games']}/{r['games']} shifts {r['shift_games']}/{r['games']} "
              f"xy {r['pct_shots_with_xy']:.1f}% type {r['pct_shots_with_type']:.1f}% "
              f"sog-match {r['games_sog_match']}/{r['pbp_games']} toi30 {r['pct_toi_within_30s']:.1f}%")


if __name__ == "__main__":
    main()
