#!/usr/bin/env python3
"""observed_2025_metrics.py -- observed 2025 regular-season team-game and player-game realism metrics.

Source: the nflverse 2025 play-by-play, snap counts, schedule and player table in the lp-snapshots tree. The
definitions match seed_metrics.py field for field, so a simulated seed and an observed game are computed the same
way (see that file's docstring). Two differences are inherent and reported in the results report, not hidden here:
  * nflverse play_type 'run' includes quarterback scrambles; the simulator's decision_type 'run' is its own label.
  * Snap counts come from the snap-count file keyed by PFR player id; they are mapped to GSIS ids through the
    players table and a player with no mapping keeps snaps empty rather than zero.

Runs locally (pandas). Writes observed/ under --out.

Usage: python3 observed_2025_metrics.py --out docs/research/SLC-2025-REALISM-RESULTS-2026-11-05/observed
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

RAW = "/root/lp-snapshots/nfl-backfill-2026-10-27/raw"
BUCKETS = ("neg", "zero", "b1_3", "b4_9", "b10_19", "b20_39", "b40p")
SCRIMMAGE_TYPES = ("run", "pass")
DRIVE_TYPES = ("run", "pass", "punt", "field_goal", "qb_kneel", "qb_spike")


def bucket_of(yards):
    labels = np.select([yards < 0, yards == 0, yards <= 3, yards <= 9, yards <= 19, yards <= 39],
                       ["neg", "zero", "b1_3", "b4_9", "b10_19", "b20_39"], default="b40p")
    return labels


def load_plays():
    cols = ["game_id", "season_type", "week", "posteam", "defteam", "qtr", "play_type", "yards_gained",
            "fixed_drive", "fixed_drive_result", "touchdown", "td_team", "field_goal_result", "interception",
            "fumble_lost", "sack", "complete_pass", "pass_attempt", "rusher_player_id", "receiver_player_id",
            "passer_player_id", "rushing_yards", "receiving_yards", "total_home_score", "total_away_score",
            "home_team", "away_team"]
    df = pd.read_parquet(f"{RAW}/pbp/play_by_play_2025.parquet")
    df = df[df.season_type == "REG"][[c for c in cols if c in df.columns]].copy()
    return df


def team_game_rows(plays, schedule):
    out = []
    for game_id, g in plays.groupby("game_id", sort=True):
        home = g.home_team.dropna().iloc[0]
        away = g.away_team.dropna().iloc[0]
        final = schedule.set_index("game_id").loc[game_id]
        final_scores = {home: float(final.home_score), away: float(final.away_score)}
        # score at the end of Q2, from the running total on the last play of quarter 2
        q2 = g[(g.qtr == 2) & g.total_home_score.notna()]
        end_q2 = {home: float(q2.total_home_score.iloc[-1]) if len(q2) else np.nan,
                  away: float(q2.total_away_score.iloc[-1]) if len(q2) else np.nan}
        for team, side_home in ((away, 0), (home, 1)):
            t = g[g.posteam == team]
            drive_plays = t[t.play_type.isin(DRIVE_TYPES)]
            drives = drive_plays.fixed_drive.dropna().unique()
            scrim = t[t.play_type.isin(SCRIMMAGE_TYPES)]
            runs = scrim[scrim.play_type == "run"]
            passes = scrim[scrim.play_type == "pass"]
            n_drives = len(drives)
            drive_res = t.dropna(subset=["fixed_drive"]).groupby("fixed_drive").fixed_drive_result.first()
            drive_start_qtr = drive_plays.dropna(subset=["fixed_drive"]).groupby("fixed_drive").qtr.min()
            scrim_by_drive = scrim.groupby("fixed_drive").size()
            three = int(sum(1 for d, r in drive_res.items() if r == "Punt" and scrim_by_drive.get(d, 0) == 3))
            bucket_run = bucket_of(runs[(runs.fumble_lost != 1) & (runs.interception != 1)].yards_gained.fillna(0).values)
            pass_ok = passes[(passes.interception != 1) & (passes.fumble_lost != 1)]
            bucket_pass = bucket_of(pass_ok.yards_gained.fillna(0).values)
            td = int(((g.td_team == team) & g.play_type.isin(SCRIMMAGE_TYPES)).sum())
            h1 = scrim[scrim.qtr.isin([1, 2])]
            h2 = scrim[scrim.qtr.isin([3, 4])]
            row = {
                "game_id": game_id, "team": team, "is_home": side_home, "week": int(g.week.iloc[0]),
                "drives": n_drives,
                "scrimmage_plays": len(scrim), "run_plays": len(runs), "pass_plays": len(passes),
                "scrimmage_yards": float(scrim.yards_gained.fillna(0).sum()),
                "touchdowns": td,
                "touchdowns_h1": int(((g.td_team == team) & g.play_type.isin(SCRIMMAGE_TYPES) & g.qtr.isin([1, 2])).sum()),
                "touchdowns_h2": int(((g.td_team == team) & g.play_type.isin(SCRIMMAGE_TYPES) & g.qtr.isin([3, 4])).sum()),
                "fg_attempts": int((t.play_type == "field_goal").sum()),
                "fg_made": int((t.field_goal_result == "made").sum()),
                "punts": int((t.play_type == "punt").sum()),
                "three_and_outs": three,
                "turnovers": int(((t.interception == 1) | (t.fumble_lost == 1))[t.play_type.isin(SCRIMMAGE_TYPES)].sum()),
                "turnovers_on_downs": int((drive_res == "Turnover on downs").sum()),
                "scoring_drives": int(drive_res.isin(["Touchdown", "Field goal"]).sum()),
                "plays_h1": len(h1), "plays_h2": len(h2),
                "run_h1": int((h1.play_type == "run").sum()), "pass_h1": int((h1.play_type == "pass").sum()),
                "run_h2": int((h2.play_type == "run").sum()), "pass_h2": int((h2.play_type == "pass").sum()),
                "drives_h1": int((drive_start_qtr <= 2).sum()),
                "drives_h2": int((drive_start_qtr >= 3).sum()),
                "points": final_scores[team],
                "points_h1": end_q2[team] if not np.isnan(end_q2[team]) else np.nan,
            }
            row["points_h2"] = row["points"] - row["points_h1"] if not np.isnan(row["points_h1"]) else np.nan
            row["points_per_drive"] = row["points"] / n_drives if n_drives else np.nan
            row["scrimmage_yards_per_drive"] = row["scrimmage_yards"] / n_drives if n_drives else np.nan
            row["plays_per_drive"] = len(scrim) / n_drives if n_drives else np.nan
            run_counts = pd.Series(bucket_run).value_counts().reindex(BUCKETS, fill_value=0)
            pass_counts = pd.Series(bucket_pass).value_counts().reindex(BUCKETS, fill_value=0)
            for b in BUCKETS:
                row["run_" + b] = int(run_counts[b])
                row["pass_" + b] = int(pass_counts[b])
            out.append(row)
    return pd.DataFrame(out)


def player_game_rows(plays, snaps, players):
    # drop incomplete rows before zipping: dropping each column separately misaligns the pairs
    pairs = players.dropna(subset=["pfr_id", "gsis_id"]).drop_duplicates()
    if pairs.pfr_id.duplicated().any():
        raise SystemExit("players: %d pfr_id values map to more than one gsis_id" % pairs.pfr_id.duplicated().sum())
    pfr_to_gsis = dict(zip(pairs.pfr_id, pairs.gsis_id))
    rows = []
    run = plays[(plays.play_type == "run") & plays.rusher_player_id.notna()]
    pas = plays[(plays.play_type == "pass") & plays.passer_player_id.notna()]
    tgt = plays[(plays.play_type == "pass") & plays.receiver_player_id.notna() & (plays.sack != 1)]
    keys = {}

    def bump(game, team, gsis, field, value):
        keys.setdefault((game, team, gsis), {})
        keys[(game, team, gsis)][field] = keys[(game, team, gsis)].get(field, 0) + value

    for r in run.itertuples():
        bump(r.game_id, r.posteam, r.rusher_player_id, "carries", 1)
        bump(r.game_id, r.posteam, r.rusher_player_id, "rush_yds", float(r.rushing_yards or 0))
    for r in tgt.itertuples():
        bump(r.game_id, r.posteam, r.receiver_player_id, "targets", 1)
        bump(r.game_id, r.posteam, r.receiver_player_id, "receptions", int(r.complete_pass == 1))
        bump(r.game_id, r.posteam, r.receiver_player_id, "rec_yds", float(r.receiving_yards or 0))
    for r in pas[pas.sack != 1].itertuples():
        bump(r.game_id, r.posteam, r.passer_player_id, "pass_att", 1)
        bump(r.game_id, r.posteam, r.passer_player_id, "pass_comp", int(r.complete_pass == 1))
    for (game, team, gsis), vals in keys.items():
        rows.append(dict(game_id=game, team=team, gsis_id=gsis, **vals))
    frame = pd.DataFrame(rows)
    snap = snaps.copy()
    snap["gsis_id"] = snap.pfr_player_id.map(pfr_to_gsis)
    snap = snap.dropna(subset=["gsis_id"])
    snap = snap.groupby(["game_id", "team", "gsis_id"], as_index=False).offense_snaps.sum()
    frame = frame.merge(snap.rename(columns={"offense_snaps": "snaps"}), on=["game_id", "team", "gsis_id"], how="outer")
    return frame.fillna(0)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)

    plays = load_plays()
    schedule = pd.read_parquet(f"{RAW}/schedules/games.parquet")
    schedule = schedule[(schedule.season == 2025) & (schedule.game_type == "REG")]
    snaps = pd.read_parquet(f"{RAW}/snap_counts/snap_counts_2025.parquet")
    snaps = snaps[snaps.game_type == "REG"]
    players = pd.read_parquet(f"{RAW}/players/players.parquet", columns=["gsis_id", "pfr_id"])

    team_game = team_game_rows(plays, schedule)
    # team snaps: the largest offensive snap count in the team-game, over every offensive player including linemen
    team_snaps = snaps.groupby(["game_id", "team"], as_index=False).offense_snaps.max().rename(
        columns={"offense_snaps": "team_snaps"})
    team_game = team_game.merge(team_snaps, on=["game_id", "team"], how="left")
    if team_game.team_snaps.isna().any():
        raise SystemExit("team snaps missing for %d team-games" % team_game.team_snaps.isna().sum())
    team_game.to_csv(os.path.join(a.out, "observed_team_game.csv"), index=False)
    player_game = player_game_rows(plays, snaps, players)
    player_game.to_csv(os.path.join(a.out, "observed_player_game.csv"), index=False)
    print("games: %d; team-games: %d; player-game rows: %d" % (
        team_game.game_id.nunique(), len(team_game), len(player_game)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
