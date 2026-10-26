"""Unconditional favourite -1.5 vs favourite ML vs underdog +1.5, at published SBR prices.

Settles every archived game three ways and reports records, units and ROI so the
"is -1.5 worth it" question has a measured baseline. No model enters.
"""
import gzip, json, statistics as st
from collections import defaultdict

PATH = "/root/legendarypicks/research/nhl/sbr-odds-archive-2026-10-19/games_2018_2023.jsonl.gz"


def payout(american, won):
    """Profit per 1u stake."""
    if not won:
        return -1.0
    return american / 100.0 if american > 0 else 100.0 / abs(american)


def load():
    out = []
    with gzip.open(PATH, "rt") as fh:
        for line in fh:
            g = json.loads(line)
            h, a = g["home"], g["away"]
            if None in (h.get("final"), a.get("final"), h.get("ml_open"), a.get("ml_open"),
                        h.get("puck_price"), a.get("puck_price"), h.get("puck_line")):
                continue
            out.append(g)
    return out


def summarize(name, results):
    """results: list of (season, profit, american, won)."""
    n = len(results)
    if not n:
        return None
    wins = sum(1 for r in results if r[3])
    units = sum(r[1] for r in results)
    roi = units / n * 100.0
    odds = [r[2] for r in results]
    se = st.pstdev([r[1] for r in results]) / (n ** 0.5)
    return {
        "strategy": name, "bets": n, "wins": wins, "losses": n - wins,
        "win_pct": 100.0 * wins / n, "units": units, "roi_pct": roi,
        "roi_se": st.pstdev([r[1] for r in results]) / (n ** 0.5) * 100.0,
        "avg_american": sum(odds) / n,
        "breakeven_win_pct": 100.0 * sum(-1.0 / (payout(o, True) + 1.0) * -1 for o in odds) / n,
    }


def main():
    games = load()
    print("games with both finals + ML open + both puck prices: %d" % len(games))

    for price_key in ("ml_open", "ml_close"):
        rows = {"fav_ml": [], "fav_minus15": [], "dog_plus15": []}
        by_season = defaultdict(lambda: {"fav_ml": [], "fav_minus15": [], "dog_plus15": []})
        by_band = defaultdict(lambda: {"fav_minus15": [], "fav_ml": []})
        for g in games:
            h, a = g["home"], g["away"]
            if h[price_key] is None or a[price_key] is None:
                continue
            fav, dog = (h, a) if h[price_key] <= a[price_key] else (a, h)
            if fav["puck_line"] != -1.5:
                continue
            margin = fav["final"] - dog["final"]
            fav_win = margin > 0
            cover = margin >= 2
            dog_cover = not cover

            fav_price = fav[price_key]
            band = "+" if fav[price_key] > 0 else ("-101/-140" if fav[price_key] >= -140
                                                   else "-141/-200" if fav[price_key] >= -200
                                                   else "-201+")
            r_ml = (g["season"], payout(fav[price_key], fav_win), fav[price_key], fav_win)
            r_pl = (g["season"], payout(fav["puck_price"], cover), fav["puck_price"], cover)
            r_dog = (g["season"], payout(dog["puck_price"], dog_cover), dog["puck_price"], dog_cover)
            rows["fav_ml"].append(r_ml)
            rows["fav_minus15"].append(r_pl)
            rows["dog_plus15"].append(r_dog)
            for k, v in (("fav_ml", r_ml), ("fav_minus15", r_pl), ("dog_plus15", r_dog)):
                by_season[g["season"]][k].append(v)
            by_band[band]["fav_minus15"].append(r_pl)
            by_band[band]["fav_ml"].append(r_ml)

        print("\n=== prices: %s ===" % price_key)
        for k in ("fav_ml", "fav_minus15", "dog_plus15"):
            s = summarize(k, rows[k])
            print("%-14s %4d bets  %3d-%3d  win %5.1f%%  units %+8.2f  ROI %+6.2f%% (se %.2f)  avg %+6.1f  BE win %5.1f%%"
                  % (s["strategy"], s["bets"], s["wins"], s["losses"], s["win_pct"],
                     s["units"], s["roi_pct"], s["roi_se"], s["avg_american"], s["breakeven_win_pct"]))

        print("\nper season (fav -1.5 | fav ML | dog +1.5):")
        for season in sorted(by_season):
            parts = []
            for k in ("fav_minus15", "fav_ml", "dog_plus15"):
                s = summarize(k, by_season[season][k])
                parts.append("%3d-%3d %+6.1fu %+6.1f%%" % (s["wins"], s["losses"], s["units"], s["roi_pct"]))
            print("  %s  " % season + " | ".join(parts))

        print("\nfavourite ML price band:")
        for band in ("+", "-101/-140", "-141/-200", "-201+"):
            for k in ("fav_ml", "fav_minus15"):
                s = summarize(k, by_band[band][k])
                if s:
                    lo, hi = s["roi_pct"] - 1.96 * s["roi_se"], s["roi_pct"] + 1.96 * s["roi_se"]
                    print("  %-10s %-12s %4d bets  %3d-%3d  win %5.1f%%  ROI %+6.2f%% [%+6.2f, %+6.2f]  avg %+6.1f"
                          % (band, k, s["bets"], s["wins"], s["losses"], s["win_pct"],
                             s["roi_pct"], lo, hi, s["avg_american"]))

        # paired: same games, -1.5 instead of ML
        pairs = [(p, m) for p, m in zip(rows["fav_minus15"], rows["fav_ml"])]
        diffs = [p[1] - m[1] for p, m in pairs]
        d = sum(diffs) / len(diffs)
        ds = st.pstdev(diffs) / (len(diffs) ** 0.5)
        print("\nfav -1.5 minus fav ML on identical games: %+.4f u/bet (se %.4f, 95%% CI [%+.4f, %+.4f])"
              % (d, ds, d - 1.96 * ds, d + 1.96 * ds))


if __name__ == "__main__":
    main()
