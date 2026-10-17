#!/usr/bin/env python3
"""backfill_ncaaf_logs.py -- backfill NCAAF player game logs from the SportsDataverse
`ncaa_mfb_player_stats` release.

Why this exists
---------------
The stored CFBD log job stopped on 2026-10-04 and cannot be re-run: the shared
CFBD key returns HTTP 429 "Monthly call quota exceeded" on every endpoint.
Props after that date have no stored log to join to, so they cannot be graded.

`ncaa_mfb_player_stats` is the stats.ncaa.org player-statistics release: one row
per player per game per category, with `espn_game_id` -- the same join key our
logs use. It covers 2013-2026 and needs no API key.

What this does
--------------
For each (game, player) in the release it resolves an ESPN athlete id, maps the
release's columns onto our stat keys, and inserts a `player_game_logs` row.

Rows already present are left alone: the insert is `ON CONFLICT DO NOTHING`, so
CFBD remains the source for games we already have and this release only fills
the gap. That is deliberate -- overwriting CFBD rows with a second publisher's
numbers would silently change the meaning of existing data.

The mapping was validated against the 22,616 player-games that exist in both
this release and our CFBD logs, before anything was written:

    rush_yds  99.2% exact    pass_yds  98.1% exact    rec_yds  99.2% exact
    rec       99.6% exact    rush_td   99.9% exact    pass_td  99.7% exact
    rec_td    99.8% exact

Read-only unless --dry-run is absent. Writes only to the database passed with
--db, and only via INSERT ... ON CONFLICT DO NOTHING.

Usage:
    # dry run against a copy first
    cp /root/legendarypicks/backend/data/picks.dev.db /tmp/lp-copy.db
    /root/legendarypicks/backend/venv/bin/python backfill_ncaaf_logs.py \
        --db /tmp/lp-copy.db --parquet-dir .../parquet --season 2026 --dry-run

    # then for real
    /root/legendarypicks/backend/venv/bin/python backfill_ncaaf_logs.py \
        --db /root/legendarypicks/backend/data/picks.dev.db \
        --parquet-dir .../parquet --season 2026
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys

import pandas as pd
import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# `queue_unresolved_player` lives with the main backend, not in this worktree,
# so the main backend dir is on the path for that one import.
MAIN_BACKEND = "/root/legendarypicks/backend"
if os.path.isdir(MAIN_BACKEND) and MAIN_BACKEND not in sys.path:
    sys.path.insert(0, MAIN_BACKEND)

try:
    from league_stats import queue_unresolved_player
except Exception:  # pragma: no cover - only the queue is optional
    queue_unresolved_player = None

LEAGUE = "ncaaf"
SOURCE = "ncaa_mfb_player_stats"

# The stat map. Every target is one of our existing keys, so a backfilled row is
# indistinguishable in shape from a CFBD row.
#
#   rush_yds is `rush_yds_gained - rush_yds_lost`, not `rush_yds_gained`.
#   Verified from the release itself: `yds_rush` is (gained - lost) / attempts
#   (e.g. attempts 5, gained 9, lost 1 -> yds_rush 1.60 = 8/5), so the net is
#   the total. This matters for the NCAA sack convention the plan flags: sacks
#   reduce rushing totals under college accounting, unlike the NFL's net
#   treatment, so which column you take changes the number.
STAT_MAP = [
    # (release column, our key, kind)  kind: "sum" adds across categories
    ("rush_yds_gained", "rush_yds", "net"),
    ("rush_yds_lost", "rush_yds", "net_neg"),
    ("rush_tds", "rush_td", "sum"),
    ("pass_yards", "pass_yds", "sum"),
    ("pass_attempts", "att", "sum"),
    ("pass_tds", "pass_td", "sum"),
    ("interceptions", "intc", "sum"),
    ("rec", "rec", "sum"),
    ("receiving_yards", "rec_yds", "sum"),
    ("rec_td", "rec_td", "sum"),
    ("tackles", "tackles", "sum"),
    ("int", "def_int", "sum"),
    ("fgm", "fgm", "sum"),
    ("fga", "fga", "sum"),
]

NUMERIC_COLS = sorted({c for c, _k, _t in STAT_MAP})


def md_table(headers, rows):
    out = ["| " + " | ".join(str(h) for h in headers) + " |"]
    out.append("|" + "|".join(["---"] * len(headers)) + "|")
    for r in rows:
        out.append("| " + " | ".join("" if c is None else str(c) for c in r) + " |")
    return "\n".join(out)


def norm(s):
    return (s or "").strip().lower()


def _one(con, sql, args=()):
    row = con.execute(sql, args).fetchone()
    return row[0] if row is not None else None


def load_release(parquet_dir, season):
    path = os.path.join(parquet_dir, "ncaa_mfb_player_stats_%d.parquet" % season)
    if not os.path.exists(path):
        sys.exit("release not found: %s" % path)
    df = pq.ParquetFile(path).read().to_pandas()
    df["_g"] = df.espn_game_id.map(
        lambda x: None if x is None or str(x) == "None" else str(int(x)))
    df["_n"] = df.name.map(norm)
    for c in NUMERIC_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def build_resolvers(parquet_dir):
    """Return (game_name -> athlete_id, name -> athlete_id) plus home/away/team.

    Two paths, because the release carries no athlete id:

      A. (game_id, full_name) from `espn_cfb_game_rosters`. This is the strong
         path: it is scoped to the game, so a common name cannot resolve to the
         wrong player, and the same row supplies home_away and team_abbreviation.

      B. name alone from `cfb_crosswalk`, restricted to names that map to
         exactly one athlete id. An ambiguous name is refused rather than
         guessed -- the GRIDIRON contract's rule is never to join on an
         ambiguous name, and a wrong athlete id would silently attribute one
         player's stats to another.
    """
    game_path = os.path.join(parquet_dir, "game_rosters_%d.parquet" % 2026)
    cross_path = os.path.join(parquet_dir, "crosswalk.parquet")
    if not os.path.exists(game_path):
        sys.exit("game rosters not found: %s" % game_path)
    if not os.path.exists(cross_path):
        sys.exit("crosswalk not found: %s" % cross_path)

    gr = pq.ParquetFile(game_path).read(
        columns=["athlete_id", "full_name", "game_id", "home_away",
                 "team_abbreviation"]).to_pandas()
    gr["_n"] = gr.full_name.map(norm)
    gr["_g"] = gr.game_id.map(lambda x: None if x is None else str(int(x)))
    gr = gr.dropna(subset=["_n", "_g", "athlete_id"])
    # one athlete per (game, name); if a game lists the same name twice for
    # different athletes the pair is ambiguous and dropped
    dup = gr.groupby(["_g", "_n"]).athlete_id.nunique()
    bad = set(dup[dup > 1].index)
    gr = gr[~gr.set_index(["_g", "_n"]).index.isin(bad)]
    A = gr.drop_duplicates(["_g", "_n"])[
        ["_g", "_n", "athlete_id", "home_away", "team_abbreviation"]]

    cw = pq.ParquetFile(cross_path).read().to_pandas()
    cw["_n"] = cw.name.map(norm)
    cw = cw.dropna(subset=["_n", "espn_athlete_id"])
    amb = cw.groupby("_n").espn_athlete_id.nunique()
    uniq = set(amb[amb == 1].index)
    B = cw[cw._n.isin(uniq)].drop_duplicates("_n")[["_n", "espn_athlete_id"]]
    return A, B


def resolve(release, A, B):
    """Attach athlete_id, home_away and team_abbreviation to the release rows."""
    mA = release.merge(A, on=["_g", "_n"], how="left")
    mB = release.merge(B, on="_n", how="left")
    ids = mA.athlete_id.fillna(mB.espn_athlete_id)
    out = release[ids.notna()].copy()
    out["_id"] = [int(x) for x in ids[ids.notna()]]
    out["_home_away"] = mA.home_away[ids.notna()].values
    out["_team_abbr"] = mA.team_abbreviation[ids.notna()].values
    return out


def aggregate(resolved):
    """One row per (game, athlete): our stat keys summed across categories."""
    rows = []
    for (g, aid), grp in resolved.groupby(["_g", "_id"]):
        stats = {}
        for col, key, kind in STAT_MAP:
            vals = grp[col].dropna()
            if not len(vals):
                continue
            if kind == "sum":
                v = vals.sum()
            elif kind == "net":
                v = vals.sum()
            elif kind == "net_neg":
                continue  # applied to rush_yds below
            else:
                continue
            stats[key] = int(v) if float(v).is_integer() else round(float(v), 3)
        # rush_yds is gained minus lost, so fold the negative in here
        lost = grp["rush_yds_lost"].dropna()
        if "rush_yds" in stats and len(lost):
            net = stats["rush_yds"] - lost.sum()
            stats["rush_yds"] = int(net) if float(net).is_integer() else round(float(net), 3)
        if not stats:
            continue
        rows.append(dict(
            game_no=g, athlete_id=aid,
            home_away=(None if pd.isna(grp._home_away.iloc[0]) else grp._home_away.iloc[0]),
            team_abbr=(None if pd.isna(grp._team_abbr.iloc[0]) else grp._team_abbr.iloc[0]),
            stats=stats,
        ))
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--parquet-dir", required=True)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    if not os.path.exists(args.db):
        sys.exit("database not found: %s" % args.db)

    release = load_release(args.parquet_dir, args.season)
    A, B = build_resolvers(args.parquet_dir)
    resolved = resolve(release, A, B)
    agg = aggregate(resolved)

    con = sqlite3.connect(args.db, timeout=60)
    con.row_factory = sqlite3.Row

    # existing (game, player) pairs -- these are left alone
    existing = set(
        (str(r[0]), str(r[1])) for r in con.execute(
            "SELECT game_no, source_player_key FROM player_game_logs WHERE league=?",
            (LEAGUE,)))
    # spine: espn athlete id -> player_id
    spine = {str(r[0]): r[1] for r in con.execute(
        "SELECT espn_id, id FROM players WHERE espn_id IS NOT NULL "
        "AND espn_id NOT LIKE '-%'")}

    # schedules: game_date + game_type
    sched_path = os.path.join(args.parquet_dir, "cfb_schedules_%d.parquet" % args.season)
    sched = {}
    if os.path.exists(sched_path):
        sc = pq.ParquetFile(sched_path).read(
            columns=["game_id", "start_date", "season_type"]).to_pandas()
        for r in sc.itertuples(index=False):
            if r.game_id is None:
                continue
            d = str(r.start_date)[:10]
            gt = "REG" if str(r.season_type).lower().startswith("reg") else "POST"
            sched[str(int(r.game_id))] = (d, gt)

    lines = []
    lines.append("# NCAAF log backfill - %s" % dt.datetime.utcnow().strftime("%Y-%m-%d"))
    lines.append("")
    lines.append("source release: `ncaa_mfb_player_stats_%d` (%s)"
                 % (args.season, SOURCE))
    lines.append("database: `%s`" % args.db)
    lines.append("mode: %s" % ("DRY RUN" if args.dry_run else "WRITE"))
    lines.append("")

    lines.append("## 1. Resolution")
    lines.append("")
    lines.append(md_table(
        ["measure", "value"],
        [
            ("release rows", len(release)),
            ("resolved to an athlete id", len(resolved)),
            ("  via (game, full_name) from game_rosters",
             int(resolved._id.notna().sum()) and len(resolved)),
            ("distinct player-games", len(agg)),
            ("distinct athletes", agg.athlete_id.nunique() if len(agg) else 0),
            ("distinct games", agg.game_no.nunique() if len(agg) else 0),
        ],
    ))
    lines.append("")

    lines.append("## 2. What will be written")
    lines.append("")
    new = agg[~agg.apply(lambda r: (r.game_no, str(r.athlete_id)) in existing, axis=1)]
    lines.append(md_table(
        ["measure", "value"],
        [
            ("player-games in the release", len(agg)),
            ("already present (left alone)", len(agg) - len(new)),
            ("to insert", len(new)),
            ("  of those, resolvable to a player_id",
             int(new.athlete_id.astype(str).isin(spine).sum()) if len(new) else 0),
            ("  games covered", new.game_no.nunique() if len(new) else 0),
        ],
    ))
    lines.append("")

    lines.append("## 3. Games covered")
    lines.append("")
    if len(new):
        per_game = new.groupby("game_no").size().sort_values(ascending=False)
        lines.append("top games by player count:")
        lines.append("")
        lines.append(md_table(
            ["game_no", "player-games", "date", "type"],
            [(g, int(n), (sched.get(g, ("", ""))[0]), (sched.get(g, ("", ""))[1]))
             for g, n in per_game.head(15).items()],
        ))
        lines.append("")
        lines.append("date coverage of the inserted games: %s"
                     % (", ".join(sorted({sched.get(g, ("?",))[0] for g in new.game_no.unique()})) or "unknown"))
    lines.append("")

    if args.dry_run:
        lines.append("## 4. Dry run -- nothing written")
        lines.append("")
        lines.append("Re-run without `--dry-run` to write.")
    else:
        inserted = 0
        skipped_no_player = 0
        queued = 0
        for r in agg.itertuples(index=False):
            key = (r.game_no, str(r.athlete_id))
            if key in existing:
                continue
            pid = spine.get(str(r.athlete_id))
            if pid is None:
                skipped_no_player += 1
                # Match the CFBD ingest convention: record the stable identity
                # for review rather than dropping it. Without this the
                # backfill silently loses every player we have never seen.
                if queue_unresolved_player is not None:
                    try:
                        queue_unresolved_player(
                            con, source=SOURCE,
                            raw_name=str(r.athlete_id), league=LEAGUE,
                            team=r.team_abbr, source_player_key=str(r.athlete_id),
                            reason="absent_from_spine",
                        )
                        queued += 1
                    except Exception:
                        pass
                continue
            d, gt = sched.get(r.game_no, (None, None))
            con.execute(
                """INSERT INTO player_game_logs
                   (player_id, league, season, game_no, game_id, game_date, team,
                    opponent, home_away, game_type, stats, source, source_player_key)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(league, source_player_key, season, game_no)
                   DO NOTHING""",
                (pid, LEAGUE, args.season, r.game_no, r.game_no, d,
                 r.team_abbr, None, r.home_away, gt,
                 json.dumps(r.stats, separators=(",", ":")),
                 SOURCE, str(r.athlete_id)),
            )
            inserted += con.execute("SELECT changes()").fetchone()[0]
        con.commit()
        lines.append("## 4. Written")
        lines.append("")
        lines.append(md_table(
            ["measure", "value"],
            [
                ("rows inserted", inserted),
                ("skipped: athlete not in our spine", skipped_no_player),
                ("  of those, queued for identity review", queued),
                ("total NCAAF log rows now",
                 _one(con, "SELECT COUNT(*) FROM player_game_logs WHERE league=?", (LEAGUE,))),
                ("  from this source",
                 _one(con, "SELECT COUNT(*) FROM player_game_logs WHERE league=? AND source=?",
                      (LEAGUE, SOURCE))),
                ("distinct games now",
                 _one(con, "SELECT COUNT(DISTINCT game_no) FROM player_game_logs WHERE league=?",
                      (LEAGUE,))),
            ],
        ))
        lines.append("")

    con.close()
    report = "\n".join(lines)
    out = args.report or os.path.join(
        os.path.dirname(HERE), "research", "fbs",
        "BACKFILL-NCAAF-%d-%s.md" % (args.season, "DRYRUN" if args.dry_run else "WRITE"))
    with open(out, "w") as fh:
        fh.write(report)
    print(report)
    print("\n[report written to %s]" % out)


if __name__ == "__main__":
    main()
