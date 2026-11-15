"""Grade the week-10 NE@DET SLC family batches against the final ESPN box score.

Reads every completed 250-seed chunk for 2026_10_NE_DET across the six arms,
keeps the valid seeds, and reports:

  * game level - win probability, score distribution, total, home-win Brier;
  * player level - model mean vs actual for the players who recorded stats, plus
    per-arm MAE on the graded stats.

Market grading is deliberately absent: the API database has no prop_games row
for 2026-11-15 (its newest NFL prop game is 2026-11-08), so there are no
pre-kickoff lines to grade against yet. The report says so instead of scoring
against nothing.
"""
import argparse, glob, json, statistics
from collections import Counter, defaultdict
from pathlib import Path

GAME = "2026_10_NE_DET"
HOME_AWAY = ("DET", "NE")
ARMS = ("v1", "v1.5", "v1.6", "v1.7", "v1.7-pr43", "v2")
# our boxscore keys -> ESPN (category, label) with the labels the summary uses
MARKETS = {
    "pass_yards": ("passing", "YDS"), "pass_attempts": ("passing", "C/ATT"),
    "pass_completions": ("passing", "C/ATT"), "pass_tds": ("passing", "TD"),
    "interceptions": ("passing", "INT"),
    "rush_yards": ("rushing", "YDS"), "carries": ("rushing", "CAR"),
    "rush_tds": ("rushing", "TD"),
    "receiving_yards": ("receiving", "YDS"), "receptions": ("receiving", "REC"),
    "targets": ("receiving", "TGTS"), "receiving_tds": ("receiving", "TD"),
}


def quantity(values):
    xs = sorted(values)
    if not xs:
        return None

    def q(p):
        pos = (len(xs) - 1) * p
        lo = int(pos)
        hi = min(lo + 1, len(xs) - 1)
        return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)

    return {"mean": statistics.fmean(xs), "median": statistics.median(xs),
            "p10": q(0.10), "p90": q(0.90), "n": len(xs)}


def load_actuals(path):
    d = json.loads(Path(path).read_text())
    score, players = {}, {}
    for team in d["boxscore"]["players"]:
        abbr = team["team"]["abbreviation"]
        for cat in team["statistics"]:
            labels = cat["labels"]
            for entry in cat["athletes"]:
                name = entry["athlete"]["displayName"]
                stats = entry["stats"]
                row = players.setdefault(norm(name), {"name": name, "team": abbr,
                                                      "passing": {}, "rushing": {},
                                                      "receiving": {}})
                for label, value in zip(labels, stats):
                    if cat["name"] == "passing":
                        if label == "C/ATT":
                            comp, att = (value.split("/") + ["0"])[:2]
                            row["passing"]["comp"] = float(comp or 0)
                            row["passing"]["att"] = float(att or 0)
                        elif label in ("YDS", "TD", "INT"):
                            row["passing"][{"YDS": "yds", "TD": "td", "INT": "int"}[label]] = float(value or 0)
                    elif cat["name"] == "rushing":
                        if label in ("CAR", "YDS", "TD"):
                            row["rushing"][{"CAR": "car", "YDS": "yds", "TD": "td"}[label]] = float(value or 0)
                    elif cat["name"] == "receiving":
                        if label in ("REC", "TGTS", "YDS", "TD"):
                            row["receiving"][{"REC": "rec", "TGTS": "tgt", "YDS": "yds",
                                              "TD": "td"}[label]] = float(value or 0)
    for comp in d["header"]["competitions"][0]["competitors"]:
        score[comp["team"]["abbreviation"]] = int(comp["score"])
    return score, players


def norm(name):
    return "".join(ch for ch in name.lower().replace(".", "").replace("'", "") if ch.isalnum())


def our_value(player, market):
    section, key = market.split("_", 1)
    return (player.get(section) or {}).get(key)


