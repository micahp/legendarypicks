#!/usr/bin/env python3
"""seed_metrics.py -- per-seed team and player realism metrics from the 2025 realism batches.

Runs on the fast host with the standard library only, against the raw batch files, which it never writes. It emits
two derived tables, one row per (arm, game, seed, team) and one row per (arm, game, seed, player). Seeds whose batch
has no record (simulation_error) produce no rows; the verifier reports them. Blocked and incomplete seeds keep their
rows and carry their status, so the scorer decides what to include.

Definitions (matched to the observed extractor in observed_2025_metrics.py):
  scrimmage play   a simulated play whose event is run, pass_complete, pass_incomplete, sack, interception or
                   fumble_lost. Punts and field-goal attempts are not scrimmage plays.
  run / pass       decision_type 'run' / 'dropback' (a dropback includes sacks and interceptions)
  drive            a drive summary with at least one play, by offense team
  three-and-out    a drive with exactly 3 scrimmage plays that ends in a punt
  turnover         an interception or fumble_lost play by the offense
  yardage bucket   run plays by yards_gained; pass plays are pass_complete, pass_incomplete and sack
  half             quarters 1-2 are the first half, 3-4 the second half, 5 is overtime

Usage: python3 seed_metrics.py --root /root/repro/arms-2025 --out DIR
"""
import argparse
import csv
import glob
import gzip
import json
import os
import sys
from collections import defaultdict

ARMS = ("v1", "v15", "v2")
SCRIMMAGE = {"run", "pass_complete", "pass_incomplete", "sack", "interception", "fumble_lost"}
PASS_EVENTS = {"pass_complete", "pass_incomplete", "sack"}
BUCKETS = ("neg", "zero", "b1_3", "b4_9", "b10_19", "b20_39", "b40p")


def bucket(yards):
    if yards < 0:
        return "neg"
    if yards == 0:
        return "zero"
    if yards <= 3:
        return "b1_3"
    if yards <= 9:
        return "b4_9"
    if yards <= 19:
        return "b10_19"
    if yards <= 39:
        return "b20_39"
    return "b40p"


PERIOD = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4, "OT": 5}


def half_of(quarter):
    if quarter in (1, 2):
        return "h1"
    if quarter in (3, 4):
        return "h2"
    return "ot"


def team_rows(arm, game, seed, record, teams, home, complete_flag, status):
    # team_snaps is the simulator's own offensive snap count per team (lineup export); empty when not exported
    lineup = (record.get("realism") or {}).get("lineup") or {}
    team_snaps = {t: (lineup.get(t) or {}).get("team_snaps", "") for t in teams}
    drives = record["quarter_by_quarter"]["drive_summaries"]
    plays = record["realism"]["plays"]
    drive_team = {d["drive_index"]: d["offense_team"] for d in drives}
    scrim_by_drive = defaultdict(int)
    per_team = {t: defaultdict(float) for t in teams}
    for p in plays:
        team = drive_team.get(p["drive"])
        if team not in per_team:
            continue
        ev, dec = p["event_type"], p["decision_type"]
        q = p["state_before"]["quarter"]
        h = half_of(q)
        row = per_team[team]
        if ev in SCRIMMAGE:
            scrim_by_drive[p["drive"]] += 1
            row["plays"] += 1
            row["yards"] += p["yards_gained"]
            row["plays_" + h] += 1
            if dec == "run":
                row["run_plays"] += 1
                row["run_plays_" + h] += 1
            else:
                row["pass_plays"] += 1
                row["pass_plays_" + h] += 1
            if ev == "run":
                row["bucket_run_" + bucket(p["yards_gained"])] += 1
            if ev in PASS_EVENTS:
                row["bucket_pass_" + bucket(p["yards_gained"])] += 1
            if ev in ("interception", "fumble_lost"):
                row["turnovers"] += 1
    for d in drives:
        team = d["offense_team"]
        if team not in per_team or d["play_count"] < 1:
            continue
        row = per_team[team]
        row["drives"] += 1
        row["drive_net_yards"] += d["net_yards"]
        row["points_drive_sum"] += d["points"] or 0
        if (d["points"] or 0) > 0:
            row["scoring_drives"] += 1
        if d["terminal"] == "touchdown":
            row["touchdowns"] += 1
            row["touchdowns_" + half_of(PERIOD.get(d["scoring_period"], 5))] += 1
        if d["terminal"] == "field_goal_attempt":
            row["fg_attempts"] += 1
            if (d["points"] or 0) >= 3:
                row["fg_made"] += 1
        if d["terminal"] == "punt":
            row["punts"] += 1
            if scrim_by_drive[d["drive_index"]] == 3:
                row["three_and_outs"] += 1
        if d["terminal"] == "turnover_on_downs":
            row["turnovers_on_downs"] += 1
        row["drives_" + half_of(PERIOD.get(d["start_period"], 5))] += 1
    out = []
    pbp = record.get("points_by_period", {})
    for t in teams:
        row = per_team[t]
        pts = pbp.get(t, {})
        out.append([arm, game, seed, t, int(t == home), complete_flag, status,
                    int(row["drives"]), int(row["plays"]), int(row["run_plays"]), int(row["pass_plays"]),
                    int(row["yards"]), int(row["drive_net_yards"]), int(row["points_drive_sum"]),
                    int(row["touchdowns"]), int(row["fg_attempts"]), int(row["fg_made"]), int(row["punts"]),
                    int(row["three_and_outs"]), int(row["turnovers"]), int(row["turnovers_on_downs"]),
                    int(row["scoring_drives"]), int(row["plays_h1"]), int(row["plays_h2"]),
                    int(row["run_plays_h1"]), int(row["pass_plays_h1"]), int(row["run_plays_h2"]),
                    int(row["pass_plays_h2"]), int(row["drives_h1"]), int(row["drives_h2"]),
                    int(pts.get("Q1", 0) + pts.get("Q2", 0)), int(pts.get("Q3", 0) + pts.get("Q4", 0)),
                    int(pts.get("OT", 0)), int(row["touchdowns_h1"]), int(row["touchdowns_h2"]), team_snaps.get(t, "")]
                   + [int(row["bucket_run_" + b]) for b in BUCKETS]
                   + [int(row["bucket_pass_" + b]) for b in BUCKETS])
    return out


