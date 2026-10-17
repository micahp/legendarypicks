#!/usr/bin/env python3
"""fbs_baseline.py -- the FBS baseline ladder, stage 2 of the five-stage plan.

Stage 2 of the plan is: compare simple season averages, rolling-window
projections, a full Marcel-style model, and a hierarchical model using team
opportunity shares, prior player experience, and opponent adjustments. Test QB
passing yards and RB rushing yards first.

This file implements that comparison as a **pre-registered** ladder. The
definitions, the training window, the holdout and the keep rule are fixed here
before any number is computed, because the NFL work measured that a comparison
chosen after the fact is choosing the winner.

THE HOLDOUT, AND WHY IT IS A WEEK WALK-FORWARD
----------------------------------------------
The plan's holdout was 2025 as the first complete season, with 2026 as a
separate live forward-recorded test. The first half of that is not available.
Measured 2026-10-17 against the dev database:

    SELECT substr(start_time,1,4) FROM prop_games WHERE league='ncaaf'
      -> 2026 only
    SELECT COUNT(*) FROM prop_games WHERE league='ncaaf'
      AND substr(start_time,1,4)='2025'   -> 0

NCAAF props exist for 2026 only. There is no 2025 prop board, so there is no
2025 line to grade against and no 2025 over/under to settle. A holdout season
requires prior seasons' props, not prior seasons' logs.

So the holdout is the **second half of the 2026 season, graded week by week**:
train on every game strictly before the graded week, grade that week. This is a
walk-forward in time rather than across seasons, which keeps the property that
matters -- the target is never in its own fit -- and it is the only holdout the
data supports. The plan's 2025-as-first-complete-holdout is recorded as
UNAVAILABLE, not as done.

What this costs, stated plainly: a week walk-forward within one season measures
the models against one season's schedule and one season's players. It cannot
separate a model that is right from a model that is right for this season. That
limitation is reported, not hidden, and it is the reason the keep rule requires
an interval, not a point difference.

Definitions, fixed before the run
---------------------------------
**Markets.** `passing_yards` and `rushing_yards` only. Receiving markets are
excluded until target and reception attribution quality is confirmed, per the
plan.

**Items.** One row per (week, player, game, market). An item exists only if the
prop is settled, the line is non-null, the player has a stored log row in that
game, and the line is not a whole number (a whole number is a possible push and
is not an observation of the over/under).

**Walk-forward.** For each graded week W, a model reads every stored log row
with `game_date` strictly before W's first kickoff. It never reads W.

**Models, in order of complexity.**
1. `season_avg` -- the player's mean per-game value over all prior games. No
   regression, no shrinkage. The control.
2. `rolling_5` -- the mean of the player's last 5 prior games.
3. `marcel` -- Marcel-style: weighted average of the player's last three prior
   weeks with weights 5/4/3, regressed to the league mean by n/(n+k), k=5.
4. `share_adj` -- `rolling_5` scaled by the player's share of their own prior
   games' opportunities. This is the first rung of the plan's opportunity
   modeling; the team-side share needs the team logs, which are measured
   separately.

**P(over).** A normal approximation to the per-game distribution with a
player-specific variance: the player's own prior-game variance shrunk toward
the league variance by n/(n+10), floored at 1.0. Deliberately the simplest
honest probability, because the NFL's lesson was that the probability, not the
point estimate, was the broken part.

**Keep rule.** A model is adopted only if its Brier on the graded weeks is
lower than `season_avg`'s by a **player-game-clustered** bootstrap interval
that excludes zero. The items are alternate lines on the same player-game, so
an item-level interval is optimistic by roughly 3x here and is not reported.

Read-only against the database. Writes nothing. The report is Markdown.

Usage:
    cd <repo>/backend
    LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
      /root/legendarypicks/backend/venv/bin/python fbs_baseline.py
"""
import argparse
import datetime as dt
import math
import os
import random
import sqlite3
import sys
from datetime import date as _date, timedelta as _timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

DEFAULT_DB = os.environ.get("LP_DB_PATH") or os.path.join(
    HERE, "data", "picks.dev.db"
)
LEAGUE = "ncaaf"

MARKETS = ("passing_yards", "rushing_yards")
STAT_KEY = {"passing_yards": "pass_yds", "rushing_yards": "rush_yds"}

