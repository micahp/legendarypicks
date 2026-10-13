"""validate_nfl_seeding_history.py -- seeds from regular-season results vs the playoff games
actually played, 2010-2025. Read-only: both databases are opened with mode=ro.

2010-2023 come from the historical SQLite (codes already mapped to current ones). 2024-2025 come
from the dev DB. Before any season is checked, every regular-season game in the season is matched
against the nflverse games.parquet (raw codes, div_game flag) through CODE_MAP, and the division
of both clubs under the current nfl_teams map must agree with div_game. A season whose map does
not agree is reported and skipped, never silently checked.

Exit 1 if any conference-season does not match (or a season fails the map check).

Usage:
  LP_DB_PATH=<dev db> python validate_nfl_seeding_history.py --hist <historical sqlite> \
      --parquet <games.parquet>
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

import pandas as pd

import nfl_bracket_check as bc
import nfl_seeding as sd

# nflverse raw code -> code used in the database. Every pair found in 10-11 check (step 1a).
CODE_MAP = {"LA": "LAR", "STL": "LAR", "SD": "LAC", "OAK": "LV", "WAS": "WSH"}
FIRST, LAST = 2010, 2025
HIST_LAST = 2023


def ro(path):
    return sqlite3.connect("file:%s?mode=ro" % path, uri=True)


def map_code(raw):
    return CODE_MAP.get(raw, raw)


def verify_map(con, season, games_df, tmap):
    """Return a list of mismatches between the database games and nflverse for one season."""
    db = con.execute(
        "SELECT game_id, home_team, away_team FROM nfl_schedule "
        "WHERE season = ? AND game_type = 'REG'", (season,)).fetchall()
    raw = games_df[games_df.season == season].set_index("game_id")
    bad = []
    for game_id, home, away in db:
        if game_id not in raw.index:
            bad.append((game_id, "missing from nflverse"))
            continue
        r = raw.loc[game_id]
        if (map_code(r.home_team), map_code(r.away_team)) != (home, away):
            bad.append((game_id, "codes %s@%s vs db %s@%s" % (r.away_team, r.home_team, away, home)))
            continue
        if home not in tmap or away not in tmap:
            bad.append((game_id, "code not in nfl_teams: %s %s" % (home, away)))
            continue
        same_div = tmap[home][1] == tmap[away][1]
        if bool(r.div_game) != same_div:
            bad.append((game_id, "div_game=%s but divisions %s %s" % (
                r.div_game, tmap[home][1], tmap[away][1])))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hist", required=True)
    ap.add_argument("--parquet", required=True)
    args = ap.parse_args()

    dev_path = os.environ.get("LP_DB_PATH")
    if not dev_path:
        sys.exit("set LP_DB_PATH to the dev database")
    dev = ro(dev_path)
    hist = ro(args.hist)
    tmap = bc.team_map(dev)
    games_df = pd.read_parquet(args.parquet)

    ok_count = 0
    total = 0
    for season in range(FIRST, LAST + 1):
        con = hist if season <= HIST_LAST else dev
        mism = verify_map(con, season, games_df, tmap)
        if mism:
            print("%d  MAP FAILED: %d games, e.g. %s" % (season, len(mism), mism[:3]))
            total += 2
            continue
        sd.COIN_FLAGS.clear()
        sd.DECISIONS.clear()
        rep = bc.validate_season(con, season, tmap)
        for conf in ("AFC", "NFC"):
            total += 1
            c = rep["conferences"][conf]
            if c["ok"]:
                ok_count += 1
                print("%d %s ok  coin_flips=%d decisions=%d" % (
                    season, conf, len(sd.COIN_FLAGS), len(sd.DECISIONS)))
            else:
                print("%d %s MISMATCH  wc_pairs=%s wc_field=%s div_pairs=%s coin_flips=%d" % (
                    season, conf, c["wild_card_pairs_match"], c["wild_card_field_match"],
                    c["divisional_pairs_match"], len(sd.COIN_FLAGS)))
                print("    seeds:        %s" % c["seeds"])
                print("    expected wc:  %s" % c["expected_wc"])
                print("    actual wc:    %s" % c["actual_wc"])
                print("    expected div: %s" % c["expected_div"])
                print("    actual div:   %s" % c["actual_div"])
    print("conference-seasons ok: %d of %d" % (ok_count, total))
    sys.exit(0 if ok_count == total else 1)


if __name__ == "__main__":
    main()
