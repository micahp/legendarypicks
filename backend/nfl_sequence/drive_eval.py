"""Drive-level diagnostics: real nflverse drives and simulated drives under one set of definitions.

A drive is every snap a possession team runs from the kickoff or change of possession that hands it the
ball until the ball changes hands again. Kickoffs and point-after tries sit on the drive but are not
offensive snaps. Penalties and two-point tries are excluded from both sides, so the simulator (which
generates neither) is compared on the same snaps.

Both sides are first reduced to the same ``Play`` record, and one function classifies every drive, so
the definitions cannot drift apart:
- real: nflverse rows. Drive identity is nflverse's ``drive`` number (contiguous within each game and
  one kickoff per drive). Points come from the score change across each play, using the pre-play
  ``posteam_score``/``defteam_score`` and the post-play ``total_home_score``/``total_away_score``.
- simulated: script plays. Drive identity is ``state_before.drive_index``. Points come from the score
  change across each play.

Drive outcomes are decided from the last offensive snap and the points that snap produced, in a fixed
priority order, so every drive ends with exactly one label:
defensive_touchdown, field_goal_made, field_goal_missed, punt, turnover, touchdown, safety_against_offense,
clock_expiration (period ended with the offense on the field), kneel_end_game (last snap a kneel),
turnover_on_downs, kickoff_return_touchdown and no_offensive_snap (a kickoff with no snap before the period
ended), or other (none of the above; reported, expected to be empty).

Historical evaluation boundaries are unchanged: real drives come from the seasons passed in, and the
simulator's models are the committed 2010-2021 artifacts.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

from .model import clock_window

SCRIMMAGE = ("run", "pass", "sack", "scramble", "interception", "punt", "field_goal", "kneel", "spike")
SNAP_PASS = ("run", "pass", "sack", "scramble")
YARDAGE = ("run", "pass", "sack", "scramble", "kneel", "spike")
RED_ZONE_YARDS = 20
OUTCOMES = (
    "touchdown",
    "field_goal_made",
    "field_goal_missed",
    "punt",
    "turnover",
    "defensive_touchdown",
    "safety_against_offense",
    "turnover_on_downs",
    "clock_expiration",
    "kneel_end_game",
    "kickoff_return_touchdown",
    "no_offensive_snap",
    "other",
)
SCORING_OUTCOMES = ("touchdown", "field_goal_made", "kickoff_return_touchdown")
FIELD_BINS = ((1, 20, "1-20"), (21, 40, "21-40"), (41, 60, "41-60"), (61, 80, "61-80"), (81, 99, "81-99"))
SCORE_BINS = ((-99, -9, "trail_9+"), (-8, -1, "trail_1-8"), (0, 0, "tied"), (1, 8, "lead_1-8"), (9, 99, "lead_9+"))
DISTANCE_BINS = ((1, 2, "1-2"), (3, 4, "3-4"), (5, 7, "5-7"), (8, 9, "8-9"), (10, 10, "10"), (11, 99, "11+"))
FG_BINS = ((0, 29, "<=29"), (30, 34, "30-34"), (35, 39, "35-39"), (40, 44, "40-44"), (45, 49, "45-49"), (50, 54, "50-54"), (55, 99, "55+"))
SIM_KIND = {
    "run": "run",
    "pass_complete": "pass",
    "pass_incomplete": "pass",
    "sack": "sack",
    "qb_scramble": "scramble",
    "interception": "interception",
    "punt": "punt",
    "field_goal": "field_goal",
    "kneel": "kneel",
    "spike": "spike",
    "kickoff": "kickoff",
    "extra_point": "pat",
}


@dataclass(frozen=True)
class Play:
    """One snap or kick, identical in shape for real and simulated games."""

    source: str
    game: str
    trial: int
    seq: int
    drive: int
    kind: str
    offense: str
    defense: str
    period: int
    clock: int
    down: Optional[int]
    ydstogo: Optional[int]
    yardline: Optional[int]
    yards: int
    elapsed: int
    fumble: bool
    touchback: bool
    made: Optional[bool]
    first_down: bool
    points_off: int
    points_def: int
    points_off_before: int
    points_def_before: int
    kick_distance: Optional[int]


def _bin(value: int, bins: Sequence[Tuple[int, int, str]]) -> str:
    for low, high, label in bins:
        if low <= value <= high:
            return label
    raise ValueError("value %r outside every bin" % (value,))


def field_bin(yardline: int) -> str:
    return _bin(yardline, FIELD_BINS)


def score_bin(diff: int) -> str:
    return _bin(diff, SCORE_BINS)


def quarter_bin(period: int) -> str:
    return "Q1" if period == 1 else "Q2" if period == 2 else "Q3" if period == 3 else "Q4_OT"


def call_class(kind: str) -> str:
    return {"run": "run", "pass": "pass", "sack": "pass", "scramble": "pass", "interception": "pass",
            "punt": "punt", "field_goal": "field_goal", "kneel": "kneel", "spike": "spike"}[kind]


# --------------------------------------------------------------------------- real nflverse rows


def _real_clock(qtr: Any, gs: Any) -> int:
    qtr, gs = int(qtr), int(gs)
    return gs - 900 * (4 - qtr) if qtr <= 4 else gs


def _real_kind(row: Mapping[str, Any]) -> Optional[str]:
    play_type = row["play_type"]
    if play_type == "kickoff":
        return "kickoff"
    if play_type == "extra_point":
        return "pat"
    if row["two_point_attempt"] == 1:
        return "two_point"
    if play_type == "punt":
        return "punt"
    if play_type == "field_goal":
        return "field_goal"
    if play_type == "qb_kneel":
        return "kneel"
    if play_type == "qb_spike":
        return "spike"
    if play_type in ("run", "pass"):
        if play_type == "run" and row["qb_scramble"] == 1:
            return "scramble"
        if row["sack"] == 1:
            return "sack"
        if row["interception"] == 1:
            return "interception"
        return "pass" if play_type == "pass" else "run"
    return None


def real_game_plays(rows: Sequence[Mapping[str, Any]], skips: Counter) -> List[Play]:
    """Plays of one regular-season game, in order. ``rows`` must be that game's rows sorted by play_id.

    Points are not read from each row's post-play totals. nflverse's totals on penalty (no_play) rows
    are not reliable (they can fall), so a play's post-play score is the pre-play score of the next
    usable row, which carries both teams' scores. The last play's post-play score is the game's final
    (the maximum total seen). Points on skipped rows are therefore still counted, on the next usable play.
    """
    usable = []
    for row in rows:
        if row["play_type"] is None or row["drive"] is None:
            continue
        if row["play_type"] == "no_play" or row["play_deleted"] == 1:
            skips["no_play_or_deleted"] += 1
            continue
        if row["penalty"] == 1:
            skips["penalty_flag_on_a_snap_kept"] += 1  # the snap happened; the flag is recorded, not dropped
        if row["aborted_play"] == 1:
            skips["aborted_flag_on_a_snap_kept"] += 1  # e.g. a lost fumble that nflverse also marks aborted
        kind = _real_kind(row)
        if kind is None:
            skips["unsupported_play_type"] += 1
            continue
        if row["posteam"] is None:
            skips["no_offense"] += 1
            continue
        usable.append((row, kind))

    if not usable:
        return []
    home_team, away_team = usable[0][0]["home_team"], usable[0][0]["away_team"]
    final = {
        home_team: max(int(r["total_home_score"] or 0) for r in rows),
        away_team: max(int(r["total_away_score"] or 0) for r in rows),
    }
    plays: List[Play] = []
    for index, (row, kind) in enumerate(usable):
        offense, defense = row["posteam"], row["defteam"]
        pre_off = int(row["posteam_score"] or 0)
        pre_def = int(row["defteam_score"] or 0)
        if index + 1 < len(usable):
            nxt_row = usable[index + 1][0]
            after = {nxt_row["posteam"]: int(nxt_row["posteam_score"] or 0), nxt_row["defteam"]: int(nxt_row["defteam_score"] or 0)}
        else:
            after = final
        post_off = after[offense]
        post_def = after[defense]
        clock = _real_clock(row["qtr"], row["game_seconds_remaining"])
        if index + 1 < len(usable) and int(usable[index + 1][0]["qtr"]) == int(row["qtr"]):
            nxt_row = usable[index + 1][0]
            elapsed = clock - _real_clock(nxt_row["qtr"], nxt_row["game_seconds_remaining"])
        else:
            nxt_row, elapsed = None, clock
        elapsed = max(0, min(clock, elapsed))
        first_down = False
        if nxt_row is not None and nxt_row["drive"] == row["drive"] and nxt_row["posteam"] == offense:
            first_down = nxt_row["down"] is not None and int(nxt_row["down"]) == 1 and _real_kind(nxt_row) in SCRIMMAGE
        yards = int(row["yards_gained"] or 0) if kind in YARDAGE else 0
        made = None
        if kind == "field_goal":
            made = row["field_goal_result"] == "made"
        elif kind == "pat":
            made = row["extra_point_result"] == "good"
        elif kind == "two_point":
            made = row["two_point_conv_result"] == "success"
        kick_distance = None
        if kind in ("punt", "field_goal") and row["kick_distance"] is not None:
            kick_distance = int(row["kick_distance"])
        plays.append(
            Play(
                source="real",
                game=row["game_id"],
                trial=-1,
                seq=index,
                drive=int(row["drive"]),
                kind=kind,
                offense=offense,
                defense=defense,
                period=int(row["qtr"]),
                clock=clock,
                down=None if row["down"] is None else int(row["down"]),
                ydstogo=None if row["ydstogo"] is None else int(row["ydstogo"]),
                yardline=None if row["yardline_100"] is None else int(row["yardline_100"]),
                yards=yards,
                elapsed=elapsed,
                fumble=row["fumble_lost"] == 1,
                touchback=row["touchback"] == 1,
                made=made,
                first_down=first_down,
                points_off=post_off - pre_off,
                points_def=post_def - pre_def,
                points_off_before=pre_off,
                points_def_before=pre_def,
                kick_distance=kick_distance,
            )
        )
    return plays


# --------------------------------------------------------------------------- simulated scripts


def _score(state: Mapping[str, Any], team: str, home: str) -> int:
    return state["home_score"] if team == home else state["away_score"]


def sim_game_plays(doc: Mapping[str, Any], trial: int) -> List[Play]:
    """Plays of one simulated game from its validated script."""
    home, away = doc["teams"]["home"], doc["teams"]["away"]
    game = doc["game_id"]
    plays: List[Play] = []
    for seq, play in enumerate(doc["plays"]):
        before, after, outcome = play["state_before"], play["state_after"], play["outcome"]
        kind = SIM_KIND[play["event_type"]]
        if kind == "kickoff":
            kicker = before["kicking_team"]
            offense = away if kicker == home else home
            defense = kicker
        else:
            offense, defense = before["offense_team"], before["defense_team"]
        pre_off, pre_def = _score(before, offense, home), _score(before, defense, home)
        post_off, post_def = _score(after, offense, home), _score(after, defense, home)
        clock = before["clock_seconds"]
        yardline = before["yardline_100"]
        first_down = (
            after["phase"] == "scrimmage"
            and after["down"] == 1
            and after["offense_team"] == offense
            and after["drive_index"] == before["drive_index"]
        )
        plays.append(
            Play(
                source="sim",
                game=game,
                trial=trial,
                seq=seq,
                drive=before["drive_index"],
                kind=kind,
                offense=offense,
                defense=defense,
                period=before["quarter"],
                clock=clock,
                down=before["down"],
                ydstogo=before["yards_to_go"],
                yardline=yardline,
                yards=outcome["yards"] if kind in YARDAGE else 0,
                elapsed=outcome["elapsed"],
                fumble=bool(outcome["fumble_lost"]),
                touchback=bool(outcome["touchback"]),
                made=outcome["made"] if kind in ("field_goal", "pat") else None,
                first_down=first_down,
                points_off=post_off - pre_off,
                points_def=post_def - pre_def,
                points_off_before=pre_off,
                points_def_before=pre_def,
                kick_distance=yardline + 17 if kind == "field_goal" else None,
            )
        )
    return plays


# --------------------------------------------------------------------------- drives


@dataclass
class Drive:
    source: str
    game: str
    trial: int
    drive: int
    offense: str
    defense: str
    outcome: str
    mixed_offense: bool
    start_yardline: Optional[int]
    start_period: Optional[int]
    start_clock: Optional[int]
    start_score_diff: Optional[int]
    plays: int
    run_pass_plays: int
    first_downs: int
    net_yards: int
    duration: int
    third_att: int
    third_conv: int
    fourth_go_att: int
    fourth_go_conv: int
    fourth_punt: int
    fourth_fg: int
    red_zone_entry: bool
    red_zone_td: bool
    points_off: int
    pat_points: int
    pat_att: int
    pat_missed: int
    fg_att: int
    fg_made: int
    fg_distances: List[int]
    turnovers: int
    kick_present: bool
    kick_touchback: bool
    kick_points: int
    last_kind: Optional[str]


def _outcome(sp: Sequence[Play], kicks: Sequence[Play]) -> str:
    if not sp:
        return "kickoff_return_touchdown" if any(k.points_off >= 6 for k in kicks) else "no_offensive_snap"
    last = sp[-1]
    clock_end = last.clock - last.elapsed
    if last.points_def >= 6:
        return "defensive_touchdown"
    if last.kind == "field_goal":
        return "field_goal_made" if last.points_off >= 3 else "field_goal_missed"
    if last.kind == "punt":
        return "punt"
    if last.kind == "interception" or last.fumble:
        return "turnover"
    if any(p.points_off >= 6 for p in sp):
        return "touchdown"
    if last.points_def == 2:
        return "safety_against_offense"
    if last.kind == "kneel":
        return "kneel_end_game"
    if clock_end <= 0:
        return "clock_expiration"
    if last.kind in SNAP_PASS and last.down == 4 and not last.first_down:
        return "turnover_on_downs"
    return "other"


def build_drives(plays: Sequence[Play]) -> List[Drive]:
    """Group one game's plays into drives and classify each drive. Plays must be in game order."""
    groups: Dict[int, List[Play]] = {}
    order: List[int] = []
    for play in plays:
        if play.drive not in groups:
            groups[play.drive] = []
            order.append(play.drive)
        groups[play.drive].append(play)

    drives: List[Drive] = []
    for drive_id in order:
        ps = groups[drive_id]
        kicks = [p for p in ps if p.kind == "kickoff"]
        pats = [p for p in ps if p.kind in ("pat", "two_point")]
        sp = [p for p in ps if p.kind in SCRIMMAGE]
        head = sp[0] if sp else (kicks[0] if kicks else ps[0])
        offense, defense = head.offense, head.defense
        mixed = any(p.offense != offense for p in sp)
        first = sp[0] if sp else None
        third = [p for p in sp if p.down == 3 and p.kind in SNAP_PASS]
        fourth = [p for p in sp if p.down == 4 and p.kind in SNAP_PASS]
        fgs = [p for p in sp if p.kind == "field_goal"]
        red = [p for p in sp if p.yardline is not None and p.yardline <= RED_ZONE_YARDS]
        drives.append(
            Drive(
                source=head.source,
                game=head.game,
                trial=head.trial,
                drive=drive_id,
                offense=offense,
                defense=defense,
                outcome=_outcome(sp, kicks),
                mixed_offense=mixed,
                start_yardline=first.yardline if first else None,
                start_period=first.period if first else (head.period if head else None),
                start_clock=first.clock if first else None,
                start_score_diff=(head.points_off_before - head.points_def_before) if head else None,
                plays=len(sp),
                run_pass_plays=sum(1 for p in sp if p.kind in SNAP_PASS),
                first_downs=sum(1 for p in sp if p.first_down),
                net_yards=sum(p.yards for p in sp),
                duration=sum(p.elapsed for p in sp),
                third_att=len(third),
                third_conv=sum(1 for p in third if p.first_down or p.points_off >= 6),
                fourth_go_att=len(fourth),
                fourth_go_conv=sum(1 for p in fourth if p.first_down or p.points_off >= 6),
                fourth_punt=sum(1 for p in sp if p.down == 4 and p.kind == "punt"),
                fourth_fg=sum(1 for p in sp if p.down == 4 and p.kind == "field_goal"),
                red_zone_entry=bool(red),
                red_zone_td=bool(red) and any(p.points_off >= 6 for p in sp),
                points_off=sum(p.points_off for p in sp),
                pat_points=sum(p.points_off for p in pats if p.offense == offense),
                pat_att=sum(1 for p in pats if p.offense == offense),
                pat_missed=sum(1 for p in pats if p.offense == offense and p.made is False),
                fg_att=len(fgs),
                fg_made=sum(1 for p in fgs if p.made),
                fg_distances=[p.kick_distance for p in fgs if p.kick_distance is not None],
                turnovers=sum(1 for p in sp if p.kind == "interception" or p.fumble),
                kick_present=bool(kicks),
                kick_touchback=any(k.touchback for k in kicks),
                kick_points=sum(k.points_off for k in kicks),
                last_kind=sp[-1].kind if sp else None,
            )
        )
    return drives