def field_of(market):
    return {"pass_yards": ("passing", "yds"), "pass_attempts": ("passing", "att"),
            "pass_completions": ("passing", "comp"), "pass_tds": ("passing", "td"),
            "interceptions": ("passing", "int"), "rush_yards": ("rushing", "yds"),
            "carries": ("rushing", "att"), "rush_tds": ("rushing", "td"),
            "receiving_yards": ("receiving", "yds"), "receptions": ("receiving", "rec"),
            "targets": ("receiving", "tgt"), "receiving_tds": ("receiving", "td")}[market]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=Path, required=True)
    ap.add_argument("--espn", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--game", default=GAME)
    ap.add_argument("--home-away", default="DET,NE")
    args = ap.parse_args()
    globals()["GAME"] = args.game
    globals()["HOME_AWAY"] = tuple(args.home_away.split(","))
    score, actual_players = load_actuals(args.espn)
    home, away = HOME_AWAY
    home_points, away_points = score[home], score[away]

    games, dists = {}, {}
    for arm in ARMS:
        rows = []
        for path in sorted((args.runs / arm).glob(GAME + "*boxscores.jsonl")):
            for line in path.open():
                row = json.loads(line)
                if row.get("teams") and row.get("status") == "valid_complete":
                    rows.append(row)
        by_seed = {}
        for row in rows:
            by_seed[row["seed"]] = row
        rows = list(by_seed.values())
        games[arm] = rows
        per_player = defaultdict(lambda: defaultdict(list))
        for row in rows:
            for player in row.get("players") or []:
                key = norm(player["name"])
                for market in MARKETS:
                    sec, k = field_of(market)
                    value = (player.get(sec) or {}).get(k)
                    if value is not None:
                        per_player[key][market].append(float(value))
        dists[arm] = per_player

    summary = {}
    for arm, rows in games.items():
        pts_home = [next(t["stats"]["points"] for t in r["teams"] if t["team"] == home) for r in rows]
        pts_away = [next(t["stats"]["points"] for t in r["teams"] if t["team"] == away) for r in rows]
        n = len(rows)
        wins = Counter(home if h > a else away if a > h else "tie" for h, a in zip(pts_home, pts_away))
        p_home = wins[home] / n if n else None
        summary[arm] = {
            "valid_seeds": n,
            "p_home_win": p_home, "p_away_win": wins[away] / n if n else None,
            "p_tie": wins["tie"] / n if n else None,
            "home_win_brier": (p_home - 1.0) ** 2 if n else None,
            "home": quantity(pts_home), "away": quantity(pts_away),
            "total": quantity([h + a for h, a in zip(pts_home, pts_away)]),
            "margin": quantity([h - a for h, a in zip(pts_home, pts_away)]),
        }
        summary[arm]["combined_score_error"] = (
            abs(summary[arm]["home"]["mean"] - home_points) + abs(summary[arm]["away"]["mean"] - away_points))

    graded = []
    for key, actual in actual_players.items():
        for market in MARKETS:
            sec, k = field_of(market)
            truth = (actual.get(sec) or {}).get(k)
            if truth is None:
                continue
            if sec == "passing" and market == "pass_attempts":
                truth = actual["passing"].get("att")
            if sec == "rushing" and market == "carries":
                truth = actual["rushing"].get("car")
            if truth is None or truth == 0:
                continue
            row = {"player": actual["name"], "team": actual["team"], "market": market, "actual": truth}
            for arm in ARMS:
                q = quantity([v for v in dists[arm].get(key, {}).get(market, [])])
                row[arm] = q["mean"] if q else None
            row["best_arm"] = min((a for a in ARMS if row[a] is not None),
                                  key=lambda a: abs(row[a] - truth), default=None)
            graded.append(row)

    mae = {}
    for arm in ARMS:
        errs = [abs(r[arm] - r["actual"]) for r in graded if r[arm] is not None]
        mae[arm] = {"n": len(errs), "mae": statistics.fmean(errs) if errs else None}

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / ("%s-family-grading.json" % args.game)).write_text(json.dumps(
        {"game": GAME, "final_score": score, "game_level": summary,
         "player_mae": mae, "graded_stats": graded,
         "notes": ["no 2026-11-15 prop_games row exists in picks.dev.db, so market grading is unavailable",
                   "seeds are model draws, not paired across arms (v2 uses rng protocol v2)"]},
        indent=2, sort_keys=True) + "\n")

    lines = ["# Week 10: NE at DET, SLC model family", "",
             "**Final:** DET %d, NE %d (home win = 1)." % (home_points, away_points), "",
             "Inputs: the prospective snapshots built 2026-11-14 18:54:46Z, week-10 kicker table",
             "(LA = McManus), week-9 streaks and snap counts. Each arm is its own git ref.", "",
             "## Game level", "",
             "| Arm | Valid seeds | P(%s) | P(%s) | P(tie) | Home Brier | %s mean (P10-P90) | %s mean (P10-P90) | Total | Combined score error |" % (home, away, home, away),
             "|---|---:|---:|---:|---:|---:|---|---|---:|---:|"]
    for arm in ARMS:
        s = summary[arm]
        if not s["valid_seeds"]:
            lines.append("| %s | 0 | - | - | - | - | - | - | - | - |" % arm)
            continue
        lines.append("| %s | %d | %.1f%% | %.1f%% | %.1f%% | %.3f | %.2f (%.0f-%.0f) | %.2f (%.0f-%.0f) | %.2f | %.2f |" % (
            arm, s["valid_seeds"], 100 * s["p_home_win"], 100 * s["p_away_win"], 100 * s["p_tie"],
            s["home_win_brier"], s["home"]["mean"], s["home"]["p10"], s["home"]["p90"],
            s["away"]["mean"], s["away"]["p10"], s["away"]["p90"], s["total"]["mean"],
            s["combined_score_error"]))
    lines += ["", "## Player stat accuracy (MAE over graded player-markets)", "",
              "| Arm | Graded player-markets | MAE |", "|---|---:|---:|"]
    for arm in ARMS:
        m = mae[arm]
        lines.append("| %s | %d | %s |" % (arm, m["n"], "-" if m["mae"] is None else "%.3f" % m["mae"]))
    lines += ["", "## Market grading", "",
              "Not possible yet: `picks.dev.db` has no `prop_games` row for 2026-11-15",
              "(newest NFL prop game is 2026-11-08), so there are no pre-kickoff lines for",
              "this game. Prop Brier versus the de-vigged market runs once those lines land.", "",
              "## Graded player-markets (model mean vs actual)", "",
              "| Player | Team | Market | Actual | " + " | ".join(ARMS) + " |", "|---|---|---|---:|" + "---:|" * len(ARMS)]
    for row in sorted(graded, key=lambda r: (r["team"], r["player"], r["market"])):
        cells = ["-" if row[a] is None else "%.2f" % row[a] for a in ARMS]
        lines.append("| %s | %s | %s | %.0f | %s |" % (row["player"], row["team"], row["market"],
                                                      row["actual"], " | ".join(cells)))
    (args.out_dir / ("%s-FAMILY-GRADING.md" % args.game.replace("2026_10_","").replace("_","-"))).write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:20]))
    print("... wrote", args.out_dir / ("%s-FAMILY-GRADING.md" % args.game.replace("2026_10_","").replace("_","-")))


if __name__ == "__main__":
    main()
