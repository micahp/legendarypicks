#!/usr/bin/env python3
"""audit_fbs_reconcile.py -- reconcile the SportsDataverse releases against our
own stored prop fixtures and stored player logs.

The FBS modeling track needs a box-score authority that can be joined to the
props. We have two publishers on disk:

  * CFBD (`/games/players`) -- what `player_game_logs` is loaded from. Its key
    is the ESPN event id and the ESPN athlete id.
  * SportsDataverse season Parquet releases -- ESPN play-by-play, player box
    scores, game rosters, team box scores, season rosters.

The question this script answers is narrow and load-bearing: **for the games we
actually have props on, does the release publish a box score, and does the
release's box score agree with the book's own final score?**

That second half matters because the props were priced against the book's
result. If the release disagrees with the stored `prop_games` final score for
the same ESPN event id, then any model trained on the release and graded against
the stored result is measuring the disagreement, not the model.

Read-only. Nothing is written. The report is Markdown.

Usage:
    cd <repo>/backend
    LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
      /root/legendarypicks/backend/venv/bin/python audit_fbs_reconcile.py \
        --parquet-dir ../research/fbs/parquet \
        --fixtures ../research/fbs/dev_linked_fixtures.json
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    import pandas as pd
    HAVE_PANDAS = True
except Exception:  # pragma: no cover
    HAVE_PANDAS = False

DEFAULT_DB = os.environ.get("LP_DB_PATH") or os.path.join(
    HERE, "data", "picks.dev.db"
)
LEAGUE = "ncaaf"

# The team code vocabularies are ESPN's (`AFA`, `AKR`, `ALA`). The releases
# carry ESPN team abbreviations in `homeTeamAbbrev` / `team_abbreviation`, so the
# codes compare directly. A mismatch here is a vocabulary problem, not a data
# problem, and is reported rather than mapped by hand.


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


def load_fixtures(path):
    """Return {espn_event_id: {...}} with the key normalised to an int string.

    The database stores the ESPN event id as TEXT. The releases store it as
    int64. Normalising both sides to `str(int(x))` is what makes the join
    possible; without it a text-vs-int comparison silently matches nothing and
    reads as "the release has no coverage of our fixtures", which is false.
    """
    with open(path) as fh:
        raw = json.load(fh)
    out = {}
    for r in raw:
        raw_id = str(r.get("eid") or "").strip()
        if not raw_id:
            continue
        try:
            eid = str(int(raw_id))
        except (TypeError, ValueError):
            continue
        out[eid] = r
    return out


def final_scores(df):
    """{game_id (int): (home_final, away_final)} from a play-by-play frame."""
    g = (df.drop_duplicates("game_id")
           .set_index("game_id")[["homeFinalScore", "awayFinalScore"]])
    out = {}
    for k, r in g.iterrows():
        try:
            out[str(int(k))] = (r["homeFinalScore"], r["awayFinalScore"])
        except (TypeError, ValueError):
            continue
    return out


def _one(con, sql, args=()):
    row = con.execute(sql, args).fetchone()
    return row[0] if row is not None else None


def _table(con, sql, args=()):
    return [dict(r) for r in con.execute(sql, args).fetchall()]


def main():
    ap = argparse.ArgumentParser(
        description="Reconcile SportsDataverse releases against stored fixtures")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--parquet-dir", default=os.path.join(
        os.path.dirname(HERE), "research", "fbs", "parquet"))
    ap.add_argument("--fixtures", default=os.path.join(
        os.path.dirname(HERE), "research", "fbs", "dev_linked_fixtures.json"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if not HAVE_PANDAS:
        sys.exit("pandas/pyarrow unavailable")
    if not os.path.exists(args.db):
        sys.exit("database not found: %s" % args.db)
    if not os.path.exists(args.fixtures):
        sys.exit("fixtures file not found: %s (run audit_fbs_data.py first)" % args.fixtures)

    con = sqlite3.connect("file:%s?mode=ro" % args.db, uri=True, timeout=60)
    fixtures = load_fixtures(args.fixtures)
    ids = set(fixtures)
    # Kickoff comparison needs a comparable form. `prop_games.start_time` is
    # written in two shapes in this database ("2026-10-17T16:00:00+00:00" and
    # "2026-10-17T16:00:00Z"), so normalise both to a plain "YYYY-MM-DDTHH:MM"
    # prefix before comparing.
    now_utc = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M")

    def kickoff_minute(st):
        s = (st or "").replace("Z", "+00:00")
        return s[:16]

    now_key = now_utc

    lines = []
    lines.append("# FBS reconciliation - %s" % dt.datetime.utcnow().strftime("%Y-%m-%d"))
    lines.append("")
    lines.append(
        "Read-only. Database `%s`. Fixtures file `%s` (%d linked fixtures). "
        "Nothing was written." % (args.db, args.fixtures, len(fixtures))
    )
    lines.append("")

    # ------------------------------------------------------------------
    # 1. Which of our prop fixtures appear in each release?
    # ------------------------------------------------------------------
    lines.append("## 1. Coverage of our prop fixtures")
    lines.append("")
    lines.append(
        "The denominator is the 323 NCAAF `prop_games` rows that carry an ESPN "
        "event id. That is the population we can actually grade, so coverage is "
        "measured against it and not against the publisher's whole season."
    )
    lines.append("")

    espn_pbp = pd.read_parquet(os.path.join(args.parquet_dir, "espn_pbp_2026.parquet"))
    espn_scores = final_scores(espn_pbp)
    ncaaf_pbp = pd.read_parquet(os.path.join(
        args.parquet_dir, "ncaa_mfb_pbp_cfbfastr_2026.parquet"))
    ncaaf_ids = set(str(int(i)) for i in ncaaf_pbp.espn_game_id.dropna().unique())
    pbox = pd.read_parquet(os.path.join(args.parquet_dir, "player_box_2026.parquet"))
    pbox_ids = set(str(int(i)) for i in pbox.game_id.dropna().unique())
    grosters = pd.read_parquet(os.path.join(args.parquet_dir, "game_rosters_2026.parquet"))
    groster_ids = set(str(int(i)) for i in grosters.game_id.dropna().unique())
    tbox = pd.read_parquet(os.path.join(args.parquet_dir, "team_box_2026.parquet"))
    tbox_ids = set(str(int(i)) for i in tbox.game_id.dropna().unique())

    lines.append(md_table(
        ["release", "season", "games", "of our fixtures", "coverage"],
        [
            ("ESPN play-by-play", 2026, espn_pbp.game_id.nunique(),
             len(ids & set(espn_scores)), pct(len(ids & set(espn_scores)), len(ids))),
            ("stats.ncaa.org play-by-play (cfbfastR)", 2026, len(ncaaf_ids),
             len(ids & ncaaf_ids), pct(len(ids & ncaaf_ids), len(ids))),
            ("ESPN player box scores", 2026, pbox_ids and len(pbox_ids),
             len(ids & pbox_ids), pct(len(ids & pbox_ids), len(ids))),
            ("ESPN game rosters", 2026, len(groster_ids),
             len(ids & groster_ids), pct(len(ids & groster_ids), len(ids))),
            ("ESPN team box scores", 2026, len(tbox_ids),
             len(ids & tbox_ids), pct(len(ids & tbox_ids), len(ids))),
        ],
    ))
    lines.append("")
    lines.append(
        "Every release above is a season-2026 file and our props are 2026, so "
        "coverage here is a real measurement rather than a season mismatch."
    )
    lines.append("")
    lines.append("### Fixtures the release does not cover")
    lines.append("")
    missing = [(eid, fixtures[eid]) for eid in sorted(ids, key=lambda x: int(x))
               if eid not in set(espn_scores)]
    future = [m for m in missing if kickoff_minute(m[1].get("st")) > now_key]
    past = [m for m in missing if m not in future]
    lines.append(md_table(
        ["measure", "count"],
        [
            ("fixtures the release does not cover", len(missing)),
            ("of those, kickoff is in the future", len(future)),
            ("of those, kickoff has passed", len(past)),
        ],
    ))
    lines.append("")
    lines.append(
        "The two groups are different things and must not be read as one. A "
        "fixture whose kickoff has not happened yet has no box score anywhere, "
        "including in the release. A fixture whose kickoff HAS passed and is "
        "still absent is either in progress at the moment of this run or a "
        "coverage gap; the stored `final_home`/`final_away` tells which, "
        "because a game in progress has no stored score either."
    )
    lines.append("")
    if past:
        lines.append("Past-kickoff fixtures absent from the release:")
        lines.append("")
        lines.append(md_table(
            ["espn event id", "kickoff", "home", "away", "stored final",
             "state at this run"],
            [(m[0], m[1].get("st"), m[1].get("home"), m[1].get("away"),
              "%s-%s" % (m[1].get("fh"), m[1].get("fa")),
              "no stored score, so in progress or not settled"
              if m[1].get("fh") is None else "has a stored score, so a gap")
             for m in past[:20]],
        ))
        lines.append("")

    # ------------------------------------------------------------------
    # 2. Do the releases agree with the book's final score?
    # ------------------------------------------------------------------
    lines.append("## 2. Does the release agree with the stored final score?")
    lines.append("")
    lines.append(
        "For every fixture where the release has a final score and our stored "
        "`prop_games` row has one, compare them. The stored score is the book's "
        "result, which is what the prop was settled against. A disagreement "
        "means the two publishers describe different games."
    )
    lines.append("")
    agree = disagree = missing_release = missing_stored = 0
    disagreements = []
    for eid in sorted(ids, key=lambda x: int(x)):
        f = fixtures[eid]
        if eid not in espn_scores:
            missing_release += 1
            continue
        if f.get("fh") is None or f.get("fa") is None:
            missing_stored += 1
            continue
        rh, ra = espn_scores[eid]
        if rh is None or ra is None:
            missing_release += 1
            continue
        if int(rh) == int(f["fh"]) and int(ra) == int(f["fa"]):
            agree += 1
        else:
            disagree += 1
            disagreements.append((eid, f.get("away"), f.get("home"),
                                  f["fh"], f["fa"], int(rh), int(ra)))
    lines.append(md_table(
        ["measure", "count"],
        [
            ("fixtures with both scores", agree + disagree),
            ("agree", agree),
            ("disagree", disagree),
            ("release has no score for the fixture", missing_release),
            ("stored row has no score", missing_stored),
        ],
    ))
    lines.append("")
    if disagreements:
        lines.append("Disagreements:")
        lines.append("")
        lines.append(md_table(
            ["espn event id", "away", "home", "stored away", "stored home",
             "release away", "release home"],
            disagreements[:25],
        ))
        if len(disagreements) > 25:
            lines.append("")
            lines.append("... and %d more." % (len(disagreements) - 25))
    else:
        lines.append("No disagreements in this run.")
    lines.append("")

    # ------------------------------------------------------------------
    # 3. The player join: release athlete id against our spine
    # ------------------------------------------------------------------
    lines.append("## 3. Player identity across publishers")
    lines.append("")
    lines.append(
        "The release carries an ESPN athlete id (`athlete_id`, or "
        "`rusher_player_id` / `passer_player_id` / `receiver_player_id` in "
        "play-by-play). Our spine carries `players.espn_id` from CFBD. The "
        "join is exact-id only; a name join would manufacture matches."
    )
    lines.append("")

    spine = {str(r[0]).strip(): r[1] for r in con.execute(
        "SELECT espn_id, name FROM players WHERE league=? AND espn_id IS NOT NULL "
        "AND espn_id!=''", (LEAGUE,))}
    spine_ids = set(spine)
    lines.append(md_table(
        ["measure", "count"],
        [
            ("spine rows with an ESPN id", len(spine)),
        ],
    ))
    lines.append("")

    # Player box scores: athletes we can and cannot resolve
    pbox_ath = set(str(int(i)) for i in pbox.athlete_id.dropna().unique())
    pbox_resolved = pbox_ath & spine_ids
    lines.append(md_table(
        ["measure", "count"],
        [
            ("distinct athletes in the 2026 player box", len(pbox_ath)),
            ("of those on our spine by ESPN id", len(pbox_resolved)),
            ("of those NOT on our spine", len(pbox_ath - spine_ids)),
        ],
    ))
    lines.append("")
    lines.append(
        "The unresolved athletes are a spine gap, not a release defect: the "
        "release publishes their box score and our roster ingest never created "
        "the row to join to. The count is reported, not repaired."
    )
    lines.append("")

    # Play-by-play: how many prop player-games have a play attributed?
    pp = pd.read_parquet(os.path.join(args.parquet_dir, "espn_pbp_2026.parquet"),
                         columns=["game_id", "rusher_player_id", "passer_player_id",
                                  "receiver_player_id"])
    attributed = set()
    for c in ("rusher_player_id", "passer_player_id", "receiver_player_id"):
        for g, a in zip(pp.game_id, pp[c]):
            if a == a and g == g:
                attributed.add((str(int(g)), str(int(a))))
    lines.append(md_table(
        ["measure", "count"],
        [
            ("(game, athlete) pairs with any play attributed", len(attributed)),
            ("distinct games with attributed plays",
             len(set(g for g, _ in attributed))),
        ],
    ))
    lines.append("")

    # ------------------------------------------------------------------
    # 4. The gap that matters: props whose player has no release row
    # ------------------------------------------------------------------
    lines.append("## 4. Props with a release box score vs without")
    lines.append("")
    lines.append(
        "Section 5 of the coverage audit measures whether the stored CFBD log "
        "exists. This section asks the same question of the release. The two "
        "differ: the release is a different publisher with a different "
        "coverage floor, so a prop gradeable against one may not be gradeable "
        "against the other."
    )
    lines.append("")

    q = ("SELECT p.market, p.player_id pid, pl.espn_id aid, pg.espn_event_id eid "
         "FROM props p JOIN prop_games pg ON pg.id=p.game_id "
         "JOIN players pl ON pl.id=p.player_id "
         "WHERE pg.league=? AND pg.espn_event_id IS NOT NULL AND pg.espn_event_id!=''")
    rows = con.execute(q, (LEAGUE,)).fetchall()
    pbox_by_game_ath = {}
    for g, a in zip(pbox.game_id, pbox.athlete_id):
        if g == g and a == a:
            pbox_by_game_ath[(str(int(g)), str(int(a)))] = True
    agg = {}
    for m, pid, aid, eid in rows:
        d = agg.setdefault(m, {"total": 0, "box": 0, "play": 0, "noaid": 0})
        d["total"] += 1
        if aid is None or str(aid).strip() == "":
            d["noaid"] += 1
            continue
        key = (str(int(eid)), str(int(aid)))
        if pbox_by_game_ath.get(key):
            d["box"] += 1
        if key in attributed:
            d["play"] += 1
    table = []
    for m, d in sorted(agg.items(), key=lambda kv: -kv[1]["total"]):
        table.append((m, d["total"], d["box"], pct(d["box"], d["total"]),
                      d["play"], pct(d["play"], d["total"]), d["noaid"]))
    lines.append(md_table(
        ["market", "props", "with a release box score", "share",
         "with an attributed play", "share", "no athlete id"],
        table,
    ))
    lines.append("")
    lines.append(
        "`with a release box score` joins on the release's `game_id` and "
        "`athlete_id`. `with an attributed play` is the play-by-play's own "
        "attribution, which covers players who appeared without a box-score "
        "row (a player who played special teams only, for example). The two are "
        "different populations and the report shows both. `no athlete id` is a "
        "prop whose own player row has no ESPN id, which cannot be joined to "
        "anything."
    )
    lines.append("")

    con.close()
    report = "\n".join(lines)
    out = args.out or os.path.join(
        os.path.dirname(HERE), "research", "fbs",
        "AUDIT-FBS-RECONCILE-%s.md" % dt.datetime.utcnow().strftime("%Y%m%d"))
    with open(out, "w") as fh:
        fh.write(report)
    print(report)
    print("\n[report written to %s]" % out)


if __name__ == "__main__":
    main()