def game_points(plays: Sequence[Play]) -> Dict[str, int]:
    """Points each team scored, from every play's score change (kickoffs and PATs included)."""
    totals: Dict[str, int] = {}
    for play in plays:
        totals[play.offense] = totals.get(play.offense, 0) + play.points_off
        totals[play.defense] = totals.get(play.defense, 0) + play.points_def
    return totals


# --------------------------------------------------------------------------- tallies


def tally_game(plays: Sequence[Play], counts: Counter) -> List[int]:
    """Add one game's drive and play counts to ``counts``. Returns the points each team scored (two values)."""
    drives = build_drives(plays)
    counts["games"] += 1
    counts["drives"] += len(drives)
    for drive in drives:
        counts["outcome:" + drive.outcome] += 1
        counts["plays"] += drive.plays
        counts["points_off"] += drive.points_off
        counts["run_pass_plays"] += drive.run_pass_plays
        counts["first_downs"] += drive.first_downs
        counts["net_yards"] += drive.net_yards
        counts["duration"] += drive.duration
        counts["turnovers"] += drive.turnovers
        counts["third_att"] += drive.third_att
        counts["third_conv"] += drive.third_conv
        counts["fourth_go_att"] += drive.fourth_go_att
        counts["fourth_go_conv"] += drive.fourth_go_conv
        counts["fourth_punt"] += drive.fourth_punt
        counts["fourth_fg"] += drive.fourth_fg
        counts["rz_entry"] += int(drive.red_zone_entry)
        counts["rz_td"] += int(drive.red_zone_td)
        counts["pat_att"] += drive.pat_att
        counts["pat_made"] += drive.pat_att - drive.pat_missed
        counts["fg_att"] += drive.fg_att
        counts["fg_made"] += drive.fg_made
        for distance in drive.fg_distances:
            counts["fg_dist_sum"] += distance
            counts["fg_dist_n"] += 1
            counts["fg_dist_bin:%s:att" % _bin(min(distance, 99), FG_BINS)] += 1
            counts["fg_over_99_yards"] += int(distance > 99)
        counts["kick_touchback"] += int(drive.kick_touchback)
        counts["kick_present"] += int(drive.kick_present)
        if drive.start_yardline is not None:
            fb = field_bin(drive.start_yardline)
            counts["field:%s:drives" % fb] += 1
            counts["field:%s:%s" % (fb, drive.outcome)] += 1
            counts["field:%s:points" % fb] += drive.points_off
            counts["field:%s:td_rz_entry" % fb] += int(drive.red_zone_entry)
            counts["start_yardline_sum"] += drive.start_yardline
            counts["start_yardline_n"] += 1
        if drive.start_period is not None:
            qb = quarter_bin(drive.start_period)
            counts["quarter:%s:drives" % qb] += 1
            counts["quarter:%s:%s" % (qb, drive.outcome)] += 1
        if drive.start_score_diff is not None:
            sb = score_bin(drive.start_score_diff)
            counts["score:%s:drives" % sb] += 1
            counts["score:%s:%s" % (sb, drive.outcome)] += 1
    for prev, nxt in zip(drives, drives[1:]):
        scored = prev.outcome in SCORING_OUTCOMES
        counts["pair:%s>%s" % (prev.outcome, nxt.outcome)] += 1
        counts["after_score:%s:%s" % ("scored" if scored else "no_score", nxt.outcome)] += 1
        if nxt.start_yardline is not None:
            counts["after_score:%s:start_%s" % ("scored" if scored else "no_score", field_bin(nxt.start_yardline))] += 1
        counts["after_score:%s:n" % ("scored" if scored else "no_score")] += 1

    for play in plays:
        if play.kind in SCRIMMAGE and play.down is not None and play.yardline is not None:
            fb = field_bin(play.yardline)
            counts["call:%s:%s:%s" % (play.down, fb, call_class(play.kind))] += 1
            counts["calls"] += 1
            if play.kind in ("run", "pass"):
                counts["yds_n:%s:%s" % (play.kind, fb)] += 1
                counts["yds_sum:%s:%s" % (play.kind, fb)] += play.yards
            if play.kind == "sack":
                counts["sack:%s" % fb] += 1
            if play.down == 4 and play.kind in SNAP_PASS:
                counts["fourth_go:%s" % fb] += 1
            if play.down == 4 and play.kind == "punt":
                counts["fourth_punt_field:%s" % fb] += 1
            if play.kind in SNAP_PASS and play.down == 3 and play.ydstogo is not None:
                db = _bin(play.ydstogo, DISTANCE_BINS)
                counts["conv3:%s:att" % db] += 1
                counts["conv3:%s:conv" % db] += int(play.first_down or play.points_off >= 6)
            if play.fumble:
                counts["fumbles_lost"] += 1
        if play.kind == "field_goal" and play.kick_distance is not None and play.made:
            counts["fg_dist_bin:%s:made" % _bin(min(play.kick_distance, 99), FG_BINS)] += 1
        if play.kind in SCRIMMAGE and play.down is not None and play.clock is not None:
            window = clock_window(play.period, play.clock)
            lead = "lead" if play.points_off_before > play.points_def_before else ("trail" if play.points_off_before < play.points_def_before else "tied")
            counts["call_timing:%s:%s:%s" % (window, lead, call_class(play.kind))] += 1
        if play.kind in ("run", "pass") and play.down is not None and play.ydstogo is not None:
            db = _bin(play.ydstogo, DISTANCE_BINS)
            counts["yds_db_n:%s:%d:%s" % (play.kind, play.down, db)] += 1
            counts["yds_db_sum:%s:%d:%s" % (play.kind, play.down, db)] += play.yards
        if play.kind in ("pat", "two_point") and play.made is not None:
            counts["xp_att"] += 1
            counts["xp_made"] += int(play.made)
    points = list(game_points(plays).values())
    counts["team_points"] += sum(points)
    counts["team_games"] += len(points)
    return points


