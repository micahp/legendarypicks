"""Grade week-10 NE@DET prop lines against the six SLC family arms.

Model probability for each player/market/line is the share of that arm's 1,000
valid simulated games in which the player finished over the line. The market
reference is the de-vigged over probability from each book's paired prices,
averaged over books. Actuals come from the final ESPN box score.

Brier is scored per graded player/market/line item; correlated lines for the
same player are kept separate, as the WAS-NYG family report does.
"""
import argparse, json, sqlite3, statistics
from collections import defaultdict
from pathlib import Path

GAME = "2026_10_NE_DET"
ARMS = ("v1", "v1.5", "v1.6", "v1.7", "v1.7-pr43", "v2")
# DB market -> (sim metric, actual group, actual field)
MARKETS = {
    "passing_yards": ("pass_yards", "passing", "yds"),
    "pass_attempts": ("pass_attempts", "passing", "att"),
    "pass_completions": ("pass_completions", "passing", "comp"),
    "passing_touchdowns": ("pass_tds", "passing", "td"),
    "interceptions_thrown": ("interceptions", "passing", "int"),
    "rushing_yards": ("rush_yards", "rushing", "yds"),
    "rush_attempts": ("carries", "rushing", "car"),
    "receiving_yards": ("receiving_yards", "receiving", "yds"),
    "receptions": ("receptions", "receiving", "rec"),
    "targets": ("targets", "receiving", "tgt"),
    "passing_rushing_yards": ("passing_rushing_yards", None, None),
    "rushing_receiving_yards": ("rushing_receiving_yards", None, None),
    "total_touchdowns": ("total_touchdowns", None, None),
    "rushing_receiving_touchdowns": ("rushing_receiving_touchdowns", None, None),
}


def norm(name):
    return "".join(ch for ch in name.lower().replace(".", "").replace("'", "") if ch.isalnum())


def american_prob(odds):
    odds = int(odds)
    return 100 / (odds + 100) if odds > 0 else -odds / (-odds + 100)


def parse_actuals(path):
    d = json.loads(Path(path).read_text())
    players = {}
    for team in d["boxscore"]["players"]:
        abbr = team["team"]["abbreviation"]
        for cat in team["statistics"]:
            labels = cat["labels"]
            for entry in cat["athletes"]:
                name = entry["athlete"]["displayName"]
                row = players.setdefault(norm(name), {"name": name, "team": abbr,
                                                      "passing": {}, "rushing": {}, "receiving": {}})
                for label, value in zip(labels, entry["stats"]):
                    if cat["name"] == "passing":
                        if label == "C/ATT":
                            comp, att = (value.split("/") + ["0", "0"])[:2]
                            row["passing"]["comp"] = float(comp or 0)
                            row["passing"]["att"] = float(att or 0)
                        elif label in ("YDS", "TD", "INT"):
                            row["passing"][{"YDS": "yds", "TD": "td", "INT": "int"}[label]] = float(value or 0)
                    elif cat["name"] == "rushing" and label in ("CAR", "YDS", "TD"):
                        row["rushing"][{"CAR": "car", "YDS": "yds", "TD": "td"}[label]] = float(value or 0)
                    elif cat["name"] == "receiving" and label in ("REC", "TGTS", "YDS", "TD"):
                        row["receiving"][{"REC": "rec", "TGTS": "tgt", "YDS": "yds", "TD": "td"}[label]] = float(value or 0)
    return players


def actual_value(player, market):
    _, group, field = MARKETS[market]
    if group:
        value = (player.get(group) or {}).get(field)
        return None if value is None else float(value)
    if market == "passing_rushing_yards":
        a = (player.get("passing") or {}).get("yds")
        b = (player.get("rushing") or {}).get("yds")
    elif market == "rushing_receiving_yards":
        a = (player.get("rushing") or {}).get("yds")
        b = (player.get("receiving") or {}).get("yds")
    elif market == "total_touchdowns":
        a = (player.get("rushing") or {}).get("td")
        b = (player.get("receiving") or {}).get("td")
    elif market == "rushing_receiving_touchdowns":
        a = (player.get("rushing") or {}).get("td")
        b = (player.get("receiving") or {}).get("td")
    else:
        return None
    return None if a is None or b is None else float(a) + float(b)