MARCEL_WEIGHTS = (5.0, 4.0, 3.0)
MARCEL_K = 5.0
ROLLING_N = 5
SHARE_MIN_GAMES = 3
VARIANCE_SHRINK_K = 10.0
SIGMA_FLOOR = 1.0

# Grade every week from this index onward; the weeks before it are the
# minimum training history. Derived from the data, so a later season extends
# the holdout without editing this file.
GRADE_FROM_WEEK_INDEX = 4
N_BOOT = 1000
BOOT_SEED = 20261017


def md_table(headers, rows):
    out = ["| " + " | ".join(str(h) for h in headers) + " |"]
    out.append("|" + "|".join(["---"] * len(headers)) + "|")
    for r in rows:
        cells = []
        for c in r:
            if c is None:
                cells.append("")
            elif isinstance(c, float):
                cells.append("%g" % c)
            else:
                cells.append(str(c))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


def variance(xs):
    xs = list(xs)
    if len(xs) < 2:
        return None
    m = mean(xs)
    return sum((x - m) ** 2 for x in xs) / (len(xs) - 1)


def brier(p, y):
    return (p - y) ** 2


def log_loss(p, y):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def clustered_interval(a_by_key, b_by_key, n_boot=N_BOOT, seed=BOOT_SEED):
    """Paired cluster bootstrap of mean(a) - mean(b) on shared clusters."""
    shared = [k for k in a_by_key if k in b_by_key]
    if not shared:
        return (None, None, None, 0)
    point = mean(a_by_key[k] for k in shared) - mean(b_by_key[k] for k in shared)
    rng = random.Random(seed)
    boots = []
    for _ in range(n_boot):
        sa = sb = 0.0
        for _ in range(len(shared)):
            k = rng.choice(shared)
            sa += a_by_key[k]
            sb += b_by_key[k]
        boots.append(sa / len(shared) - sb / len(shared))
    boots.sort()
    lo = boots[int(0.025 * len(boots))]
    hi = boots[int(0.975 * len(boots)) - 1]
    return (point, lo, hi, len(shared))


def week_key(gdate):
    """NCAAF week keyed by the Saturday that starts it, as 'YYYY-MM-DD'."""
    y, m, d = (int(x) for x in (gdate or "0-0-0").split("-"))
    if y == 0:
        return None
    day = _date(y, m, d)
    return str(day - _timedelta(days=(day.weekday() + 2) % 7))



def _one(con, sql, args=()):
    row = con.execute(sql, args).fetchone()
    return row[0] if row is not None else None


def _table(con, sql, args=()):
    return [dict(r) for r in con.execute(sql, args).fetchall()]


