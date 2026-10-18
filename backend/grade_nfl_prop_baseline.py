#!/usr/bin/env python3
"""grade_nfl_prop_baseline.py -- the live Marcel-lite P(over) on the same prop items the v2 grader uses.

Why this exists. Before the v2 engine (`nfl_player_projection_v2.py`, branch scratch/spec-b-rebase) can
replace the live player-projection route, the number it has to beat must be on the record. The live route
is `/api/projections/player/{id}` -> `analytics/projections.py`: `project_stat` (recency-weighted mean) and
`prob_over` (the player's own empirical hit rate vs the line) over that player's same-season logs. That
route has never been graded. This script grades it.

The item set is imported from `grade_nfl_prop_probabilities.collect`, not re-implemented: same props table,
same sportsbook-only source list, same devig, same weeks, same position and lead-passer filters, same
box-score outcome. The two Briers are therefore comparable item by item.

Two baselines are reported:

  walk-forward  the fair one, and the one to quote. For each target game only the player's 2026
                regular-season games BEFORE that week enter the series, and `project_stat`'s own
                min_games=3 gate applies, so the item is dropped when the player has fewer than three
                prior games (the live route returns no projection at all in that case). This is what the
                route would have served before kickoff, and it is the comparison the walk-forward v2
                numbers in RESULTS-player-projection-v2-2026-10-12.md are against.
  as-served     the live route replayed today: every 2026 log in the season, including the target game and
                every game after it. Reported only to size the look-ahead in the served number. It is not
                a forecast and must never be quoted as one.

Paired comparison. `--v2-csv` takes the CSV written by `grade_nfl_prop_probabilities.py --csv` and prints
the Brier of ours, of the live baseline, and of the market on the items BOTH graded, plus the paired
per-item difference. That intersection is the headline: the two systems are not served on identical item
sets, so a difference of two standalone Briers would be a difference of two populations.

Read-only. Usage:
  LP_DB_PATH=... python3 grade_nfl_prop_baseline.py --season 2026 [--csv out.csv] [--v2-csv v2.csv]
"""
import argparse
import csv
import json
import os
import sqlite3
from collections import defaultdict

import grade_nfl_prop_probabilities as g
from analytics.projections import project_stat, prob_over

# Market -> the canonical (post-normalize) stat key the live route projects on. Same keys as the grader's
# RECEIVING / PASSING tuples, which are already canonical.
MARKET_KEY = {m: col for m, (_idx, col) in list(g.RECEIVING.items()) + list(g.PASSING.items())}

# The box-score attribute each market's actual comes from, on the branch History Row.
MARKET_KEY_TO_ROW = {"receiving_yards": "rec_yds", "receptions": "rec", "targets": "tgt",
                     "passing_yards": "pass_yds", "pass_attempts": "att", "pass_completions": "cmp",
                     "passing_touchdowns": "pass_td"}

# Copied from routers/players/stats.py:_NFL_KEY_NORMALIZE (2026-10-16). The live route folds legacy 2024
# nflverse keys onto the canonical 2025 pbp names before building the series; without it a legacy row's
# stat is invisible to the projection. Only the keys these seven markets touch matter here.
NORM = {"passing_yards": "pass_yds", "passing_tds": "pass_td", "completions": "cmp", "attempts": "att",
        "interceptions": "intc", "rushing_yards": "rush_yds", "rushing_tds": "rush_td",
        "receiving_yards": "rec_yds", "receiving_tds": "rec_td", "receptions": "rec",
        "fantasy_points": "fpts", "fantasy_points_ppr": "fpts_ppr"}


def live_series(con, season):
    """Replay the live route's series build.

    Returns (per_player, absent, keys_seen) where per_player[pid] is a list of (game_id, week, {key: value})
    ordered most-recent-first as the route orders it (COALESCE(game_date,'') DESC, game_no DESC), absent
    counts player-games whose blob carried no numeric stat at all, and keys_seen is the union of numeric
    keys found. The route skips a game for a stat whose key is missing from the blob; History.Row would
    read it as 0.0 instead, so the denominators can differ and that is counted.
    """
    rows = con.execute(
        "SELECT player_id, game_id, game_date, game_no, stats FROM player_game_logs "
        "WHERE league='nfl' AND season=? AND source='nflverse_weekly' "
        "AND (game_type='REG' OR game_type IS NULL) AND game_id IS NOT NULL", (season,)).fetchall()
    per_player, absent, keys_seen = defaultdict(list), 0, set()
    for pid, gid, gdate, gno, stats in rows:
        blob = json.loads(stats)
        numeric = {k: v for k, v in blob.items() if isinstance(v, (int, float))}
        if not numeric:
            absent += 1
        keys_seen.update(numeric)
        _s, week, _a, _h = g.eng.parse_game_id(gid)
        vals = {NORM.get(k, k): v for k, v in numeric.items()}
        per_player[pid].append((gid, week, vals))
    for pid in per_player:
        per_player[pid].sort(key=lambda t: t[1], reverse=True)
    return per_player, absent, keys_seen