TEAM_HEADER = ["arm", "game_id", "seed", "team", "is_home", "complete_game", "status", "drives",
               "scrimmage_plays", "run_plays", "pass_plays", "scrimmage_yards", "drive_net_yards", "drive_points",
               "touchdowns", "fg_attempts", "fg_made", "punts", "three_and_outs", "turnovers", "turnovers_on_downs",
               "scoring_drives", "plays_h1", "plays_h2", "run_h1", "pass_h1", "run_h2", "pass_h2", "drives_h1",
               "drives_h2", "points_h1", "points_h2", "points_ot", "touchdowns_h1", "touchdowns_h2", "team_snaps"] + [
                   "run_" + b for b in BUCKETS] + [
                   "pass_" + b for b in BUCKETS]


def player_rows(arm, game, seed, record, complete_flag, status):
    out = []
    lineup = (record.get("realism") or {}).get("lineup") or {}
    for p in record["players"]:
        team = p.get("team")
        snaps = ((lineup.get(team) or {}).get("player_snaps") or {}).get(p.get("stable_player_id"), 0)
        rush, rec, pas = p.get("rushing") or {}, p.get("receiving") or {}, p.get("passing") or {}
        out.append([arm, game, seed, team, p.get("stable_player_id"), p.get("name"), p.get("position"),
                    complete_flag, status, int(snaps), int(rush.get("att", 0)), int(rush.get("yds", 0)),
                    int(rush.get("td", 0)), int(rec.get("tgt", 0)), int(rec.get("rec", 0)), int(rec.get("yds", 0)),
                    int(rec.get("td", 0)), int(pas.get("att", 0)), int(pas.get("comp", 0)), int(pas.get("yds", 0)),
                    int(pas.get("td", 0)), int(pas.get("int", 0)), int(pas.get("sacked", 0))])
    return out


PLAYER_HEADER = ["arm", "game_id", "seed", "team", "gsis_id", "name", "position", "complete_game", "status", "snaps",
                 "carries", "rush_yds", "rush_td", "targets", "receptions", "rec_yds", "rec_td", "pass_att",
                 "pass_comp", "pass_yds", "pass_td", "interceptions", "sacked"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)

    team_out = gzip.open(os.path.join(a.out, "team_seed.csv.gz"), "wt", newline="")
    player_out = gzip.open(os.path.join(a.out, "player_seed.csv.gz"), "wt", newline="")
    tw, pw = csv.writer(team_out), csv.writer(player_out)
    tw.writerow(TEAM_HEADER)
    pw.writerow(PLAYER_HEADER)
    counts = defaultdict(int)
    for path in sorted(glob.glob(os.path.join(a.root, "*", "*.json.gz"))):
        arm = os.path.basename(os.path.dirname(path))
        batch = json.load(gzip.open(path, "rt"))
        game = batch["game_id"]
        home = batch["teams"]["home"]
        teams = [batch["teams"]["away"], home]
        complete = {o["seed"]: (bool(o.get("complete_game")), o.get("status")) for o in batch["summary"]["outcomes"]}
        box_path = path[:-len(".json.gz")] + ".boxscores.jsonl.gz"
        if not os.path.exists(box_path):
            counts["missing_boxscore_file"] += 1
            continue
        for line in gzip.open(box_path, "rt"):
            rec = json.loads(line)
            if rec.get("type") != "game":
                continue
            seed = rec["seed"]
            flag, status = complete.get(seed, (False, "unknown"))
            counts["records"] += 1
            counts["records_" + ("complete" if flag else "not_complete")] += 1
            for row in team_rows(arm, game, seed, rec, teams, home, int(flag), status):
                tw.writerow(row)
            for row in player_rows(arm, game, seed, rec, int(flag), status):
                pw.writerow(row)
    team_out.close()
    player_out.close()
    with open(os.path.join(a.out, "counts.json"), "w") as f:
        json.dump(dict(counts), f, indent=2, sort_keys=True)
    print(json.dumps(dict(counts), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