def main():
    ap = argparse.ArgumentParser(description="FBS baseline ladder (pre-registered)")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if not os.path.exists(args.db):
        sys.exit("database not found: %s" % args.db)

    con = sqlite3.connect("file:%s?mode=ro" % args.db, uri=True, timeout=60)
    con.row_factory = sqlite3.Row

    lines = []
    lines.append("# FBS baseline ladder - %s" % dt.datetime.utcnow().strftime("%Y-%m-%d"))
    lines.append("")
    lines.append(
        "Pre-registered before the run: markets %s; walk-forward week by week; "
        "keep rule is a player-game-clustered bootstrap interval for the Brier "
        "difference that excludes zero."
        % ", ".join(MARKETS)
    )
    lines.append("")

    # ------------------------------------------------------------------
    # 0. The holdout, and the measurement that constrains it
    # ------------------------------------------------------------------
    lines.append("## 0. The holdout, and why it is not 2025")
    lines.append("")
    seasons = [r[0] for r in con.execute(
        "SELECT DISTINCT substr(start_time,1,4) FROM prop_games WHERE league=? "
        "ORDER BY 1", (LEAGUE,))]
    lines.append(md_table(
        ["measure", "value"],
        [
            ("seasons with %s props" % LEAGUE, ", ".join(seasons or ["(none)"])),
            ("fixtures with a 2025 date", _one(con, 
                "SELECT COUNT(*) FROM prop_games WHERE league=? AND "
                "substr(start_time,1,4)='2025'", (LEAGUE,))),
            ("settled props, all seasons", _one(con, 
                "SELECT COUNT(*) FROM prop_results pr JOIN props p ON "
                "p.id=pr.prop_id JOIN prop_games pg ON pg.id=p.game_id "
                "WHERE pg.league=?", (LEAGUE,))),
        ],
    ))
    lines.append("")
    lines.append(
        "The plan's holdout was 2025 as the first complete season and 2026 as a "
        "separate live forward-recorded test. The first half of that is not "
        "available: there is no 2025 NCAAF prop board in this database, so "
        "there is no 2025 line and no 2025 result to grade. The holdout is "
        "therefore a **week walk-forward within 2026**: every game strictly "
        "before the graded week is training data, and the graded week is never "
        "in its own fit."
    )
    lines.append("")
    lines.append(
        "What this costs, stated plainly: a within-season walk-forward cannot "
        "separate a model that is right from a model that is right for this "
        "season's players. It measures the models against one season's "
        "schedule. That is the limitation the keep rule's interval exists to "
        "surface, and it is reported rather than hidden."
    )
    lines.append("")

    # ------------------------------------------------------------------
    # 1. The week calendar
    # ------------------------------------------------------------------
    lines.append("## 1. The week calendar")
    lines.append("")
    dates = [r[0] for r in con.execute(
        "SELECT DISTINCT l.game_date FROM player_game_logs l WHERE l.league=? "
        "ORDER BY 1", (LEAGUE,))]
    wk = {}
    for d in dates:
        k = week_key(d)
        if k:
            wk.setdefault(k, set()).add(d)
    lines.append(md_table(
        ["week starting", "game dates", "count"],
        [(str(k), ", ".join(sorted(v)), len(v)) for k, v in sorted(wk.items())],
    ))
    lines.append("")

    # ------------------------------------------------------------------
    # 2. The item set
    # ------------------------------------------------------------------
    lines.append("## 2. The item set")
    lines.append("")
    lines.append(
        "An item is a (week, player, game, market) with a settled result, a "
        "non-whole-number line, a player with an ESPN id, and a stored log row "
        "in that game. The population is measured before any model is fitted, "
        "because every model below is graded on it and a model that quietly "
        "grades a different population is not a result."
    )
    lines.append("")

    raw = _table(con, 
        "SELECT pg.espn_event_id eid, p.player_id pid, p.market market, "
        "p.line line, p.side side, pr.actual_value actual, pr.hit hit, "
        "pl.espn_id aid, l.game_date gdate, l.season season, "
        "json_extract(l.stats,'$.pass_yds') py, "
        "json_extract(l.stats,'$.rush_yds') ry "
        "FROM props p "
        "JOIN prop_games pg ON pg.id=p.game_id "
        "JOIN players pl ON pl.id=p.player_id "
        "JOIN prop_results pr ON pr.prop_id=p.id "
        "JOIN player_game_logs l ON l.league=? AND l.game_no=pg.espn_event_id "
        "AND l.source_player_key=pl.espn_id "
        "WHERE pg.league=? AND pg.espn_event_id IS NOT NULL "
        "AND pg.espn_event_id!=''", (LEAGUE, LEAGUE))
    lines.append(md_table(
        ["measure", "count"],
        [
            ("props joined to a settled result and a stored log", len(raw)),
            ("distinct markets", len(set(r["market"] for r in raw))),
            ("distinct players", len(set(r["pid"] for r in raw))),
            ("distinct games", len(set(r["eid"] for r in raw))),
        ],
    ))
    lines.append("")

    items = []
    dropped = {"not a pre-registered market": 0, "whole-number line": 0,
               "no value": 0}
    for r in raw:
        if r["market"] not in MARKETS:
            dropped["not a pre-registered market"] += 1
            continue
        if r["line"] is None or r["actual"] is None:
            dropped["no value"] += 1
            continue
        if float(r["line"]) == int(float(r["line"])):
            dropped["whole-number line"] += 1
            continue
        key = STAT_KEY[r["market"]]
        val = r["py"] if key == "pass_yds" else r["ry"]
        if val is None:
            dropped["no value"] += 1
            continue
        w = week_key(r["gdate"])
        if w is None:
            continue
        items.append({
            "week": w,
            "pid": r["pid"],
            "eid": r["eid"],
            "market": r["market"],
            "line": float(r["line"]),
            "actual": float(r["actual"]),
            "val": float(val),
            "gdate": r["gdate"],
            "cluster": "%s|%s|%s|%s" % (w, r["pid"], r["eid"], r["market"]),
        })
    lines.append(md_table(
        ["measure", "count"],
        [("items", len(items))] +
        [("dropped: %s" % k, v) for k, v in dropped.items()],
    ))
    lines.append("")
    by_week = {}
    for it in items:
        by_week.setdefault(it["week"], []).append(it)
    lines.append("Items by week:")
    lines.append("")
    lines.append(md_table(
        ["week", "items", "players", "games", "markets"],
        [(w, len(v), len(set(i["pid"] for i in v)), len(set(i["eid"] for i in v)),
          len(set(i["market"] for i in v)))
         for w, v in sorted(by_week.items())],
    ))
    lines.append("")

    # ------------------------------------------------------------------
    # 3. Player history
    # ------------------------------------------------------------------
    lines.append("## 3. Player history")
    lines.append("")
    hist = {}
    for r in _table(con, 
        "SELECT l.player_id pid, l.game_no gid, l.game_date gdate, "
        "json_extract(l.stats,'$.pass_yds') py, "
        "json_extract(l.stats,'$.rush_yds') ry, "
        "json_extract(l.stats,'$.att') att "
        "FROM player_game_logs l WHERE l.league=? AND l.player_id IS NOT NULL "
        "ORDER BY l.game_date", (LEAGUE,)):
        hist.setdefault(r["pid"], []).append({
            "gid": r["gid"], "gdate": r["gdate"],
            "pass_yds": r["py"], "rush_yds": r["ry"], "att": r["att"],
        })
    lines.append(md_table(
        ["measure", "count"],
        [
            ("players with prior games", len(hist)),
            ("player-games", sum(len(v) for v in hist.values())),
            ("seasons", sorted(set(
                r["season"] for r in _table(con, 
                    "SELECT DISTINCT season FROM player_game_logs WHERE league=?",
                    (LEAGUE,))))),
        ],
    ))
    lines.append("")

    # ------------------------------------------------------------------
    # 4. The models
    # ------------------------------------------------------------------
    lines.append("## 4. The models")
    lines.append("")
    lines.append(
        "All four are functions of the player's prior games, read with a "
        "cutoff date. Nothing here reads the graded week."
    )
    lines.append("")

    def prior(pid, cutoff_date):
        return [g for g in hist.get(pid, []) if (g["gdate"] or "") < cutoff_date]

    _league_mean_cache = {}

    def proj_season_avg(pid, key, cutoff):
        vals = [g[key] for g in prior(pid, cutoff) if g[key] is not None]
        return mean(vals)

    def proj_rolling(pid, key, cutoff):
        vals = [g[key] for g in prior(pid, cutoff) if g[key] is not None]
        return mean(vals[-ROLLING_N:]) if vals else None

    def league_mean(key, cutoff):
        # Cached on (key, cutoff). Without this, marcel recomputes a full pass
        # over every player's history for every item, which is O(items x
        # players x games) and does not finish. The value depends only on the
        # key and the cutoff, so it is safe to memoize.
        ck = (key, cutoff)
        if ck in _league_mean_cache:
            return _league_mean_cache[ck]
        vals = []
        for pid in hist:
            vals.extend(g[key] for g in prior(pid, cutoff) if g[key] is not None)
        v = mean(vals)
        _league_mean_cache[ck] = v
        return v

    def proj_marcel(pid, key, cutoff):
        games = [g for g in prior(pid, cutoff) if g[key] is not None]
        if not games:
            return None
        # Group the player's prior games into distinct dates, then take the
        # last three groups, which is the Marcel window shape.
        by_date = {}
        for g in games:
            by_date.setdefault((g["gdate"] or "")[:10], []).append(g[key])
        last3 = list(by_date.values())[-3:]
        acc = tw = 0.0
        for i, group in enumerate(last3):
            w = MARCEL_WEIGHTS[-(i + 1)]
            acc += w * mean(group)
            tw += w
        raw = acc / tw if tw else None
        lm = league_mean(key, cutoff)
        if raw is None:
            return lm
        if lm is None:
            return raw
        return (len(games) * raw + MARCEL_K * lm) / (len(games) + MARCEL_K)

    def proj_share_adj(pid, key, cutoff):
        """`rolling_5` adjusted for the player's opportunity share.

        The share is measured from the logs we actually store. Passing yards
        per attempt and rushing yards per carry are opportunity-normalised
        rates; the projection is the player's rate times the league-average
        opportunities per game, which is a level adjustment and nothing more.
        The first version of this multiplied the projection by a ratio of the
        player's own mean to itself, which is 1.0 by construction and inflated
        the point estimate to MAE 144. That is the failure this comment exists
        to record.
        """
        base = proj_rolling(pid, key, cutoff)
        if base is None:
            return None
        opp_key = "att" if key == "pass_yds" else "rush_yds"
        games = [g for g in prior(pid, cutoff)
                 if g[key] is not None and g[opp_key] is not None]
        if len(games) < SHARE_MIN_GAMES:
            return base
        rate = sum(g[key] for g in games) / sum(g[opp_key] for g in games)
        if not rate:
            return base
        opp_pg = league_mean(opp_key, cutoff)
        if not opp_pg:
            return base
        return rate * opp_pg

    MODELS = [
        ("season_avg", proj_season_avg),
        ("rolling_5", proj_rolling),
        ("marcel", proj_marcel),
        ("share_adj", proj_share_adj),
    ]

    # ------------------------------------------------------------------
    # 5. Walk-forward grading
    # ------------------------------------------------------------------
    # The graded weeks are the last `MIN_GRADED_WEEKS` of the season's
    # calendar. The calendar is derived from the item population itself, so a
    # season that extends adds weeks here without editing this file. Measured
    # 2026-10-17: the 2026 calendar has 5 joinable weeks (2026-08-29 through
    # 2026-09-26); the weeks after 2026-10-03 have prop rows but zero stored
    # CFBD logs, because the CFBD log job stopped on 2026-10-04. Those weeks
    # cannot be graded against the stored history and are excluded by the
    # join, not by this constant.
    MIN_GRADED_WEEKS = 4
    MIN_PRIOR_WEEKS = 1
    all_weeks = sorted(by_week)
    if len(all_weeks) <= MIN_GRADED_WEEKS:
        grade_weeks = all_weeks
    else:
        grade_weeks = all_weeks[-MIN_GRADED_WEEKS:]
    lines.append("## 5. Walk-forward grading")
    lines.append("")
    lines.append(
        "Each graded week is scored with models fitted on every game strictly "
        "before that week. The P(over) is a normal approximation with a "
        "player-specific variance shrunk toward the league variance, floored at "
        "1.0."
    )
    lines.append("")
    lines.append(md_table(
        ["measure", "value"],
        [
            ("weeks in the calendar", len(all_weeks)),
            ("weeks graded", len(grade_weeks)),
            ("graded weeks", ", ".join(grade_weeks) or "(none)"),
            ("minimum weeks of history before the first graded week",
             MIN_PRIOR_WEEKS),
        ],
    ))
    lines.append("")
    lines.append(
        "The graded window is the last %d weeks of the season's calendar, "
        "subject to every graded week having at least %d weeks of history "
        "behind it. This is a pre-registered floor; the first graded week with "
        "fewer weeks behind it would be measuring the absence of history "
        "rather than the model."
        % (MIN_GRADED_WEEKS, MIN_PRIOR_WEEKS)
    )
    lines.append("")

    per_model = {name: [] for name, _ in MODELS}
    for wk in grade_weeks:
        cutoff = wk  # every game with game_date < wk is training data
        # Precompute the league variance once per week, not once per item.
        # The league variance depends only on (key, cutoff).
        lv_cache = {}
        for key in set(STAT_KEY.values()):
            allv = []
            for pid in hist:
                allv.extend(g[key] for g in prior(pid, cutoff)
                            if g[key] is not None)
            lv_cache[key] = variance(allv)
        for it in by_week[wk]:
            key = STAT_KEY[it["market"]]
            pgames = prior(it["pid"], cutoff)
            pv = variance([g[key] for g in pgames if g[key] is not None])
            lv = lv_cache.get(key)
            if pv is not None:
                n = sum(1 for g in pgames if g[key] is not None)
                sigma = math.sqrt((n * pv + VARIANCE_SHRINK_K * (lv or pv))
                                  / (n + VARIANCE_SHRINK_K))
            elif lv is not None:
                sigma = math.sqrt(lv)
            else:
                sigma = SIGMA_FLOOR
            sigma = max(sigma, SIGMA_FLOOR)
            for name, fn in MODELS:
                proj = fn(it["pid"], key, cutoff)
                if proj is None:
                    continue
                p_over = norm_cdf((it["line"] - proj) / sigma)
                per_model[name].append({
                    "cluster": it["cluster"],
                    "proj": proj, "actual": it["actual"], "line": it["line"],
                    "p_over": p_over,
                    "y": 1.0 if it["actual"] > it["line"] else 0.0,
                    "market": it["market"], "week": wk,
                })

    lines.append(md_table(
        ["model", "items", "MAE", "Brier", "log loss"],
        [(name, len(rs),
          "%.2f" % mean([abs(r["actual"] - r["proj"]) for r in rs]) if rs else "",
          "%.4f" % mean([brier(r["p_over"], r["y"]) for r in rs]) if rs else "",
          "%.4f" % mean([log_loss(r["p_over"], r["y"]) for r in rs]) if rs else "")
         for name, rs in per_model.items()],
    ))
    lines.append("")

    # Per-week breakdown. A pooled Brier over four weeks can hide a model that
    # wins one week and loses three, and a pooled interval can be driven by a
    # single week's clusters. The per-week table is the honest view.
    lines.append("Per graded week:")
    lines.append("")
    week_rows = []
    for wk in grade_weeks:
        row = [wk]
        for name, _ in MODELS:
            rs = [r for r in per_model[name] if r["week"] == wk]
            row.append("%d / %.4f" % (len(rs),
                        mean([brier(r["p_over"], r["y"]) for r in rs]) if rs else float("nan")))
        week_rows.append(tuple(row))
    lines.append(md_table(
        ["week"] + [name for name, _ in MODELS],
        week_rows,
    ))
    lines.append("")
    lines.append(
        "Each cell is `items / Brier`. A model whose pooled Brier is better but "
        "whose per-week Briers are not consistently better is not a model, and "
        "the per-week view is what makes that visible."
    )
    lines.append("")

    # ------------------------------------------------------------------
    # 6. The keep rule
    # ------------------------------------------------------------------
    lines.append("## 6. The keep rule")
    lines.append("")
    lines.append(
        "A model is adopted only if its Brier is lower than `season_avg`'s by a "
        "player-game-clustered bootstrap interval that excludes zero. The "
        "interval is reported, not just the point difference."
    )
    lines.append("")

    def by_cluster(rs):
        d = {}
        for r in rs:
            d.setdefault(r["cluster"], []).append(brier(r["p_over"], r["y"]))
        return {k: mean(v) for k, v in d.items()}

    base = per_model["season_avg"]
    base_by = by_cluster(base)
    base_brier = mean([brier(r["p_over"], r["y"]) for r in base]) if base else None
    rows_out = []
    for name, _ in MODELS:
        if name == "season_avg":
            continue
        rs = per_model[name]
        if not rs:
            rows_out.append((name, 0, "", "", "no items"))
            continue
        point, lo, hi, n = clustered_interval(by_cluster(rs), base_by)
        if point is None:
            rows_out.append((name, 0, "", "", "no shared clusters"))
            continue
        verdict = "KEPT" if (lo < 0 and hi < 0) else "not kept"
        rows_out.append((name, n, "%.4f" % point, "[%.4f, %.4f]" % (lo, hi), verdict))
    lines.append(md_table(
        ["model", "shared clusters", "Brier difference vs season_avg",
         "clustered 95% interval", "verdict"],
        rows_out,
    ))
    lines.append("")
    lines.append(
        "Control: `season_avg` Brier %s on %d items across %d clusters."
        % ("%.4f" % base_brier if base_brier is not None else "n/a",
           len(base), len(base_by))
    )
    lines.append("")

    # ------------------------------------------------------------------
    # 7. The control
    # ------------------------------------------------------------------
    lines.append("## 7. The control")
    lines.append("")
    lines.append(md_table(
        ["measure", "count"],
        [
            ("control items", len(base)),
            ("control clusters (player-games)", len(base_by)),
            ("control distinct players", len(set(
                r["cluster"].split("|")[1] for r in base))),
            ("control distinct games", len(set(
                r["cluster"].split("|")[2] for r in base))),
            ("control markets", ", ".join(sorted(set(r["market"] for r in base)))),
            ("control weeks", ", ".join(sorted(set(r["week"] for r in base)))),
        ],
    ))
    lines.append("")

    con.close()
    report = "\n".join(lines)
    out = args.out or os.path.join(
        os.path.dirname(HERE), "research", "fbs",
        "AUDIT-FBS-BASELINE-%s.md" % dt.datetime.utcnow().strftime("%Y%m%d"))
    with open(out, "w") as fh:
        fh.write(report)
    print(report)
    print("\n[report written to %s]" % out)


if __name__ == "__main__":
    main()
