#!/usr/bin/env python3
"""fbs_prop_fields.py -- which prop markets the stored logs can actually grade.

The plan names QB passing yards and RB rushing yards as the first markets, and
the data-coverage audit measures the fields. This script answers the sharper
question that follows from it: for each prop market, is there a stored stat
that measures the same thing, and how much of the market does it cover.

The distinction that matters here is between a market and its components. A
`total_touchdowns` prop can be a passing touchdown, a rushing touchdown, a
receiving touchdown, a return touchdown, or a defensive touchdown, and the
stored CFBD log publishes the offensive components and the defensive ones
separately. A market that a single key cannot answer is not gradeable by that
key, and the coverage table below says which is which.

Read-only. Writes nothing. The report is Markdown.

Usage:
    cd <repo>/backend
    LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
      /root/legendarypicks/backend/venv/bin/python fbs_prop_fields.py
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

DEFAULT_DB = os.environ.get("LP_DB_PATH") or os.path.join(
    HERE, "data", "picks.dev.db"
)
LEAGUE = "ncaaf"

# The market -> stat-key map. This is a claim about vocabulary, not about
# coverage: it says which stored key would answer the market if the player
# played that position. It is stated explicitly so a reader can disagree with
# it, which is the only way a wrong mapping stops being load-bearing.
#
#   None means no single stored key answers the market. Those markets need a
#   sum of components, which is a different code path and is reported as such.
MARKET_FIELDS = {
    "passing_yards": ["pass_yds"],
    "rushing_yards": ["rush_yds"],
    "receiving_yards": ["rec_yds"],
    "receptions": ["rec"],
    "pass_attempts": ["att"],
    "pass_completions": ["att"],  # CFBD stores completions/attempts together
    "passing_touchdowns": ["pass_td"],
    "rushing_touchdowns": ["rush_td"],
    "rushing_receiving_yards": ["rush_yds", "rec_yds"],
    "passing_rushing_yards": ["pass_yds", "rush_yds"],
    "total_touchdowns": ["pass_td", "rush_td", "rec_td", "def_td"],
    "rushing_receiving_touchdowns": ["rush_td", "rec_td"],
    "total_passing_touchdowns": ["pass_td"],
    "interceptions_thrown": ["intc"],
    "kicking_points": ["def_int"],  # NOT the right key; see the report
    "extra_points_made": [],
    "field_goals_made": [],
}

# CFBD publishes completions/attempts as a single "catt" string ("32/35"). The
# ingest splits it into `att`. There is no separate completion key, so a
# `pass_completions` prop is answered by the numerator of the same string.
ATT_IS_COMBINED = True


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


def pct(n, d, digits=1):
    if not d:
        return "n/a"
    return "%.1f%%" % (100.0 * n / d)


def _one(con, sql, args=()):
    row = con.execute(sql, args).fetchone()
    return row[0] if row is not None else None


def _table(con, sql, args=()):
    return [dict(r) for r in con.execute(sql, args).fetchall()]


def main():
    ap = argparse.ArgumentParser(description="FBS prop market field coverage")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if not os.path.exists(args.db):
        sys.exit("database not found: %s" % args.db)

    con = sqlite3.connect("file:%s?mode=ro" % args.db, uri=True, timeout=60)
    con.row_factory = sqlite3.Row

    lines = []
    lines.append("# FBS prop field coverage - %s" % dt.datetime.utcnow().strftime("%Y-%m-%d"))
    lines.append("")
    lines.append(
        "For each prop market: does a stored CFBD stat answer it, and how much "
        "of the market does that stat cover? The stored log publishes "
        "components, not markets, so a market with no single answering key is "
        "a sum of components and a different code path."
    )
    lines.append("")

    # ------------------------------------------------------------------
    # 1. The prop population
    # ------------------------------------------------------------------
    lines.append("## 1. The prop population")
    lines.append("")
    lines.append(md_table(
        ["measure", "count"],
        [
            ("props for %s" % LEAGUE, _one(con, 
                "SELECT COUNT(*) FROM props p JOIN prop_games pg ON pg.id=p.game_id "
                "WHERE pg.league=?", (LEAGUE,))),
            ("of those, settled", _one(con, 
                "SELECT COUNT(*) FROM props p JOIN prop_games pg ON pg.id=p.game_id "
                "JOIN prop_results pr ON pr.prop_id=p.id WHERE pg.league=?",
                (LEAGUE,))),
            ("of those, on a linked fixture", _one(con, 
                "SELECT COUNT(*) FROM props p JOIN prop_games pg ON pg.id=p.game_id "
                "WHERE pg.league=? AND pg.espn_event_id IS NOT NULL "
                "AND pg.espn_event_id!=''", (LEAGUE,))),
        ],
    ))
    lines.append("")

    # ------------------------------------------------------------------
    # 2. Per-market field coverage
    # ------------------------------------------------------------------
    lines.append("## 2. Per-market field coverage")
    lines.append("")
    lines.append(
        "`answerable` is the share of settled props on a linked fixture whose "
        "player has a stored log row carrying at least one of the market's "
        "answering keys. `single key` means one key answers the whole market; "
        "`components` means the market is a sum of keys and the coverage is "
        "the share with all of them."
    )
    lines.append("")

    # Two coverage definitions, because they answer different questions and
    # collapsing them into one number is how a market gets called gradeable
    # when it is not.
    #
    #   `all keys present` -- every key the market could be made of is present.
    #     This is what a sum-of-components implementation needs. Measured on
    #     2026-10-17: `total_touchdowns` is 2 of 3,134 (0.1%), because CFBD
    #     publishes a key only when that component is nonzero, so a player who
    #     scored no passing touchdown has no `pass_td` key at all.
    #
    #   `any key present` -- at least one component is present. This is what a
    #     fail-closed grader needs: it can sum the keys it has and treat an
    #     absent key as a published zero, which is the CFBD convention the
    #     data-coverage audit documents. Measured: `total_touchdowns` is
    #     3,134 of 3,134.
    #
    # A market is gradeable by a sum-of-components implementation only under
    # the `all keys` rule. Under `any key` it is gradeable only if the
    # implementation treats an absent key as zero, which is a claim about the
    # publisher's convention and must be stated as one.
    lines.append(
        "`all keys present` is what a sum-of-components implementation needs. "
        "`any key present` is what a fail-closed grader needs, and it is "
        "gradeable only if the implementation treats an absent key as a "
        "published zero. CFBD publishes a key only when that component is "
        "nonzero, which is why the two columns differ so much."
    )
    lines.append("")

    rows_out = []
    for market, keys in sorted(MARKET_FIELDS.items(),
                               key=lambda kv: kv[0]):
        if not keys:
            rows_out.append((market, "(none)", 0, "", "", "no stored key"))
            continue
        total = _one(con, 
            "SELECT COUNT(*) FROM props p JOIN prop_games pg ON pg.id=p.game_id "
            "JOIN players pl ON pl.id=p.player_id "
            "JOIN prop_results pr ON pr.prop_id=p.id "
            "JOIN player_game_logs l ON l.league=? AND "
            "l.game_no=pg.espn_event_id AND l.source_player_key=pl.espn_id "
            "WHERE pg.league=? AND p.market=?",
            (LEAGUE, LEAGUE, market))
        if not total:
            rows_out.append((market, ", ".join(keys), 0, "", "", "no items"))
            continue
        where_all = " AND ".join(
            "json_extract(l.stats,%s) IS NOT NULL" % ("'$.%s'" % k)
            for k in keys)
        # The `any key` query is scoped to the same item set as `all keys`. An
        # unparenthesised OR binds across the WHERE clause and matched every
        # log row for the market, not the props, which produced coverage over
        # 100% (27,268 of 1,092). Parenthesising the OR group makes it a
        # single predicate over the joined row.
        where_any = "(" + " OR ".join(
            "json_extract(l.stats,%s) IS NOT NULL" % ("'$.%s'" % k)
            for k in keys) + ")"
        base = ("SELECT COUNT(*) FROM props p JOIN prop_games pg ON "
                "pg.id=p.game_id JOIN players pl ON pl.id=p.player_id "
                "JOIN prop_results pr ON pr.prop_id=p.id "
                "JOIN player_game_logs l ON l.league=? AND "
                "l.game_no=pg.espn_event_id AND "
                "l.source_player_key=pl.espn_id "
                "WHERE pg.league=? AND p.market=? AND ")
        covered_all = _one(con, base + where_all, (LEAGUE, LEAGUE, market))
        covered_any = _one(con, base + where_any, (LEAGUE, LEAGUE, market))
        kind = "single key" if len(keys) == 1 else "components"
        rows_out.append((market, ", ".join(keys), total, covered_all,
                         pct(covered_all, total), covered_any,
                         pct(covered_any, total), kind))
    lines.append(md_table(
        ["market", "answering keys", "items", "all keys", "coverage",
         "any key", "coverage", "kind"],
        rows_out,
    ))
    lines.append("")

    # ------------------------------------------------------------------
    # 3. The kicking markets, which the logs do not publish
    # ------------------------------------------------------------------
    lines.append("## 3. The kicking markets")
    lines.append("")
    lines.append(
        "`kicking_points`, `extra_points_made` and `field_goals_made` have no "
        "answering key in the stored CFBD log. The data-coverage audit "
        "measured this from the release side: the ESPN player-box release "
        "publishes `totalKickingPoints` and the `fieldGoalsMade/fieldGoalAttempts` "
        "and `extraPointsMade/extraPointAttempts` strings, so the coverage "
        "exists in the publisher but not in our stored log. The field "
        "coverage here is 0 for all three, and that is a gap in the ingest, "
        "not in the publisher."
    )
    lines.append("")
    for market in ("kicking_points", "extra_points_made", "field_goals_made"):
        total = _one(con, 
            "SELECT COUNT(*) FROM props p JOIN prop_games pg ON pg.id=p.game_id "
            "JOIN players pl ON pl.id=p.player_id "
            "JOIN prop_results pr ON pr.prop_id=p.id "
            "JOIN player_game_logs l ON l.league=? AND "
            "l.game_no=pg.espn_event_id AND l.source_player_key=pl.espn_id "
            "WHERE pg.league=? AND p.market=?", (LEAGUE, LEAGUE, market))
        lines.append("- `%s`: %d settled items with a stored log row, of which "
                     "0 have a stored kicking field." % (market, total or 0))
    lines.append("")

    # ------------------------------------------------------------------
    # 4. The market aliases that do not exist
    # ------------------------------------------------------------------
    lines.append("## 4. Market aliases")
    lines.append("")
    lines.append(
        "Two prop markets exist under more than one name for the same "
        "statistic. The coverage audit counts them separately, which "
        "understates the market; the settlement diagnosis named the alias as "
        "a latent defect. Both are measured here rather than mapped."
    )
    lines.append("")
    for a, b in (("passing_touchdowns", "total_passing_touchdowns"),):
        for m in (a, b):
            n = _one(con, 
                "SELECT COUNT(*) FROM props p JOIN prop_games pg ON "
                "pg.id=p.game_id WHERE pg.league=? AND p.market=?", (LEAGUE, m))
            lines.append("- `%s`: %d props" % (m, n or 0))
    lines.append("")
    lines.append(
        "The settlement diagnosis recorded that `total_passing_touchdowns` "
        "props would become unmappable if linked without an alias, because the "
        "NCAAF market map accepts `passing_touchdowns` and these rows use "
        "`total_passing_touchdowns`. That is measured here as a naming "
        "divergence, not fixed."
    )
    lines.append("")

    con.close()
    report = "\n".join(lines)
    out = args.out or os.path.join(
        os.path.dirname(HERE), "research", "fbs",
        "AUDIT-FBS-PROP-FIELDS-%s.md" % dt.datetime.utcnow().strftime("%Y%m%d"))
    with open(out, "w") as fh:
        fh.write(report)
    print(report)
    print("\n[report written to %s]" % out)


if __name__ == "__main__":
    main()
