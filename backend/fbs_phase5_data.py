#!/usr/bin/env python3
"""fbs_phase5_data.py -- build the Phase 5 data layer (read-only archive).

Outputs (under research/fbs/phase5/cache/):
  team_games.parquet       one row per team-game, regular season, FBS-any, 2018-2025
  player_games.parquet     one row per player-game (game roster or box), 2018-2025
  props_2026.parquet       pre-kickoff two-sided 2026 NCAAF prop groups, deduped
  data_manifest.json      counts and source files

No production DB is written. The dev DB is opened mode=ro.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

ROOT = "/root/lp-fbs-archive"
PARQUET = os.path.join(ROOT, "research/fbs/parquet")
OUT = os.path.join(ROOT, "research/fbs/phase5/cache")
DEV_DB = "/root/legendarypicks/backend/data/picks.dev.db"
SEASONS = list(range(2018, 2026))

CORE_STATS = [
    "pass_attempts", "completions", "passing_yards", "passing_tds", "interceptions_thrown",
    "rush_attempts", "rushing_yards", "rushing_tds",
    "targets", "receptions", "receiving_yards", "receiving_tds",
]


def norm_name(s) -> str:
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return ""
    s = str(s).lower()
    s = s.replace("&", " and ")
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\.?\b", "", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def to_num(s):
    return pd.to_numeric(s, errors="coerce")


def load_schedules(seasons):
    frames = []
    for season in seasons:
        p = os.path.join(PARQUET, "cfb_schedules", f"cfb_schedules_{season}.parquet")
        d = pd.read_parquet(p)
        d = d[(d.season_type == "regular") & (d.fbs_participant == True)].copy()
        d["season"] = season
        d["game_id"] = d["game_id"].astype("int64")
        frames.append(d)
    s = pd.concat(frames, ignore_index=True)
    s = s.drop_duplicates("game_id")
    return s


def team_ids_for(row, team_name):
    """Map a PBP/NCAA team name to the schedule home/away id."""
    n = norm_name(team_name)
    if norm_name(row.home_team) == n:
        return int(row.home_id)
    if norm_name(row.away_team) == n:
        return int(row.away_id)
    # common abbreviation fallback
    if norm_name(row.home_abbreviation) == n:
        return int(row.home_id)
    if norm_name(row.away_abbreviation) == n:
        return int(row.away_id)
    return -1


def build_team_games(season, sched):
    p = os.path.join(PARQUET, "cfbfastR_cfb_pbp", f"play_by_play_{season}.parquet")
    cols = ["game_id", "pos_team", "def_pos_team", "home_team", "away_team",
            "home_team_id", "away_team_id", "pass", "rush", "sack", "pass_attempt",
            "completion", "int", "pass_td", "rush_td", "touchdown", "fumble_vec",
            "yds_rushed", "yds_receiving", "yds_sacked", "drive_id"]
    d = pd.read_parquet(p, columns=cols)
    games = set(sched.game_id)
    d = d[d.game_id.isin(games)].copy()
    d["team_id"] = np.where(d.pos_team == d.home_team, d.home_team_id, d.away_team_id)
    d["opp_id"] = np.where(d.pos_team == d.home_team, d.away_team_id, d.home_team_id)
    # if pos_team is an abbreviation, map by normalized name
    bad = d.team_id.isna() | (d.team_id < 0)
    if bad.any():
        smap = {int(r.game_id): r for _, r in sched.iterrows()}
        for i in d.index[bad]:
            r = smap.get(int(d.at[i, "game_id"]))
            if r is not None:
                tid = team_ids_for(r, d.at[i, "pos_team"])
                d.at[i, "team_id"] = tid
                d.at[i, "opp_id"] = int(r.away_id) if tid == int(r.home_id) else int(r.home_id)
    d = d[d.team_id.notna() & (d.team_id >= 0)]
    for c in ["pass", "rush", "sack", "pass_attempt", "completion", "int", "pass_td",
              "rush_td", "touchdown", "fumble_vec"]:
        d[c] = d[c].fillna(0).astype(float)
    for c in ["yds_rushed", "yds_receiving", "yds_sacked"]:
        d[c] = d[c].fillna(0).astype(float)
    d["play"] = ((d["pass"] > 0) | (d["rush"] > 0)).astype(float)
    g = d.groupby(["game_id", "team_id"], as_index=False).agg(
        plays=("play", "sum"),
        pass_plays=("pass", "sum"),
        rush_plays=("rush", "sum"),
        sacks=("sack", "sum"),
        pass_attempts=("pass_attempt", "sum"),
        completions=("completion", "sum"),
        interceptions=("int", "sum"),
        pass_tds=("pass_td", "sum"),
        rush_tds=("rush_td", "sum"),
        touchdowns=("touchdown", "sum"),
        fumbles=("fumble_vec", "sum"),
        yds_rushed=("yds_rushed", "sum"),
        yds_receiving=("yds_receiving", "sum"),
        yds_sacked=("yds_sacked", "sum"),
        drives=("drive_id", "nunique"),
    )
    g["team_id"] = g.team_id.astype("int64")
    g["game_id"] = g.game_id.astype("int64")
    g["rush_yards"] = g.yds_rushed + g.yds_sacked
    g["pass_yards"] = g.yds_receiving
    g["pace"] = g.plays
    g["pass_rate"] = np.where(g.plays > 0, g.pass_plays / g.plays, np.nan)
    g["logit_pass_rate"] = np.log((g.pass_rate.clip(1e-4, 1 - 1e-4)) /
                                  (1 - g.pass_rate.clip(1e-4, 1 - 1e-4)))

    # ---- union fallback: games cfbfastR does not cover, use ESPN then NCAA
    missing = set(sched.game_id) - set(g.game_id)
    extra = []
    if missing:
        ep = os.path.join(PARQUET, "espn_cfb_pbp", f"play_by_play_{season}.parquet")
        try:
            e = pd.read_parquet(ep, columns=[
                "game_id", "pos_team_id", "def_pos_team_id", "pass", "rush", "sack",
                "pass_attempt", "completion", "int", "pass_td", "rush_td", "touchdown",
                "fumble_vec", "yds_rushed", "yds_receiving", "yds_sacked", "drive.id"])
            e = e[e.game_id.isin(missing)].copy()
            if len(e):
                for c in ["pass", "rush", "sack", "pass_attempt", "completion", "int",
                          "pass_td", "rush_td", "touchdown", "fumble_vec"]:
                    e[c] = e[c].fillna(0).astype(float)
                for c in ["yds_rushed", "yds_receiving", "yds_sacked"]:
                    e[c] = e[c].fillna(0).astype(float)
                e["play"] = ((e["pass"] > 0) | (e["rush"] > 0)).astype(float)
                eg = e.groupby(["game_id", "pos_team_id"], as_index=False).agg(
                    plays=("play", "sum"), pass_plays=("pass", "sum"),
                    rush_plays=("rush", "sum"), sacks=("sack", "sum"),
                    pass_attempts=("pass_attempt", "sum"), completions=("completion", "sum"),
                    interceptions=("int", "sum"), pass_tds=("pass_td", "sum"),
                    rush_tds=("rush_td", "sum"), touchdowns=("touchdown", "sum"),
                    fumbles=("fumble_vec", "sum"), yds_rushed=("yds_rushed", "sum"),
                    yds_receiving=("yds_receiving", "sum"), yds_sacked=("yds_sacked", "sum"),
                    opp_id=("def_pos_team_id", "first"), drives=("drive.id", "nunique"))
                eg = eg.rename(columns={"pos_team_id": "team_id"})
                eg["team_id"] = eg.team_id.astype("int64")
                eg["game_id"] = eg.game_id.astype("int64")
                eg["opp_id"] = eg.opp_id.astype("int64")
                eg["rush_yards"] = eg.yds_rushed + eg.yds_sacked
                eg["pass_yards"] = eg.yds_receiving
                eg["pace"] = eg.plays
                eg["pass_rate"] = np.where(eg.plays > 0, eg.pass_plays / eg.plays, np.nan)
                eg["logit_pass_rate"] = np.log((eg.pass_rate.clip(1e-4, 1 - 1e-4)) /
                                               (1 - eg.pass_rate.clip(1e-4, 1 - 1e-4)))
                extra.append(eg)
                missing = missing - set(eg.game_id)
        except Exception as exc:
            print(f"  ESPN fallback warning {season}: {exc}", file=sys.stderr)
    if missing:
        npth = os.path.join(PARQUET, "ncaa_mfb_pbp_cfbfastr",
                            f"ncaa_mfb_pbp_cfbfastr_{season}.parquet")
        try:
            n = pd.read_parquet(npth, columns=[
                "espn_game_id", "pos_team", "home", "away", "pass", "rush", "sack",
                "pass_attempt", "completion", "int", "pass_td", "rush_td", "touchdown",
                "fumble_vec", "yds_rushed", "yds_receiving", "yds_sacked", "drive_id"])
            n["game_id"] = pd.to_numeric(n.espn_game_id, errors="coerce")
            n = n[n.game_id.isin(missing)].copy()
            if len(n):
                n["game_id"] = n.game_id.astype("int64")
                sm = sched.set_index("game_id")
                n = n.merge(sm[["home_id", "away_id"]], left_on="game_id", right_index=True, how="left")
                n["team_id"] = np.where(n.pos_team == n.home, n.home_id,
                                        np.where(n.pos_team == n.away, n.away_id, -1))
                n["opp_id"] = np.where(n.team_id == n.home_id, n.away_id, n.home_id)
                n = n[n.team_id >= 0].copy()
                for c in ["pass", "rush", "sack", "pass_attempt", "completion", "int",
                          "pass_td", "rush_td", "touchdown", "fumble_vec"]:
                    n[c] = n[c].fillna(0).astype(float)
                for c in ["yds_rushed", "yds_receiving", "yds_sacked"]:
                    n[c] = n[c].fillna(0).astype(float)
                n["play"] = ((n["pass"] > 0) | (n["rush"] > 0)).astype(float)
                ng = n.groupby(["game_id", "team_id"], as_index=False).agg(
                    plays=("play", "sum"), pass_plays=("pass", "sum"),
                    rush_plays=("rush", "sum"), sacks=("sack", "sum"),
                    pass_attempts=("pass_attempt", "sum"), completions=("completion", "sum"),
                    interceptions=("int", "sum"), pass_tds=("pass_td", "sum"),
                    rush_tds=("rush_td", "sum"), touchdowns=("touchdown", "sum"),
                    fumbles=("fumble_vec", "sum"), yds_rushed=("yds_rushed", "sum"),
                    yds_receiving=("yds_receiving", "sum"), yds_sacked=("yds_sacked", "sum"),
                    opp_id=("opp_id", "first"), drives=("drive_id", "nunique"))
                ng["rush_yards"] = ng.yds_rushed + ng.yds_sacked
                ng["pass_yards"] = ng.yds_receiving
                ng["pace"] = ng.plays
                ng["pass_rate"] = np.where(ng.plays > 0, ng.pass_plays / ng.plays, np.nan)
                ng["logit_pass_rate"] = np.log((ng.pass_rate.clip(1e-4, 1 - 1e-4)) /
                                               (1 - ng.pass_rate.clip(1e-4, 1 - 1e-4)))
                extra.append(ng)
        except Exception as exc:
            print(f"  NCAA fallback warning {season}: {exc}", file=sys.stderr)
    if extra:
        g = pd.concat([g] + extra, ignore_index=True, sort=False)
    g = g.drop_duplicates(["game_id", "team_id"])
    for c in ["rush_yards", "pass_yards", "pace", "pass_rate", "logit_pass_rate"]:
        if c not in g:
            g[c] = np.nan
    s = sched[["game_id", "season", "week", "start_date", "home_id", "away_id",
               "home_team", "away_team", "home_division", "away_division",
               "home_points", "away_points", "neutral_site", "fbs_game", "fbs_participant"]].copy()
    s["game_id"] = s["game_id"].astype("int64")
    g = g.merge(s, on="game_id", how="left", validate="many_to_one")
    g["opp_id"] = np.where(g.team_id == g.home_id, g.away_id, g.home_id)
    g["home"] = (g.team_id == g.home_id).astype(int)
    g["neutral"] = g.neutral_site.astype(int)
    g["is_fcs"] = np.where(g.home == 1, (g.away_division == "fcs").astype(int),
                           (g.home_division == "fcs").astype(int))
    g["points_for"] = np.where(g.home == 1, g.home_points, g.away_points)
    g["points_against"] = np.where(g.home == 1, g.away_points, g.home_points)
    g["total_points"] = g.points_for + g.points_against
    g["team_name"] = np.where(g.home == 1, g.home_team, g.away_team)
    g["opp_name"] = np.where(g.home == 1, g.away_team, g.home_team)
    # rest days
    g["start_dt"] = pd.to_datetime(g.start_date, utc=True, errors="coerce")
    g = g.sort_values(["season", "team_id", "start_dt", "week"])
    g["rest"] = g.groupby(["season", "team_id"])["start_dt"].diff().dt.total_seconds() / 86400.0
    g["rest"] = g["rest"].fillna(7.0).clip(0, 30)
    g["season"] = g.season.astype(int)
    g["week"] = g.week.astype(int)
    return g


def parse_box(season, sched):
    p = os.path.join(PARQUET, "espn_cfb_player_box", f"player_box_{season}.parquet")
    b = pd.read_parquet(p)
    b = b[b.game_id.isin(set(sched.game_id))].copy()
    b["athlete_id"] = to_num(b.athlete_id)
    b = b[b.athlete_id.notna()]
    b["athlete_id"] = b.athlete_id.astype("int64")
    b["game_id"] = b.game_id.astype("int64")
    b["team_id"] = b.team_id.astype("int64")
    b["category"] = b.category.astype(str).str.lower()
    rows = []
    # passing: the dedicated columns are populated in every season; stat_1..5 are a partial fallback
    m = b[b.category == "passing"].copy()
    if len(m):
        ded = m.get("completions/passingAttempts", pd.Series(index=m.index, dtype=object)).astype(str)
        parts = ded.str.extract(r"(\d+)\s*/\s*(\d+)")
        st = m.stat_1.astype(str).str.extract(r"(\d+)\s*/\s*(\d+)")
        m["completions"] = pd.to_numeric(parts[0].fillna(st[0]), errors="coerce").fillna(0)
        m["pass_attempts"] = pd.to_numeric(parts[1].fillna(st[1]), errors="coerce").fillna(0)
        m["passing_yards"] = pd.to_numeric(
            m.get("passingYards", pd.Series(index=m.index, dtype=float)), errors="coerce").fillna(
            pd.to_numeric(m.stat_2, errors="coerce")).fillna(0)
        m["passing_tds"] = pd.to_numeric(
            m.get("passingTouchdowns", pd.Series(index=m.index, dtype=float)), errors="coerce").fillna(
            pd.to_numeric(m.stat_4, errors="coerce")).fillna(0)
        rows.append(m[["game_id", "team_id", "athlete_id", "athlete_name",
                       "completions", "pass_attempts", "passing_yards", "passing_tds"]])
    # rushing
    m = b[b.category == "rushing"].copy()
    if len(m):
        m["rush_attempts"] = to_num(m.rushingAttempts).fillna(0)
        m["rushing_yards"] = to_num(m.rushingYards).fillna(0)
        m["rushing_tds"] = to_num(m.rushingTouchdowns).fillna(0)
        m["fumbles"] = to_num(m.fumbles).fillna(0)
        m["fumbles_lost"] = to_num(m.fumblesLost).fillna(0)
        rows.append(m[["game_id", "team_id", "athlete_id", "athlete_name",
                       "rush_attempts", "rushing_yards", "rushing_tds", "fumbles", "fumbles_lost"]])
    # receiving
    m = b[b.category == "receiving"].copy()
    if len(m):
        m["receptions"] = to_num(m.receptions).fillna(0)
        m["receiving_yards"] = to_num(m.receivingYards).fillna(0)
        m["receiving_tds"] = to_num(m.receivingTouchdowns).fillna(0)
        rows.append(m[["game_id", "team_id", "athlete_id", "athlete_name",
                       "receptions", "receiving_yards", "receiving_tds"]])
    if not rows:
        return pd.DataFrame(columns=["game_id", "team_id", "athlete_id"])
    out = rows[0]
    for r in rows[1:]:
        out = out.merge(r, on=["game_id", "team_id", "athlete_id", "athlete_name"], how="outer")
    for c in ["completions", "pass_attempts", "passing_yards", "passing_tds",
              "rush_attempts", "rushing_yards", "rushing_tds", "fumbles", "fumbles_lost",
              "receptions", "receiving_yards", "receiving_tds"]:
        if c not in out:
            out[c] = 0.0
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0.0)
    out = out.groupby(["game_id", "team_id", "athlete_id"], as_index=False).agg(
        athlete_name=("athlete_name", "first"), **{c: (c, "sum") for c in [
            "completions", "pass_attempts", "passing_yards", "passing_tds",
            "rush_attempts", "rushing_yards", "rushing_tds", "fumbles", "fumbles_lost",
            "receptions", "receiving_yards", "receiving_tds"]})
    return out


def build_player_games(season, sched):
    box = parse_box(season, sched)
    # game rosters: all players with a game-roster row
    gp = os.path.join(PARQUET, "espn_cfb_game_rosters", f"game_rosters_{season}.parquet")
    gr = pd.read_parquet(gp, columns=["game_id", "team_id", "athlete_id", "full_name",
                                      "active", "starter", "did_not_play"])
    gr = gr[gr.game_id.isin(set(sched.game_id))].copy()
    gr["game_id"] = gr.game_id.astype("int64")
    gr["team_id"] = gr.team_id.astype("int64")
    gr["athlete_id"] = gr.athlete_id.astype("int64")
    gr = gr.drop_duplicates(["game_id", "team_id", "athlete_id"])
    gr = gr.rename(columns={"full_name": "athlete_name"})
    # union by keys
    keys = pd.concat([
        gr[["game_id", "team_id", "athlete_id", "athlete_name"]],
        box[["game_id", "team_id", "athlete_id", "athlete_name"]],
    ], ignore_index=True).drop_duplicates(["game_id", "team_id", "athlete_id"])
    keys = keys.merge(box.drop(columns=["athlete_name"]), on=["game_id", "team_id", "athlete_id"], how="left")
    for c in ["completions", "pass_attempts", "passing_yards", "passing_tds",
              "rush_attempts", "rushing_yards", "rushing_tds", "fumbles", "fumbles_lost",
              "receptions", "receiving_yards", "receiving_tds"]:
        keys[c] = pd.to_numeric(keys.get(c, 0), errors="coerce").fillna(0.0)
    # position from season roster
    rp = os.path.join(PARQUET, "espn_cfb_rosters", f"cfb_rosters_{season}.parquet")
    try:
        ro = pd.read_parquet(rp, columns=["team_id", "athlete_id", "position", "position_abbreviation"])
        ro = ro.drop_duplicates(["team_id", "athlete_id"])
        keys = keys.merge(ro, on=["team_id", "athlete_id"], how="left")
    except Exception:
        keys["position"] = "UNK"
        keys["position_abbreviation"] = "UNK"
    keys["position"] = keys["position"].fillna("UNK")
    keys["season"] = season

    # ---- targets from NCAA cfbfastR names, mapped to athlete_id within game/team
    np_ = os.path.join(PARQUET, "ncaa_mfb_pbp_cfbfastr",
                       f"ncaa_mfb_pbp_cfbfastr_{season}.parquet")
    targets = pd.DataFrame(columns=["game_id", "team_id", "athlete_id", "targets"])
    try:
        # ESPN team ids per game, so NCAA abbreviations never need cross-source name matching
        ep = os.path.join(PARQUET, "espn_cfb_pbp", f"play_by_play_{season}.parquet")
        eg = pd.read_parquet(ep, columns=["game_id", "homeTeamId", "awayTeamId"])
        eg = eg.drop_duplicates("game_id")
        eg["game_id"] = eg.game_id.astype("int64")
        n = pd.read_parquet(np_, columns=["espn_game_id", "pos_team", "home", "away",
                                          "pass_attempt", "target", "receiver_player_name"])
        n = n[(n.pass_attempt == True) & n.receiver_player_name.notna()].copy()
        n["game_id"] = pd.to_numeric(n.espn_game_id, errors="coerce")
        n = n[n.game_id.notna()]
        n["game_id"] = n.game_id.astype("int64")
        n = n[n.game_id.isin(set(sched.game_id))]
        n = n.merge(eg, on="game_id", how="left")
        n["team_id"] = np.where(n.pos_team == n.home, n.homeTeamId,
                                np.where(n.pos_team == n.away, n.awayTeamId, -1))
        n = n[n.team_id.notna() & (n.team_id >= 0)].copy()
        n["team_id"] = n.team_id.astype("int64")
        # name -> athlete map from every game-roster/box player in the season
        nm = keys[["game_id", "team_id", "athlete_id", "athlete_name"]].copy()
        nm["norm"] = nm.athlete_name.map(norm_name)
        nm = nm[nm.norm != ""].drop_duplicates(["game_id", "team_id", "norm"])
        n["norm"] = n.receiver_player_name.map(norm_name)
        n = n.merge(nm, on=["game_id", "team_id", "norm"], how="left")
        # fallback: unique last-name match within team-game
        miss = n[n.athlete_id.isna()].copy()
        if len(miss):
            last = nm.assign(last=nm.norm.str.split().str[-1])
            last = last[last["last"] != ""].drop_duplicates(["game_id", "team_id", "last"])
            miss["last"] = miss.norm.str.split().str[-1]
            miss = miss.drop(columns=["athlete_id", "athlete_name"]).merge(
                last[["game_id", "team_id", "last", "athlete_id", "athlete_name"]],
                on=["game_id", "team_id", "last"], how="left")
            n = pd.concat([n[n.athlete_id.notna()], miss], ignore_index=True)
        t = n[n.athlete_id.notna()].groupby(["game_id", "team_id", "athlete_id"], as_index=False).size()
        t = t.rename(columns={"size": "targets"})
        targets = t
    except Exception as e:
        import traceback
        print(f"  targets warning {season}: {e}", file=sys.stderr)
        traceback.print_exc()
    keys = keys.merge(targets, on=["game_id", "team_id", "athlete_id"], how="left")
    keys["targets"] = pd.to_numeric(keys.targets, errors="coerce").fillna(0.0)
    # targets cannot be below receptions
    keys["targets"] = np.maximum(keys.targets, keys.receptions)

    # ---- INTs thrown from ESPN PBP (passer id)
    ints = pd.DataFrame(columns=["game_id", "athlete_id", "interceptions_thrown"])
    try:
        ep = os.path.join(PARQUET, "espn_cfb_pbp", f"play_by_play_{season}.parquet")
        e = pd.read_parquet(ep, columns=["game_id", "passer_player_id", "int"])
        e = e[(e["int"] == True) & e.passer_player_id.notna()]
        e["athlete_id"] = pd.to_numeric(e.passer_player_id, errors="coerce")
        e = e[e.athlete_id.notna()]
        e["athlete_id"] = e.athlete_id.astype("int64")
        e["game_id"] = e.game_id.astype("int64")
        ints = e.groupby(["game_id", "athlete_id"], as_index=False).size().rename(
            columns={"size": "interceptions_thrown"})
    except Exception as e:
        print(f"  ints warning {season}: {e}", file=sys.stderr)
    keys = keys.merge(ints, on=["game_id", "athlete_id"], how="left")
    keys["interceptions_thrown"] = pd.to_numeric(keys.interceptions_thrown, errors="coerce").fillna(0.0)
    return keys


def build_props_2026():
    con = sqlite3.connect(f"file:{DEV_DB}?mode=ro", uri=True)
    q = """SELECT p.id AS prop_id, p.game_id AS db_game_id, p.player_id, p.market, p.line,
                  p.side, p.odds, p.captured_at,
                  g.league, g.home, g.away, g.start_time, g.espn_event_id,
                  pl.name AS player_name, pl.espn_id, pl.team AS player_team, pl.position,
                  pr.actual_value, pr.hit
           FROM props p
           JOIN prop_games g ON p.game_id = g.id
           LEFT JOIN players pl ON p.player_id = pl.id
           LEFT JOIN prop_results pr ON pr.prop_id = p.id
           WHERE g.league = 'ncaaf'"""
    d = pd.read_sql_query(q, con)
    con.close()
    d["captured_at"] = pd.to_datetime(d.captured_at, utc=True, errors="coerce")
    d["start_time"] = pd.to_datetime(d.start_time, utc=True, errors="coerce")
    d = d[d.captured_at.notna() & d.start_time.notna()]
    d = d[d.captured_at < d.start_time].copy()
    d["line"] = pd.to_numeric(d.line, errors="coerce")
    d["odds"] = pd.to_numeric(d.odds, errors="coerce")
    d = d[d.line.notna() & d.odds.notna()]
    # group the paired over/under at one capture
    key = ["db_game_id", "player_id", "market", "line", "captured_at"]
    rows = []
    for k, grp in d.groupby(key, sort=False):
        ov = grp[grp.side == "over"]
        un = grp[grp.side == "under"]
        if not len(ov) or not len(un):
            continue
        # median odds per side (duplicates exist in the live board)
        oo = float(np.median(ov.odds.values))
        ou = float(np.median(un.odds.values))
        def imp(a):
            return (-a / (-a + 100.0)) if a < 0 else (100.0 / (a + 100.0))
        po, pu = imp(oo), imp(ou)
        if po <= 0 or pu <= 0:
            continue
        p_market = po / (po + pu)
        # outcome: over result preferred, under fallback; push excluded
        actual = None
        for side_df in (ov, un):
            vals = side_df.actual_value.dropna()
            if len(vals):
                actual = float(vals.iloc[0])
                break
        if actual is None:
            y = None
        elif actual == float(k[3]):
            y = None  # push
        else:
            y = 1 if actual > float(k[3]) else 0
        first = grp.iloc[0]
        rows.append({
            "db_game_id": int(k[0]), "player_id": int(k[1]), "market": k[2],
            "line": float(k[3]), "captured_at": k[4],
            "odds_over": oo, "odds_under": ou, "p_market": float(p_market),
            "actual_value": actual, "y": y,
            "player_name": first.player_name, "espn_id": first.espn_id,
            "player_team": first.player_team, "position": first.position,
            "home": first.home, "away": first.away, "start_time": first.start_time,
            "espn_event_id": first.espn_event_id,
        })
    out = pd.DataFrame(rows)
    if len(out):
        out["espn_id"] = pd.to_numeric(out.espn_id, errors="coerce")
        out["espn_event_id"] = pd.to_numeric(out.espn_event_id, errors="coerce")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", default="2018-2025")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    if "-" in args.seasons:
        a, b = args.seasons.split("-")
        seasons = list(range(int(a), int(b) + 1))
    else:
        seasons = [int(x) for x in args.seasons.split(",")]
    os.makedirs(args.out, exist_ok=True)
    sched = load_schedules(seasons)
    print(f"schedules: {len(sched)} FBS-any regular games, {sched.game_id.nunique()} unique")
    tg = []
    pg = []
    for season in seasons:
        s = sched[sched.season == season]
        g = build_team_games(season, s)
        p = build_player_games(season, s)
        print(f"  {season}: team-games {len(g)}/{2*len(s)}  player-games {len(p)}")
        tg.append(g)
        pg.append(p)
    tg = pd.concat(tg, ignore_index=True)
    pg = pd.concat(pg, ignore_index=True)
    tg.to_parquet(os.path.join(args.out, "team_games.parquet"), index=False)
    pg.to_parquet(os.path.join(args.out, "player_games.parquet"), index=False)
    print(f"wrote team_games {len(tg)}; player_games {len(pg)}")
    if 2026 in seasons or True:
        props = build_props_2026()
        props.to_parquet(os.path.join(args.out, "props_2026.parquet"), index=False)
        print(f"props_2026 groups {len(props)}; with y {props.y.notna().sum() if len(props) else 0}")
    manifest = {
        "seasons": seasons,
        "schedule_games": int(len(sched)),
        "team_games": int(len(tg)),
        "player_games": int(len(pg)),
        "props_2026_groups": int(len(props)) if "props" in locals() else None,
        "props_2026_y": int(props.y.notna().sum()) if "props" in locals() else None,
    }
    with open(os.path.join(args.out, "data_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