def sim_histograms(runs, arm):
    """(gsis, sim_metric) -> list of values across valid seeds for this game."""
    values = defaultdict(list)
    for path in sorted((runs / arm).glob(GAME + "*boxscores.jsonl")):
        for line in path.open():
            row = json.loads(line)
            if row.get("status") != "valid_complete":
                continue
            for player in row.get("players") or []:
                gsis = player.get("stable_player_id")
                if not gsis:
                    continue
                p, r, c = player.get("passing") or {}, player.get("rushing") or {}, player.get("receiving") or {}
                values[(gsis, "pass_yards")].append(float(p.get("yds") or 0))
                values[(gsis, "pass_attempts")].append(float(p.get("att") or 0))
                values[(gsis, "pass_completions")].append(float(p.get("comp") or 0))
                values[(gsis, "pass_tds")].append(float(p.get("td") or 0))
                values[(gsis, "interceptions")].append(float(p.get("int") or 0))
                values[(gsis, "rush_yards")].append(float(r.get("yds") or 0))
                values[(gsis, "carries")].append(float(r.get("att") or 0))
                values[(gsis, "rush_tds")].append(float(r.get("td") or 0))
                values[(gsis, "receiving_yards")].append(float(c.get("yds") or 0))
                values[(gsis, "receptions")].append(float(c.get("rec") or 0))
                values[(gsis, "targets")].append(float(c.get("tgt") or 0))
                values[(gsis, "receiving_tds")].append(float(c.get("td") or 0))
                values[(gsis, "passing_rushing_yards")].append(float(p.get("yds") or 0) + float(r.get("yds") or 0))
                values[(gsis, "rushing_receiving_yards")].append(float(r.get("yds") or 0) + float(c.get("yds") or 0))
                values[(gsis, "total_touchdowns")].append(float(r.get("td") or 0) + float(c.get("td") or 0) + float(p.get("td") or 0) * 0)
                values[(gsis, "rushing_receiving_touchdowns")].append(float(r.get("td") or 0) + float(c.get("td") or 0))
    unique = {}
    for key, vals in values.items():
        unique[key] = vals
    return unique


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=Path, required=True)
    ap.add_argument("--props-db", type=Path, required=True)
    ap.add_argument("--espn", type=Path, required=True)
    ap.add_argument("--kickoff", default="2026-11-15T14:30:00Z")
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()

    actual_players = parse_actuals(args.espn)
    db = sqlite3.connect("file:%s?mode=ro" % args.props_db, uri=True)
    db.row_factory = sqlite3.Row
    sql = """select p.player_id, p.market, p.line, p.side, p.source, p.captured_at, p.odds,
                    pl.nfl_gsis_id, pl.name, pl.team
             from props p join players pl on pl.id = p.player_id
             where p.game_id = 30226 and p.captured_at < ?"""
    raw = defaultdict(dict)
    names = {}
    for row in db.execute(sql, (args.kickoff,)):
        if row["nfl_gsis_id"]:
            key = (row["nfl_gsis_id"], row["market"], float(row["line"]), row["source"])
            raw[key][row["side"].lower()] = {"odds": row["odds"], "captured_at": row["captured_at"]}
            names[row["nfl_gsis_id"]] = (row["name"], row["team"])
    db.close()

    hists = {arm: sim_histograms(args.runs, arm) for arm in ARMS}

    items = []
    for (gsis, market, line, source), sides in raw.items():
        if market not in MARKETS or not {"over", "under"} <= set(sides):
            continue
        name, team = names[gsis]
        player = actual_players.get(norm(name))
        if player is None:
            continue
        y = actual_value(player, market)
        if y is None or y == line:
            continue
        model_ps = {}
        for arm in ARMS:
            vals = hists[arm].get((gsis, MARKETS[market][0]))
            if not vals:
                continue
            model_ps[arm] = sum(1 for v in vals if v > line) / len(vals)
        if not model_ps:
            continue
        over_odds, under_odds = sides["over"]["odds"], sides["under"]["odds"]
        market_p = None
        if over_odds is not None and under_odds is not None:
            io, iu = american_prob(over_odds), american_prob(under_odds)
            market_p = io / (io + iu)
        items.append({"gsis": gsis, "name": name, "team": team, "market": market,
                      "line": line, "source": source, "actual": y,
                      "over_hit": int(y > line), "market_p": market_p, "model_ps": model_ps,
                      "captured_at": sides["over"]["captured_at"]})

    # one row per player/market/line: average the model over books, average market de-vig
    grouped = defaultdict(list)
    for item in items:
        grouped[(item["gsis"], item["market"], item["line"])].append(item)
    graded = []
    for (gsis, market, line), offers in sorted(grouped.items()):
        model_ps = {arm: statistics.fmean([o["model_ps"][arm] for o in offers if arm in o["model_ps"]])
                    for arm in ARMS if any(arm in o["model_ps"] for o in offers)}
        market_ps = [o["market_p"] for o in offers if o["market_p"] is not None]
        graded.append({"name": offers[0]["name"], "team": offers[0]["team"], "market": market,
                       "line": line, "books": len({o["source"] for o in offers}),
                       "actual": offers[0]["actual"], "over_hit": offers[0]["over_hit"],
                       "market_p": statistics.fmean(market_ps) if market_ps else None,
                       "model_ps": model_ps})

    def brier(p, y):
        return (p - y) ** 2

    summary = {}
    for arm in ARMS:
        errs = [brier(g["model_ps"][arm], g["over_hit"]) for g in graded if arm in g["model_ps"]]
        summary[arm] = {"n": len(errs), "brier": statistics.fmean(errs) if errs else None}
    mkt = [brier(g["market_p"], g["over_hit"]) for g in graded if g["market_p"] is not None]
    summary["market"] = {"n": len(mkt), "brier": statistics.fmean(mkt) if mkt else None}
    summary["constant_50"] = {"n": len(graded), "brier": 0.25}

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "ne-det-prop-grading.json").write_text(json.dumps(
        {"game": GAME, "kickoff": args.kickoff,
         "raw_quote_rows": len(items), "graded_items": len(graded),
         "summary": summary, "items": graded}, indent=2, sort_keys=True) + "\n")

    lines = ["# Week 10 NE@DET: prop grading, six SLC arms", "",
             "Pre-kickoff lines only (captured before %s). One row per player/market/line;" % args.kickoff,
             "model probability is the share of 1,000 simulated games over the line, market",
             "probability is the mean de-vigged over probability across books.", "",
             "## Brier", "", "| Forecast | Graded items | Brier |", "|---|---:|---:|"]
    for key in list(ARMS) + ["market", "constant_50"]:
        s = summary[key]
        lines.append("| %s | %d | %s |" % (key, s["n"], "-" if s["brier"] is None else "%.4f" % s["brier"]))
    lines += ["", "## Items", "",
              "| Player | Team | Market | Line | Actual | Over | Books | Market P | " + " | ".join(ARMS) + " |",
              "|---|---|---|---:|---:|:--:|---:|---:|" + "---:|" * len(ARMS)]
    for g in sorted(graded, key=lambda r: (r["team"], r["name"], r["market"], r["line"])):
        cells = ["-" if arm not in g["model_ps"] else "%.2f" % g["model_ps"][arm] for arm in ARMS]
        lines.append("| %s | %s | %s | %.1f | %.0f | %s | %d | %s | %s |" % (
            g["name"], g["team"], g["market"], g["line"], g["actual"],
            "yes" if g["over_hit"] else "no", g["books"],
            "-" if g["market_p"] is None else "%.2f" % g["market_p"], " | ".join(cells)))
    (args.out_dir / "NE-DET-PROP-GRADING.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:16]))
    print("graded items:", len(graded), "-> wrote", args.out_dir / "NE-DET-PROP-GRADING.md")


if __name__ == "__main__":
    main()