# --------------------------------------------------------------------------- CLI helpers


def _read_games(source_dir: str, season: int) -> Iterator[Tuple[str, List[Mapping[str, Any]]]]:
    from .nflverse import read_season

    rows = read_season(os.path.join(source_dir, "play_by_play_%d.parquet" % season))
    current, group = None, []
    for row in rows:
        if row["game_id"] != current:
            if group:
                yield current, group
            current, group = row["game_id"], []
        group.append(row)
    if group:
        yield current, group


def _write_jsonl(handle, record: Mapping[str, Any]) -> None:
    handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")


def cmd_real(args: argparse.Namespace) -> None:
    seasons = _parse_seasons(args.seasons)
    with gzip.open(args.out, "wt") as handle:
        for season in seasons:
            season_skips: Counter = Counter()
            for game_id, rows in _read_games(args.source_dir, season):
                skips: Counter = Counter()
                plays = real_game_plays(rows, skips)
                season_skips.update(skips)
                drives = build_drives(plays)
                points = game_points(plays)
                head = rows[0]
                _write_jsonl(handle, {
                    "kind": "game", "source": "real", "season": season, "game": game_id,
                    "home": head["home_team"], "away": head["away_team"],
                    "points": points, "drives": len(drives), "plays": len(plays),
                })
                for drive in drives:
                    _write_jsonl(handle, dict(asdict(drive), kind="drive", season=season))
                for play in plays:
                    if play.kind in SCRIMMAGE:
                        _write_jsonl(handle, dict(asdict(play), kind="snap", season=season))
            _write_jsonl(handle, {"kind": "skips", "season": season, "skips": dict(season_skips)})