def grade_baseline(con, season, hist=None):
    hist = hist or g.eng.History.load(con, [season - 1, season])
    final_weeks = {w for (w,) in con.execute(
        "SELECT DISTINCT week FROM nfl_schedule WHERE season=? AND game_type='REG' AND home_score IS NOT NULL",
        (season,))}
    items, skipped = g.collect(con, season)
    skipped = dict(skipped)
    skipped.update({"not_played": 0, "week": 0, "position": 0, "not_lead_passer": 0,
                    "baseline_lt3_prior": 0})
    per_player, absent_blobs, keys_seen = live_series(con, season)
    graded, disagree, denom_diff, missing_key = [], 0, 0, 0
    for gid, pid, market, book, line, p_mkt, book_hit in items:
        week = int(gid.split("_")[1])
        if week < 2 or week not in final_weeks:
            skipped["week"] += 1
            continue
        row = next((r for r in hist.by_player.get((season, pid), []) if r.game_id == gid), None)
        if row is None:
            skipped["not_played"] += 1
            continue
        if market in g.RECEIVING:
            if row.pos not in ("RB", "WR", "TE"):
                skipped["position"] += 1
                continue
        else:
            if row.pos != "QB":
                skipped["position"] += 1
                continue
            team_rows = hist.by_team[(season, row.team)][row.week]
            if max(team_rows, key=lambda x: (x.att, -x.pid)).pid != pid:
                skipped["not_lead_passer"] += 1
                continue
        key = MARKET_KEY[market]
        if key not in keys_seen:
            missing_key += 1
            skipped["baseline_lt3_prior"] += 1
            continue
        games = per_player.get(pid, [])
        prior = [v[key] for _g, w, v in games if w < week and key in v]
        allvals = [v[key] for _g, w, v in games if key in v]
        if project_stat(prior) is None:      # the route serves nothing below min_games=3
            skipped["baseline_lt3_prior"] += 1
            continue
        n_prior_played = sum(1 for r in hist.by_player.get((season, pid), []) if r.week < week)
        if n_prior_played != len(prior):
            denom_diff += 1
        p_wf = prob_over(prior, line)["p_over"]
        p_all = prob_over(allvals, line)["p_over"] if project_stat(allvals) else None
        actual = getattr(row, MARKET_KEY_TO_ROW[market])
        outcome = 1 if actual > line else 0
        if book_hit is not None and int(book_hit) != outcome:
            disagree += 1
        graded.append({"game_id": gid, "player_id": pid, "market": market, "book": book, "line": line,
                       "p_wf": p_wf, "p_all": p_all, "p_market": p_mkt, "actual": actual,
                       "over": outcome, "n_prior": len(prior),
                       "group": "passing" if market in g.PASSING else "receiving"})
    notes = {"absent_blobs": absent_blobs, "denominator_differs": denom_diff,
             "keys_seen": len(keys_seen), "missing_market_key": missing_key}
    return graded, skipped, disagree, notes


def brier(rows, field):
    n = len(rows)
    return sum((r[field] - r["over"]) ** 2 for r in rows) / n if n else None


def _key(game_id, player_id, market, book, line):
    """Join key across the two CSVs. player_id is an int in this script's dicts and a string in a CSV,
    so it is normalised here; without that every item looks unmatched."""
    return (str(game_id), str(player_id), str(market), str(book), float(line))


def paired(base, v2_path):
    """Brier of ours, of the live baseline and of the market on the items both graded."""
    with open(v2_path, newline="") as f:
        v2 = {_key(r["game_id"], r["player_id"], r["market"], r["book"], r["line"]): r
              for r in csv.DictReader(f)}
    both, only_base = [], 0
    for b in base:
        k = _key(b["game_id"], b["player_id"], b["market"], b["book"], b["line"])
        v = v2.get(k)
        if v is None:
            only_base += 1
            continue
        both.append({"over": b["over"], "p_wf": b["p_wf"], "p_market": b["p_market"],
                     "market": b["market"], "p_v2": float(v["p_ours"])})
    seen = {_key(b["game_id"], b["player_id"], b["market"], b["book"], b["line"]) for b in base}
    only_v2 = sum(1 for k in v2 if k not in seen)
    n = len(both)
    if not n:
        print("paired: no shared items")
        return

    def item_diff(rows):
        """Per-item Brier difference, live minus v2. Positive means v2 is the better forecast."""
        return [(r["p_wf"] - r["over"]) ** 2 - (r["p_v2"] - r["over"]) ** 2 for r in rows]

    def summarize(label, rows, indent="  "):
        d = item_diff(rows)
        m = sum(d) / len(d)
        v = sum((x - m) ** 2 for x in d) / (len(d) - 1) if len(d) > 1 else 0.0
        s = (v / len(d)) ** 0.5 if len(d) > 1 else 0.0
        print("%s%-20s n %6d  live %.4f  v2 %.4f  market %.4f  paired(v2-live) %+.5f +/- %.5f" % (
            indent, label, len(rows), brier(rows, "p_wf"), brier(rows, "p_v2"), brier(rows, "p_market"),
            -m, 1.96 * s))

    print("paired on %d shared items (%d only-v2, %d only-baseline):" % (n, only_v2, only_base))
    summarize("all", both)
    for market in sorted({b["market"] for b in both}):
        sub = [b for b in both if b["market"] == market]
        if len(sub) > 1:
            summarize(market, sub, indent="    ")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--csv")
    ap.add_argument("--v2-csv")
    a = ap.parse_args(argv)
    path = os.environ.get("LP_DB_PATH")
    if not path:
        raise SystemExit("LP_DB_PATH is required")
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    graded, skipped, disagree, notes = grade_baseline(con, a.season)
    print("excluded: %s; our outcome disagrees with the book's settlement on %d graded items" % (skipped, disagree))
    print("notes: %s" % notes)
    for field, label in (("p_wf", "walk-forward (quote this)"),
                         ("p_all", "as-served (look-ahead, do not quote)")):
        rows = [dict(r, p_ours=r[field]) for r in graded if r[field] is not None]
        g.report(rows, label)
        if field == "p_all":
            print("  (as-served has %d of %d items; the rest lack 3 season games)" % (len(rows), len(graded)))
    if a.v2_csv:
        paired(graded, a.v2_csv)
    if a.csv:
        with open(a.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(graded[0]))
            w.writeheader()
            w.writerows(graded)


if __name__ == "__main__":
    main()