def cmd_sim(args: argparse.Namespace) -> None:
    from .evaluate import actual_game_table, snapshot_hash
    from .model import StatModel
    from .nflverse import read_season
    from .simulate import MODEL_VERSION, Simulator, derive_seed, script

    seasons = _parse_seasons(args.test_seasons)
    rows = []
    for season in seasons:
        rows.extend(read_season(os.path.join(args.source_dir, "play_by_play_%d.parquet" % season)))
    games = actual_game_table(rows)
    model = StatModel.load(os.path.join(args.model_dir, "nfl-seq-v0.1-%s.json" % args.variant))
    game_ids = sorted(games)
    mine = [g for index, g in enumerate(game_ids) if index % args.shards == args.shard]
    counts_by_trial: Dict[int, Counter] = {t: Counter() for t in range(args.trials)}
    points_by_trial: Dict[int, List[int]] = {t: [] for t in range(args.trials)}
    validity: Counter = Counter()
    for game_id in mine:
        game = games[game_id]
        sim = Simulator(
            model,
            game_id=game_id,
            home_team=game["home_team"],
            away_team=game["away_team"],
            season=game["season"],
            snapshot_hash=snapshot_hash(game_id, game["season"], game["home_team"], game["away_team"]),
        )
        for trial in range(args.trials):
            seed = derive_seed(sim.game_key, sim.snapshot_hash, MODEL_VERSION, trial)
            doc = script(sim.start(seed).advance())
            validity["trials"] += 1
            validity["valid" if doc["valid_full_game"] else "invalid"] += 1
            plays = sim_game_plays(doc, trial)
            points_by_trial[trial].extend(tally_game(plays, counts_by_trial[trial]))
    record = {
        "kind": "shard",
        "shard": args.shard,
        "shards": args.shards,
        "games": mine,
        "trials": args.trials,
        "validity": dict(validity),
        "counts": {str(t): dict(c) for t, c in counts_by_trial.items()},
        "team_points": {str(t): v for t, v in points_by_trial.items()},
    }
    with gzip.open(args.out, "wt") as handle:
        _write_jsonl(handle, record)


def _parse_seasons(text: str) -> List[int]:
    from .train import parse_seasons

    return parse_seasons(text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("examples", help="print representative real and simulated drive sequences")
    ex.add_argument("--source-dir", required=True)
    ex.add_argument("--model-dir", required=True)
    ex.add_argument("--real-season", type=int, default=2023)
    ex.add_argument("--test-seasons", default="2022-2023")
    ex.add_argument("--per-outcome", type=int, default=2)
    ex.add_argument("--sim-games", type=int, default=60)
    ex.add_argument("--out", required=True)
    ex.set_defaults(func=cmd_examples)
    rep = sub.add_parser("report", help="aggregate real, simulated and baseline drives into the report JSON")
    rep.add_argument("--source-dir", required=True)
    rep.add_argument("--real-seasons", default="2022-2023")
    rep.add_argument("--baseline-seasons", default="2010-2021")
    rep.add_argument("--sim-glob", required=True)
    rep.add_argument("--reps", type=int, default=2000)
    rep.add_argument("--seed", type=int, default=20261023)
    rep.add_argument("--out", required=True)
    rep.set_defaults(func=cmd_report)
    real = sub.add_parser("real", help="extract real drives from nflverse rows")
    real.add_argument("--source-dir", required=True)
    real.add_argument("--seasons", required=True)
    real.add_argument("--out", required=True)
    real.set_defaults(func=cmd_real)
    sim = sub.add_parser("sim", help="simulate the test games and tally drives per trial")
    sim.add_argument("--source-dir", required=True)
    sim.add_argument("--model-dir", required=True)
    sim.add_argument("--variant", default="main")
    sim.add_argument("--test-seasons", required=True)
    sim.add_argument("--trials", type=int, default=100)
    sim.add_argument("--shard", type=int, default=0)
    sim.add_argument("--shards", type=int, default=1)
    sim.add_argument("--out", required=True)
    sim.set_defaults(func=cmd_sim)
    args = parser.parse_args()
    args.func(args)




# --------------------------------------------------------------------------- report


def _real_units(source_dir: str, seasons: Sequence[int]) -> Tuple[List[Counter], List[List[int]]]:
    units: List[Counter] = []
    team_points: List[List[int]] = []
    for season in seasons:
        for _game_id, rows in _read_games(source_dir, season):
            counts: Counter = Counter()
            team_points.append(tally_game(real_game_plays(rows, Counter()), counts))
            units.append(counts)
    return units, team_points


def _aggregate(source_dir: str, seasons: Sequence[int]) -> Tuple[Counter, List[List[int]]]:
    total: Counter = Counter()
    units, team_points = _real_units(source_dir, seasons)
    for counts in units:
        total.update(counts)
    return total, team_points


def _sim_units(paths: Sequence[str]) -> Tuple[List[Counter], List[List[int]], Counter]:
    per_trial: Dict[int, Counter] = {}
    points: Dict[int, List[int]] = {}
    validity: Counter = Counter()
    for path in paths:
        with gzip.open(path, "rt") as handle:
            record = json.loads(handle.readline())
        validity.update(record["validity"])
        for trial, counts in record["counts"].items():
            per_trial.setdefault(int(trial), Counter()).update(counts)
        for trial, values in record["team_points"].items():
            points.setdefault(int(trial), []).extend(values)
    trials = sorted(per_trial)
    return [per_trial[t] for t in trials], [points[t] for t in trials], validity


def _ratio(num: Any, den: Any) -> Any:
    import numpy as np

    num = np.asarray(num, dtype=float)
    den = np.asarray(den, dtype=float)
    out = np.full(np.broadcast(num, den).shape, np.nan)
    np.divide(num, den, out=out, where=den > 0)
    return out


OUTCOME_SHARE_LABELS = ("touchdown", "field_goal_made", "field_goal_missed", "punt", "turnover",
                        "turnover_on_downs", "defensive_touchdown", "clock_expiration", "kneel_end_game",
                        "no_offensive_snap", "kickoff_return_touchdown", "safety_against_offense", "other")


def compute_stats(get: Any) -> Dict[str, Any]:
    """Every reported statistic, as a ratio of additive counts. ``get(key)`` returns the count per unit."""
    g = get
    S: Dict[str, Any] = {}
    games, drives = g("games"), g("drives")
    S["drives_per_game"] = _ratio(drives, games)
    S["drives_per_team_game"] = _ratio(drives, 2 * games)
    for outcome in OUTCOME_SHARE_LABELS:
        S["share:" + outcome] = _ratio(g("outcome:" + outcome), drives)
        S["per_game:" + outcome] = _ratio(g("outcome:" + outcome), games)
    S["plays_per_drive"] = _ratio(g("plays"), drives)
    S["run_pass_per_drive"] = _ratio(g("run_pass_plays"), drives)
    S["first_downs_per_drive"] = _ratio(g("first_downs"), drives)
    S["yards_per_drive"] = _ratio(g("net_yards"), drives)
    S["duration_min_per_drive"] = _ratio(g("duration"), drives) / 60.0
    S["points_off_per_drive"] = _ratio(g("points_off"), drives)
    S["points_per_team_game"] = _ratio(g("team_points"), g("team_games"))
    S["turnovers_per_drive"] = _ratio(g("turnovers"), drives)
    S["fg_attempts_per_drive"] = _ratio(g("fg_att"), drives)
    S["fg_make_rate"] = _ratio(g("fg_made"), g("fg_att"))
    S["fg_miss_rate"] = _ratio(g("fg_att") - g("fg_made"), g("fg_att"))
    S["fg_distance_mean"] = _ratio(g("fg_dist_sum"), g("fg_dist_n"))
    S["rz_entry_per_drive"] = _ratio(g("rz_entry"), drives)
    S["rz_td_conversion"] = _ratio(g("rz_td"), g("rz_entry"))
    S["start_yardline_mean"] = _ratio(g("start_yardline_sum"), g("start_yardline_n"))
    S["third_down_attempts_per_drive"] = _ratio(g("third_att"), drives)
    S["third_down_conversion"] = _ratio(g("third_conv"), g("third_att"))
    S["fourth_down_go_conversion"] = _ratio(g("fourth_go_conv"), g("fourth_go_att"))
    S["fourth_down_go_share"] = _ratio(g("fourth_go_att"), g("fourth_go_att") + g("fourth_punt") + g("fourth_fg"))
    S["pat_make_rate"] = _ratio(g("pat_made"), g("pat_att"))
    for fb in [label for _, _, label in FIELD_BINS]:
        fd = g("field:%s:drives" % fb)
        S["start_share:" + fb] = _ratio(fd, drives)
        S["field_points_per_drive:" + fb] = _ratio(g("field:%s:points" % fb), fd)
        for outcome in ("touchdown", "field_goal_made", "field_goal_missed", "punt", "turnover", "turnover_on_downs"):
            S["field_share:%s:%s" % (fb, outcome)] = _ratio(g("field:%s:%s" % (fb, outcome)), fd)
        S["field_share:%s:clock" % fb] = _ratio(g("field:%s:clock_expiration" % fb) + g("field:%s:kneel_end_game" % fb), fd)
        calls_run = sum(g("call:%d:%s:run" % (d, fb)) for d in (1, 2, 3, 4))
        calls_all = sum(g("call:%d:%s:%s" % (d, fb, c)) for d in (1, 2, 3, 4) for c in ("run", "pass", "punt", "field_goal", "kneel", "spike"))
        S["call_share:run:" + fb] = _ratio(calls_run, calls_all)
        go = g("call:4:%s:run" % fb) + g("call:4:%s:pass" % fb)
        S["fourth_go_share:" + fb] = _ratio(go, go + g("call:4:%s:punt" % fb) + g("call:4:%s:field_goal" % fb))
        S["yards_per_run:" + fb] = _ratio(g("yds_sum:run:%s" % fb), g("yds_n:run:%s" % fb))
        S["yards_per_pass:" + fb] = _ratio(g("yds_sum:pass:%s" % fb), g("yds_n:pass:%s" % fb))
    for quarter in ("Q1", "Q2", "Q3", "Q4_OT"):
        qd = g("quarter:%s:drives" % quarter)
        for outcome in ("touchdown", "field_goal_made", "punt", "turnover"):
            S["quarter_share:%s:%s" % (quarter, outcome)] = _ratio(g("quarter:%s:%s" % (quarter, outcome)), qd)
    for score in [label for _, _, label in SCORE_BINS]:
        sd = g("score:%s:drives" % score)
        for outcome in ("touchdown", "field_goal_made", "punt", "turnover"):
            S["score_share:%s:%s" % (score, outcome)] = _ratio(g("score:%s:%s" % (score, outcome)), sd)
    scored, unscored = g("after_score:scored:n"), g("after_score:no_score:n")
    S["next_td_after_scored"] = _ratio(g("after_score:scored:touchdown"), scored)
    S["next_points_after_scored"] = _ratio(g("after_score:scored:touchdown") + g("after_score:scored:field_goal_made"), scored)
    S["next_td_after_unscored"] = _ratio(g("after_score:no_score:touchdown"), unscored)
    S["next_points_after_unscored"] = _ratio(g("after_score:no_score:touchdown") + g("after_score:no_score:field_goal_made"), unscored)
    for fb in [label for _, _, label in FIELD_BINS]:
        S["next_start_after_scored:" + fb] = _ratio(g("after_score:scored:start_%s" % fb), scored)
    for db in [label for _, _, label in DISTANCE_BINS]:
        S["third_conv_by_distance:" + db] = _ratio(g("conv3:%s:conv" % db), g("conv3:%s:att" % db))
    for label in [label for _, _, label in FG_BINS]:
        S["fg_make_by_distance:" + label] = _ratio(g("fg_dist_bin:%s:made" % label), g("fg_dist_bin:%s:att" % label))
    S["touchback_share_per_kickoff"] = _ratio(g("kick_touchback"), g("kick_present"))
    for lead in ("lead", "tied", "trail"):
        late = {c: g("call_timing:late:%s:%s" % (lead, c)) for c in ("run", "pass", "punt", "field_goal", "kneel", "spike")}
        total_late = sum(late.values())
        early = {c: g("call_timing:early:%s:%s" % (lead, c)) for c in ("run", "pass", "punt", "field_goal", "kneel", "spike")}
        total_early = sum(early.values())
        S["late_kneel_share:" + lead] = _ratio(late["kneel"], total_late)
        S["late_run_share:" + lead] = _ratio(late["run"], total_late)
        S["late_pass_share:" + lead] = _ratio(late["pass"], total_late)
        S["early_kneel_share:" + lead] = _ratio(early["kneel"], total_early)
        S["late_snap_share:" + lead] = _ratio(total_late, total_late + total_early)
    for down in (1, 2, 3, 4):
        for db in [label for _, _, label in DISTANCE_BINS]:
            for kind in ("run", "pass"):
                S["yards_per_%s:%d:%s" % (kind, down, db)] = _ratio(g("yds_db_sum:%s:%d:%s" % (kind, down, db)), g("yds_db_n:%s:%d:%s" % (kind, down, db)))
    return S


def _getter(matrix: Any, index: Mapping[str, int]) -> Any:
    import numpy as np

    rows = matrix.shape[0]

    def get(key: str) -> Any:
        if key in index:
            return matrix[:, index[key]]
        return np.zeros(rows)

    return get


def _matrix(units: Sequence[Mapping[str, float]], keys: Sequence[str], index: Mapping[str, int]) -> Any:
    import numpy as np

    matrix = np.zeros((len(units), len(keys)))
    for row, counts in enumerate(units):
        for key, value in counts.items():
            matrix[row, index[key]] = value
    return matrix


def _summary(values: Sequence[float]) -> Optional[float]:
    return None if not values else float(sorted(values)[len(values) // 2])


def run_report(args: argparse.Namespace) -> Dict[str, Any]:
    import glob

    import numpy as np

    real_units, real_points = _real_units(args.source_dir, _parse_seasons(args.real_seasons))
    base_total, base_points = _aggregate(args.source_dir, _parse_seasons(args.baseline_seasons))
    sim_paths = sorted(glob.glob(args.sim_glob))
    sim_units, sim_points, validity = _sim_units(sim_paths)
    keys = sorted(set().union(*[set(c) for c in real_units + sim_units + [base_total]]))
    index = {k: i for i, k in enumerate(keys)}
    R = _matrix(real_units, keys, index)
    S = _matrix(sim_units, keys, index)
    B = _matrix([base_total], keys, index)
    rng = np.random.default_rng(args.seed)
    n = R.shape[0]
    counts_per_rep = np.zeros((args.reps, n))
    for rep in range(args.reps):
        counts_per_rep[rep] = np.bincount(rng.integers(0, n, size=n), minlength=n)
    BR = counts_per_rep @ R

    real_point = compute_stats(_getter(R.sum(axis=0, keepdims=True), index))
    real_boot = compute_stats(_getter(BR, index))
    sim = compute_stats(_getter(S, index))
    base = compute_stats(_getter(B, index))

    def pct(values: Any, q: float) -> Optional[float]:
        values = np.asarray(values, dtype=float)
        values = values[np.isfinite(values)]
        return float(np.percentile(values, q)) if values.size else None

    stats: Dict[str, Any] = {}
    for name in real_point:
        est = real_point[name][0]
        boot = real_boot[name]
        sims = sim[name]
        stats[name] = {
            "real": {"estimate": None if not np.isfinite(est) else float(est),
                     "ci95": [pct(boot, 2.5), pct(boot, 97.5)]},
            "sim": {"mean": float(np.nanmean(sims)) if np.isfinite(sims).any() else None,
                    "p2_5": pct(sims, 2.5), "p97_5": pct(sims, 97.5)},
            "baseline_2010_2021": None if not np.isfinite(base[name][0]) else float(base[name][0]),
        }

    def dist(values: Sequence[int]) -> Dict[str, Any]:
        arr = np.asarray(values, dtype=float)
        return {"n": int(arr.size), "mean": float(arr.mean()) if arr.size else None,
                "sd": float(arr.std()) if arr.size else None,
                "p10": float(np.percentile(arr, 10)) if arr.size else None,
                "p50": float(np.percentile(arr, 50)) if arr.size else None,
                "p90": float(np.percentile(arr, 90)) if arr.size else None}

    real_pts = [p for game in real_points for p in game]
    sim_pts = [p for trial in sim_points for p in trial]
    base_pts_flat = [p for game in base_points for p in game]
    report = {
        "real_seasons": _parse_seasons(args.real_seasons),
        "baseline_seasons": _parse_seasons(args.baseline_seasons),
        "sim_files": [os.path.basename(p) for p in sim_paths],
        "real_games": n,
        "sim_trials": len(sim_units),
        "bootstrap_reps": args.reps,
        "bootstrap_seed": args.seed,
        "sim_validity": dict(validity),
        "stats": stats,
        "team_game_points": {"real": dist(real_pts), "sim_pooled": dist(sim_pts), "baseline_2010_2021": dist(base_pts_flat)},
        "totals": {
            "real_2022_2023": {k: float(v) for k, v in zip(keys, R.sum(axis=0)) if v},
            "baseline_2010_2021": {k: float(v) for k, v in zip(keys, B[0]) if v},
            "sim_trial_mean": {k: float(v) for k, v in zip(keys, S.mean(axis=0)) if v},
        },
    }
    return report


def cmd_report(args: argparse.Namespace) -> None:
    report = run_report(args)
    with open(args.out, "w") as handle:
        json.dump(report, handle, indent=1, sort_keys=True, default=lambda o: None)
    print(json.dumps({"out": args.out, "real_games": report["real_games"], "sim_trials": report["sim_trials"]}, indent=1))


# --------------------------------------------------------------------------- representative sequences


def _play_line(p: Play) -> str:
    down = "" if p.down is None else "%d&%s" % (p.down, p.ydstogo)
    spot = "" if p.yardline is None else "@%d" % p.yardline
    pts = "" if (p.points_off == 0 and p.points_def == 0) else " pts off %+d def %+d" % (p.points_off, p.points_def)
    fd = " FIRST DOWN" if p.first_down else ""
    fum = " FUMBLE LOST" if p.fumble else ""
    made = "" if p.made is None else (" made" if p.made else " missed")
    return "    %-14s %-6s %-6s yds %+3d  %3ds  Q%d %02d:%02d%s%s%s%s" % (
        p.kind, down, spot, p.yards, p.elapsed, p.period, p.clock // 60, p.clock % 60, made, fum, fd, pts)


def describe_drives(source: str, game: str, plays: Sequence[Play], want: Mapping[str, int], out: List[str]) -> None:
    """Append up to ``want[outcome]`` drives per outcome, each with its snaps, to ``out``."""
    by_drive: Dict[int, List[Play]] = {}
    for p in plays:
        by_drive.setdefault(p.drive, []).append(p)
    for drive in build_drives(plays):
        if want.get(drive.outcome, 0) <= 0:
            continue
        want[drive.outcome] -= 1
        ps = by_drive[drive.drive]
        out.append("%s %s drive %d: %s | %d snaps, %d first downs, %d net yds, %d s, start %s, %s" % (
            source, game, drive.drive, drive.outcome, drive.plays, drive.first_downs, drive.net_yards,
            drive.duration, drive.start_yardline, "offense %s" % drive.offense))
        out.extend(_play_line(p) for p in ps if p.kind in SCRIMMAGE or p.kind in ("kickoff", "pat", "two_point"))
        out.append("")


def run_examples(args: argparse.Namespace) -> List[str]:
    from .evaluate import actual_game_table, snapshot_hash
    from .model import StatModel
    from .nflverse import read_season
    from .simulate import MODEL_VERSION, Simulator, derive_seed, script

    want_real = {o: args.per_outcome for o in ("touchdown", "field_goal_made", "field_goal_missed", "punt", "turnover",
                                                "turnover_on_downs", "defensive_touchdown", "clock_expiration",
                                                "safety_against_offense", "kneel_end_game", "no_offensive_snap")}
    out: List[str] = ["# Real drives, nflverse %s, regular season" % args.real_season, ""]
    for game_id, rows in _read_games(args.source_dir, args.real_season):
        if not any(v > 0 for v in want_real.values()):
            break
        describe_drives("real", game_id, real_game_plays(rows, Counter()), want_real, out)

    rows = []
    for season in _parse_seasons(args.test_seasons):
        rows.extend(read_season(os.path.join(args.source_dir, "play_by_play_%d.parquet" % season)))
    games = actual_game_table(rows)
    model = StatModel.load(os.path.join(args.model_dir, "nfl-seq-v0.1-%s.json" % args.variant))
    want_sim = {o: args.per_outcome for o in want_real}
    out.append("# Simulated drives, model nfl-seq-v0.1 main, trial 0 of each game (same seeds as the evaluation)")
    out.append("")
    for game_id in sorted(games)[: args.sim_games]:
        if not any(v > 0 for v in want_sim.values()):
            break
        game = games[game_id]
        sim = Simulator(model, game_id=game_id, home_team=game["home_team"], away_team=game["away_team"],
                        season=game["season"], snapshot_hash=snapshot_hash(game_id, game["season"], game["home_team"], game["away_team"]))
        doc = script(sim.start(derive_seed(sim.game_key, sim.snapshot_hash, MODEL_VERSION, 0)).advance())
        describe_drives("sim", game_id, sim_game_plays(doc, 0), want_sim, out)
    return out


def cmd_examples(args: argparse.Namespace) -> None:
    lines = run_examples(args)
    with open(args.out, "w") as handle:
        handle.write("\n".join(lines) + "\n")
    print("wrote %s, %d lines" % (args.out, len(lines)))


if __name__ == "__main__":
    main()
