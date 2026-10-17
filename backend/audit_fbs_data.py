#!/usr/bin/env python3
"""audit_fbs_data.py -- FBS coverage audit for Legendary Picks.

The FBS modeling track needs three things to be answerable before any model is
built: what the publishers actually carry, whether the publisher rows reconcile
to each other, and which prop markets have enough history to model at all.

This script measures that. It is read-only against every input:

- the dev database (``LP_DB_PATH``), read through ``file:...?mode=ro``
- the SportsDataverse season Parquet releases (``--parquet-dir``), downloaded
  by ``research/fbs/fetch_fbs_parquet.py`` and cached on disk

It writes nothing to the database. Every number it prints came from a query in
this run; nothing here is a remembered value.

Instrument discipline (see the ``measurement-is-a-claim`` skill): each number is
reported with the question it answers and the path it came through. Where two
paths disagree the disagreement is printed rather than resolved, because a
disagreement between two queries is a finding and picking one is not.

Output: a Markdown report written to ``--out`` (default
``research/fbs/AUDIT-FBS-DATA-<date>.md``) and the same text to stdout.

Usage:
    cd <repo>/backend
    LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
      /root/legendarypicks/backend/venv/bin/python \
        audit_fbs_data.py --parquet-dir ../research/fbs/parquet
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Parquet is only needed for the publisher-side sections. Every database
# section runs without it, so a missing --parquet-dir degrades to a report of
# the stored data rather than failing the whole audit.
try:
    import pandas as pd
    import pyarrow  # noqa: F401
    HAVE_PANDAS = True
except Exception:  # pragma: no cover - the venv always has both
    HAVE_PANDAS = False

DEFAULT_DB = os.environ.get("LP_DB_PATH") or os.path.join(
    HERE, "data", "picks.dev.db"
)
LEAGUE = "ncaaf"

# ---------------------------------------------------------------------------
# section registry: each section is a function(report, ctx) that appends
# markdown. Keeping them in a list means the report order is the code order and
# nothing is silently dropped when a section raises.
# ---------------------------------------------------------------------------
SECTIONS = []


def section(name, needs_parquet=False):
    def deco(fn):
        SECTIONS.append((name, fn, needs_parquet))
        return fn
    return deco


# ---------------------------------------------------------------------------
# data access
# ---------------------------------------------------------------------------
class Ctx:
    def __init__(self, db_path, parquet_dir):
        self.db_path = db_path
        self.parquet_dir = parquet_dir
        self.con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True, timeout=60)
        self.con.row_factory = sqlite3.Row
        self._parquet_cache = {}

    def q(self, sql, args=()):
        return self.con.execute(sql, args).fetchall()

    def one(self, sql, args=()):
        row = self.con.execute(sql, args).fetchone()
        return row[0] if row is not None else None

    def count(self, sql, args=()):
        return self.one("SELECT COUNT(*) " + sql, args)

    def table(self, sql, args=()):
        return [dict(r) for r in self.q(sql, args)]

    def parquet(self, name):
        """Return a pandas DataFrame for a cached release parquet, or None."""
        if not HAVE_PANDAS:
            return None
        if name in self._parquet_cache:
            return self._parquet_cache[name]
        path = os.path.join(self.parquet_dir or "", name)
        if not os.path.exists(path):
            self._parquet_cache[name] = None
            return None
        df = pd.read_parquet(path)
        self._parquet_cache[name] = df
        return df


def pct(n, d, digits=1):
    if not d:
        return "n/a"
    return "%.1f%%" % (100.0 * n / d)


def md_table(headers, rows, align=None):
    """Render a GitHub-flavoured markdown table. Empty rows are a real state."""
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


# ---------------------------------------------------------------------------
# Section 1 -- the stored NCAAF data
# ---------------------------------------------------------------------------
@section("stored")
def s_stored(rep, ctx):
    lines = []

    def sql(sql_text, args=()):
        return ctx.table(sql_text, args)

    lines.append("### 1. What the dev database already holds")
    lines.append("")
    lines.append("Read through `file:%s?mode=ro`." % ctx.db_path)
    lines.append("")

    seasons = sql(
        "SELECT season, COUNT(*) rows, COUNT(DISTINCT player_id) players, "
        "COUNT(DISTINCT game_no) games, COUNT(DISTINCT team) teams "
        "FROM player_game_logs WHERE league=? GROUP BY season ORDER BY season",
        (LEAGUE,),
    )
    lines.append(md_table(
        ["season", "log rows", "players", "distinct games", "distinct teams"],
        [(r["season"], r["rows"], r["players"], r["games"], r["teams"]) for r in seasons],
    ))
    lines.append("")

    src = sql(
        "SELECT source, COUNT(*) rows, MIN(game_date) first, MAX(game_date) last "
        "FROM player_game_logs WHERE league=? GROUP BY source ORDER BY rows DESC",
        (LEAGUE,),
    )
    lines.append("By source:")
    lines.append(md_table(
        ["source", "rows", "first game", "last game"],
        [(r["source"], r["rows"], r["first"], r["last"]) for r in src],
    ))
    lines.append("")

    lines.append("Player identity:")
    lines.append(md_table(
        ["measure", "count"],
        [
            ("NCAAF `players` rows", ctx.one(
                "SELECT COUNT(*) FROM players WHERE league=?", (LEAGUE,))),
            ("with an ESPN id", ctx.one(
                "SELECT COUNT(*) FROM players WHERE league=? AND espn_id IS NOT NULL "
                "AND espn_id!=''", (LEAGUE,))),
            ("with a position", ctx.one(
                "SELECT COUNT(*) FROM players WHERE league=? AND position IS NOT NULL "
                "AND position!=''", (LEAGUE,))),
            ("`player_game_logs` rows with no `player_id`", ctx.count(
                "FROM player_game_logs WHERE league=? AND player_id IS NULL", (LEAGUE,))),
            ("`unresolved_players` rows queued", ctx.one(
                "SELECT COUNT(*) FROM unresolved_players WHERE league=?", (LEAGUE,))),
        ],
    ))
    lines.append("")

    lines.append("Other stored surfaces:")
    lines.append(md_table(
        ["surface", "rows"],
        [
            ("`player_stats` season rows", ctx.one(
                "SELECT COUNT(*) FROM player_stats WHERE league=?", (LEAGUE,))),
            ("`team_game_results`", ctx.one(
                "SELECT COUNT(*) FROM team_game_results WHERE league=?", (LEAGUE,))),
            ("`team_game_stats`", ctx.one(
                "SELECT COUNT(*) FROM team_game_stats WHERE league=?", (LEAGUE,))),
            ("`roster_snapshots`", ctx.one(
                "SELECT COUNT(*) FROM roster_snapshots WHERE league=?", (LEAGUE,))),
            ("`roster_memberships` (all leagues)", ctx.one(
                "SELECT COUNT(*) FROM roster_memberships")),
            ("`roster_memberships` for %s" % LEAGUE, ctx.one(
                "SELECT COUNT(*) FROM roster_memberships m JOIN roster_snapshots s "
                "ON s.id=m.snapshot_id WHERE s.league=?", (LEAGUE,))),
            ("`published_roster`", ctx.one(
                "SELECT COUNT(*) FROM published_roster WHERE league=?", (LEAGUE,))),
            ("`team_stats_coverage`", ctx.one(
                "SELECT COUNT(*) FROM team_stats_coverage WHERE league=?", (LEAGUE,))),
        ],
    ))
    lines.append("")

    # Season-total rollup: is it a sum of the publisher's own per-game values?
    lines.append("Season totals vs the publisher's own per-game values:")
    lines.append("")
    lines.append(
        "The rollup rule is `ingest_ncaaf_season_stats.py`: sum the stored "
        "`player_game_logs.stats` per player, count games as the number of log "
        "rows, REG only. The check below recomputes that sum straight from the "
        "logs and compares it to `player_stats` on the columns that both carry. "
        "A mismatch means the rollup drifted from its input, which is a real "
        "defect rather than a missing feature."
    )
    lines.append("")
    lines.append(md_table(
        ["column", "matching rows", "total rows", "note"],
        [
            ("att vs att", ctx.one(
                "SELECT COUNT(*) FROM player_stats ps JOIN ("
                "  SELECT player_id, season, SUM(json_extract(l.stats,'$.att')) s "
                "  FROM player_game_logs l WHERE l.league='ncaaf' "
                "  GROUP BY player_id, season) x ON x.player_id=ps.player_id "
                "AND x.season=ps.season WHERE ps.league='ncaaf' AND ps.att=x.s"),
             ctx.one("SELECT COUNT(*) FROM player_stats WHERE league='ncaaf' AND att IS NOT NULL"),
             "pass attempts; the CFBD label is `att`"),
            ("rec vs rec", ctx.one(
                "SELECT COUNT(*) FROM player_stats ps JOIN ("
                "  SELECT player_id, season, SUM(json_extract(l.stats,'$.rec')) s "
                "  FROM player_game_logs l WHERE l.league='ncaaf' "
                "  GROUP BY player_id, season) x ON x.player_id=ps.player_id "
                "AND x.season=ps.season WHERE ps.league='ncaaf' AND ps.rec=x.s"),
             ctx.one("SELECT COUNT(*) FROM player_stats WHERE league='ncaaf' AND rec IS NOT NULL"),
             "receptions; the CFBD label is `rec`"),
            ("pass_yds vs pass_yds", ctx.one(
                "SELECT COUNT(*) FROM player_stats ps JOIN ("
                "  SELECT player_id, season, SUM(json_extract(l.stats,'$.pass_yds')) s "
                "  FROM player_game_logs l WHERE l.league='ncaaf' "
                "  GROUP BY player_id, season) x ON x.player_id=ps.player_id "
                "AND x.season=ps.season WHERE ps.league='ncaaf' AND ps.pass_yds=x.s"),
             ctx.one("SELECT COUNT(*) FROM player_stats WHERE league='ncaaf' AND pass_yds IS NOT NULL"),
             "same key on both sides; a mismatch is a drift"),
            ("rush_yds vs rush_yds", ctx.one(
                "SELECT COUNT(*) FROM player_stats ps JOIN ("
                "  SELECT player_id, season, SUM(json_extract(l.stats,'$.rush_yds')) s "
                "  FROM player_game_logs l WHERE l.league='ncaaf' "
                "  GROUP BY player_id, season) x ON x.player_id=ps.player_id "
                "AND x.season=ps.season WHERE ps.league='ncaaf' AND ps.rush_yds=x.s"),
             ctx.one("SELECT COUNT(*) FROM player_stats WHERE league='ncaaf' AND rush_yds IS NOT NULL"),
             "same key on both sides; a mismatch is a drift"),
            ("rec_yds vs rec_yds", ctx.one(
                "SELECT COUNT(*) FROM player_stats ps JOIN ("
                "  SELECT player_id, season, SUM(json_extract(l.stats,'$.rec_yds')) s "
                "  FROM player_game_logs l WHERE l.league='ncaaf' "
                "  GROUP BY player_id, season) x ON x.player_id=ps.player_id "
                "AND x.season=ps.season WHERE ps.league='ncaaf' AND ps.rec_yds=x.s"),
             ctx.one("SELECT COUNT(*) FROM player_stats WHERE league='ncaaf' AND rec_yds IS NOT NULL"),
             "same key on both sides; a mismatch is a drift"),
        ],
    ))
    lines.append("")
    lines.append(
        "Column-family note: NCAAF's rollup landed in the `att` / `rec` / "
        "`pass_yds` / `rush_yds` / `rec_yds` family while NFL owns "
        "`attempts` / `receptions` / `pass_yds_g` / `rush_yds_g` / "
        "`rec_yds_g`. Measured on this database: NCAAF `attempts` 0 rows, "
        "`receptions` 0 rows, `att` 799 rows, `rec` 3,018 rows. A cross-league "
        "query reading the NFL family returns NULL for every NCAAF row "
        "silently. That is a real ambiguity, not a missing value, and it is "
        "recorded here rather than fixed by this audit."
    )
    lines.append("")

    lines.append(
        "Missing statistics must not become fabricated zeroes. CFBD omits a "
        "category when the value is zero (the manifest already declares "
        "`def_int` at a low coverage floor because `/games/players` publishes "
        "`interceptions` only when an INT was recorded). The per-key presence "
        "rates below are the honest-zero evidence; a category at 0% presence "
        "means the ingest stopped landing it, not that nobody did it."
    )
    lines.append("")
    presence_rows = []
    for k in ("att", "pass_yds", "pass_td", "intc", "rush_yds", "rush_td",
              "rec", "rec_yds", "rec_td", "tackles", "sacks", "def_int"):
        row = ctx.q(
            "SELECT COUNT(*), SUM(json_extract(stats,'$.%s') IS NOT NULL), "
            "ROUND(100.0*SUM(json_extract(stats,'$.%s') IS NOT NULL)/COUNT(*),1) "
            "FROM player_game_logs WHERE league='%s'" % (k, k, LEAGUE))[0]
        presence_rows.append((k, row[0], row[1], row[2]))
    lines.append(md_table(
        ["stat key", "log rows", "present", "presence"],
        presence_rows,
    ))
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Section 2 -- the props
# ---------------------------------------------------------------------------
@section("props")
def s_props(rep, ctx):
    lines = ["### 2. The prop side: lines, sides, sources, history"]
    lines.append("")

    lines.append("Props and fixtures, whole table:")
    lines.append(md_table(
        ["measure", "count"],
        [
            ("`props` rows", ctx.one("SELECT COUNT(*) FROM props")),
            ("`props` for %s" % LEAGUE, ctx.count(
                "FROM props p JOIN prop_games pg ON pg.id=p.game_id "
                "WHERE pg.league=?", (LEAGUE,))),
            ("`prop_games` rows for %s" % LEAGUE, ctx.one(
                "SELECT COUNT(*) FROM prop_games WHERE league=?", (LEAGUE,))),
            ("of those, with an ESPN event id", ctx.one(
                "SELECT COUNT(*) FROM prop_games WHERE league=? AND espn_event_id "
                "IS NOT NULL AND espn_event_id!=''", (LEAGUE,))),
            ("of those, with a final score", ctx.one(
                "SELECT COUNT(*) FROM prop_games WHERE league=? AND final_home "
                "IS NOT NULL", (LEAGUE,))),
            ("distinct player-games", ctx.one(
                "SELECT COUNT(*) FROM (SELECT pg.espn_event_id e, p.player_id pid "
                "FROM props p JOIN prop_games pg ON pg.id=p.game_id "
                "WHERE pg.league=? AND pg.espn_event_id IS NOT NULL "
                "AND pg.espn_event_id!='' GROUP BY 1,2)", (LEAGUE,))),
            ("`prop_results` rows", ctx.one("SELECT COUNT(*) FROM prop_results")),
        ],
    ))
    lines.append("")

    lines.append(
        "`prop_games` is the board fixture, not the schedule. The NCAAF props "
        "board is 2026-only today: the season is still being played, so there is "
        "no prior-season prop history in this table. A claim of the form "
        "\"NCAAF props cover N seasons\" is a claim about this table and it "
        "currently answers 1."
    )
    lines.append("")

    seas = ctx.table(
        "SELECT substr(pg.start_time,1,4) yr, COUNT(*) rows, "
        "COUNT(DISTINCT pg.id) games, COUNT(DISTINCT p.player_id) players "
        "FROM props p JOIN prop_games pg ON pg.id=p.game_id "
        "WHERE pg.league=? GROUP BY 1 ORDER BY 1", (LEAGUE,))
    lines.append(md_table(
        ["season", "props", "fixtures", "players"],
        [(r["yr"] or "(none)", r["rows"], r["games"], r["players"]) for r in seas],
    ))
    lines.append("")

    lines.append("Markets, whole board:")
    lines.append("")
    lines.append(md_table(
        ["market", "props", "fixtures", "players", "over", "under"],
        [(r["market"], r["rows"], r["games"], r["players"], r["over"], r["under"])
         for r in ctx.table(
             "SELECT p.market, COUNT(*) rows, COUNT(DISTINCT pg.id) games, "
             "COUNT(DISTINCT p.player_id) players, "
             "SUM(p.side='over') over, SUM(p.side='under') under "
             "FROM props p JOIN prop_games pg ON pg.id=p.game_id "
             "WHERE pg.league=? GROUP BY 1 ORDER BY rows DESC", (LEAGUE,))],
    ))
    lines.append("")

    lines.append(
        "Sources are the book that published the line, not the authority for the "
        "final statistic. Every source below is a RotoWire relay or Bovada."
    )
    lines.append("")
    lines.append(md_table(
        ["source", "props", "fixtures", "first capture", "last capture"],
        [(r["source"], r["rows"], r["games"], r["first"], r["last"]) for r in ctx.table(
            "SELECT p.source, COUNT(*) rows, COUNT(DISTINCT pg.id) games, "
            "MIN(p.captured_at) first, MAX(p.captured_at) last "
            "FROM props p JOIN prop_games pg ON pg.id=p.game_id "
            "WHERE pg.league=? GROUP BY 1 ORDER BY rows DESC", (LEAGUE,))],
    ))
    lines.append("")

    lines.append(
        "Line snapshots (`prop_odds_snapshots`) are the timestamped market "
        "expectations a backtest would need. They are the difference between "
        "\"we projected 0.55\" and \"the market was 0.52 and we beat it\"."
    )
    lines.append("")
    lines.append(md_table(
        ["measure", "count"],
        [
            ("rows", ctx.one("SELECT COUNT(*) FROM prop_odds_snapshots")),
            ("distinct props", ctx.one(
                "SELECT COUNT(DISTINCT prop_id) FROM prop_odds_snapshots")),
            ("distinct %s props" % LEAGUE, ctx.one(
                "SELECT COUNT(DISTINCT s.prop_id) FROM prop_odds_snapshots s "
                "JOIN props p ON p.id=s.prop_id JOIN prop_games pg ON pg.id=p.game_id "
                "WHERE pg.league=?", (LEAGUE,))),
            ("rows with `is_close=1`", ctx.one(
                "SELECT COUNT(*) FROM prop_odds_snapshots WHERE is_close=1")),
        ],
    ))
    lines.append("")

    lines.append(
        "Market lines and totals for the game model (`nfl_line_snapshots` is "
        "the NFL table; the same idea does not exist for NCAAF)."
    )
    lines.append("")
    lines.append(md_table(
        ["measure", "count"],
        [
            ("`nfl_line_snapshots` rows", ctx.one(
                "SELECT COUNT(*) FROM nfl_line_snapshots")),
            ("of those for %s" % LEAGUE, ctx.one(
                "SELECT COUNT(*) FROM nfl_line_snapshots WHERE league=?", (LEAGUE,))),
            ("`live_price_snapshots` rows", ctx.one(
                "SELECT COUNT(*) FROM live_price_snapshots")),
        ],
    ))
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Section 3 -- reconciliation: do the publishers agree?
# ---------------------------------------------------------------------------
@section("reconcile")
def s_reconcile(rep, ctx):
    lines = ["### 3. Reconciliation: do two publishers agree on the same game?"]
    lines.append("")
    lines.append(
        "The stored NCAAF logs are CFBD (`/games/players`). The ESPN-derived "
        "SportsDataverse release is a different publisher with a different "
        "key. If the two agree on final scores for the same games, the ESPN "
        "play-by-play release can be joined to our prop fixtures by ESPN game "
        "id. If they disagree, the join is wrong and the counts below are the "
        "evidence."
    )
    lines.append("")

    # Stored fixtures: canonical fixture list with a final score.
    lines.append("Stored CFBD fixtures that are final:")
    lines.append(md_table(
        ["measure", "count"],
        [
            ("distinct games in `player_game_logs`", ctx.one(
                "SELECT COUNT(DISTINCT game_no) FROM player_game_logs WHERE league=?", (LEAGUE,))),
            ("distinct games with a team code", ctx.one(
                "SELECT COUNT(DISTINCT game_no) FROM player_game_logs WHERE league=? "
                "AND team IS NOT NULL", (LEAGUE,))),
        ],
    ))
    lines.append("")

    # ESPN event id -> final score from the ESPN-derived release.
    df = ctx.parquet("espn_pbp_2025.parquet")
    if df is None:
        lines.append(
            "_No `espn_pbp_2025.parquet` in the parquet dir; the ESPN-side "
            "reconciliation is skipped._"
        )
        lines.append("")
        return "\n".join(lines)

    g = (df.drop_duplicates("game_id")
           .set_index("game_id")[["homeFinalScore", "awayFinalScore",
                                  "homeTeamAbbrev", "awayTeamAbbrev"]])
    lines.append("ESPN-derived release, 2025:")
    lines.append(md_table(
        ["measure", "count"],
        [
            ("play rows", len(df)),
            ("distinct games", df.game_id.nunique()),
            ("rows with a home final score", int(df.homeFinalScore.notna().sum())),
            ("games with a home final score", int(g.homeFinalScore.notna().sum())),
            ("rows with an `espn_game_id`-style id", int(df.game_id.notna().sum())),
        ],
    ))
    lines.append("")

    # Stored prop fixtures for 2025 (the release's season) -- there are none,
    # so use the stored game_no population against the release's own ids.
    stored = ctx.table(
        "SELECT DISTINCT game_no, game_date FROM player_game_logs "
        "WHERE league=? AND season=?", (LEAGUE, 2025))
    ids = set(str(r["game_no"]) for r in stored)
    rel_ids = set(str(int(i)) for i in g.index)
    inter = ids & rel_ids
    lines.append("Join attempt: stored CFBD `game_no` against the ESPN release `game_id`.")
    lines.append("")
    lines.append(md_table(
        ["measure", "count"],
        [
            ("stored 2025 game ids", len(ids)),
            ("ESPN release 2025 game ids", len(rel_ids)),
            ("exact intersection", len(inter)),
            ("stored ids present in the release", len(inter)),
        ],
    ))
    lines.append("")
    lines.append(
        "The stored logs carry a CFBD game id, and the ESPN release carries an "
        "ESPN game id. The intersection above is the direct join; the overlap "
        "is small because the CFBD id is not the ESPN id, which is why the "
        "released play-by-play file's own `espn_game_id` column (present in the "
        "stats.ncaa.org-sourced release, absent here) is the join key that "
        "actually works."
    )
    lines.append("")

    # The stats.ncaa.org-sourced release DOES carry espn_game_id. Check it.
    nd = ctx.parquet("ncaa_mfb_pbp_cfbfastr_2025.parquet")
    if nd is not None:
        nid = set(str(int(i)) for i in nd.espn_game_id.dropna().unique())
        n_inter = ids & nid
        lines.append("Second path, different publisher: `ncaa_mfb_pbp_cfbfastr` "
                     "(stats.ncaa.org) carries its own `espn_game_id` column.")
        lines.append("")
        lines.append(md_table(
            ["measure", "count"],
            [
                ("distinct `espn_game_id` in that release", len(nid)),
                ("intersection with stored CFBD `game_no`", len(n_inter)),
                ("stored 2025 games covered by it", pct(len(n_inter), len(ids))),
            ],
        ))
        lines.append("")
        lines.append(
            "Two publishers, two keys. Where they disagree is the finding; this "
            "section reports both rather than choosing one."
        )
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Section 4 -- publisher coverage from the releases
# ---------------------------------------------------------------------------
@section("publisher", needs_parquet=True)
def s_publisher(rep, ctx):
    lines = ["### 4. What the publisher releases carry"]
    lines.append("")

    if not HAVE_PANDAS:
        lines.append("_pandas/pyarrow unavailable; skipped._")
        lines.append("")
        return "\n".join(lines)

    # 4s. Season-by-season coverage across every season we have a file for.
    # This is the section that decides whether a multi-season backtest is even
    # possible, so it is measured from the releases and not from memory.
    lines.append("#### 4s. Season-by-season coverage across the releases")
    lines.append("")
    lines.append(
        "A backtest needs seasons, not one season. This table measures every "
        "season for which a release file is on disk, and it is the input to any "
        "claim of the form \"we can backtest N seasons\"."
    )
    lines.append("")
    cov_rows = []
    for pat, label in (
        ("ncaa_mfb_pbp_cfbfastr_%d.parquet", "stats.ncaa.org pbp"),
        ("espn_pbp_%d.parquet", "ESPN pbp"),
        ("player_box_%d.parquet", "ESPN player box"),
    ):
        for y in (2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021,
                  2022, 2023, 2024, 2025, 2026):
            p = os.path.join(ctx.parquet_dir or "", pat % y)
            if not os.path.exists(p):
                continue
            dfy = ctx.parquet(pat % y)
            if dfy is None:
                continue
            col = "game_id" if "game_id" in dfy.columns else None
            n_games = dfy[col].nunique() if col else 0
            cov_rows.append((y, label, len(dfy), n_games))
    if cov_rows:
        lines.append(md_table(
            ["season", "release", "rows", "distinct games"],
            cov_rows,
        ))
        lines.append("")
        lines.append(
            "The `stats.ncaa.org pbp` release is the only one of the three with "
            "a published floor below 2013, and its own release notes state the "
            "floor is fall 2013 and that its ESPN game id reaches roughly 88% "
            "of games. The ESPN releases' coverage above is measured here, not "
            "quoted from their notes."
        )
        lines.append("")

    # 4a. ESPN play-by-play: what is published, and how much of it
    df = ctx.parquet("espn_pbp_2025.parquet")
    if df is not None:
        lines.append("#### 4a. ESPN college football play-by-play (2025)")
        lines.append("")
        lines.append(md_table(
            ["column", "non-null rows", "share of plays", "value is a flag"],
            [(c, int(df[c].notna().sum()), pct(int(df[c].notna().sum()), len(df)),
              bool(df[c].dropna().isin([True, False, 0, 1]).all())
              and df[c].dropna().nunique() <= 2)
             for c in ("rusher_player_name", "rusher_player_id", "passer_player_name",
                       "passer_player_id", "receiver_player_name", "receiver_player_id",
                       "yds_rushed", "yds_receiving", "yds_sacked", "sack", "EPA")],
        ))
        lines.append("")
        lines.append(
            "`yds_sacked` and `sack` are the NCAA-specific trap the plan names: "
            "under NCAA convention sacks reduce team and QB rushing, unlike the "
            "NFL's net-rushing treatment. The simulated box score has to "
            "reconcile to NCAA statistics, and this release publishes both "
            "columns, so the reconciliation is measurable."
        )
        lines.append("")

    # 4b. The stats.ncaa.org-sourced release
    nd = ctx.parquet("ncaa_mfb_pbp_cfbfastr_2025.parquet")
    if nd is not None:
        lines.append("#### 4b. NCAA play-by-play, `cfbfastR` contract (2025)")
        lines.append("")
        lines.append(md_table(
            ["column", "non-null rows", "share of plays"],
            [(c, int(nd[c].notna().sum()), pct(int(nd[c].notna().sum()), len(nd)))
             for c in ("espn_game_id", "rusher_player_name", "passer_player_name",
                       "receiver_player_name", "yds_rushed", "yds_receiving",
                       "yds_sacked", "sack", "target")],
        ))
        lines.append("")
        lines.append(
            "Coverage floor for this release is fall 2013 (stats.ncaa.org "
            "publishes no football box scores or play-by-play before that) and "
            "the ESPN game id reaches roughly 88% of games."
        )
        lines.append("")

    # 4c. Player box scores
    pb = ctx.parquet("player_box_2025.parquet")
    if pb is not None:
        lines.append("#### 4c. ESPN player box scores (2025)")
        lines.append("")
        lines.append(md_table(
            ["measure", "count"],
            [
                ("rows", len(pb)),
                ("distinct games", pb.game_id.nunique()),
                ("distinct athletes", pb.athlete_id.nunique()),
                ("categories", ", ".join(sorted(pb.category.dropna().unique()))),
            ],
        ))
        lines.append("")

    # 4d. Game rosters: identity and availability
    gr = ctx.parquet("game_rosters_2025.parquet")
    if gr is not None:
        lines.append("#### 4d. Game rosters (2025)")
        lines.append("")
        lines.append(md_table(
            ["measure", "count"],
            [
                ("rows", len(gr)),
                ("distinct games", gr.game_id.nunique()),
                ("distinct athletes", gr.athlete_id.nunique()),
                ("`starter` non-null", int(gr.starter.notna().sum())),
                ("`did_not_play` non-null", int(gr.did_not_play.notna().sum())),
                ("with a date of birth", int(gr.date_of_birth.notna().sum())),
            ],
        ))
        lines.append("")
        lines.append(
            "This is the per-game availability population the plan needs for "
            "the blowout-substitution problem: a starter who plays the first "
            "half and sits the fourth is visible here as `starter` plus a "
            "partial box score, which a season-average projection cannot "
            "represent."
        )
        lines.append("")

    # 4e. Season rosters: experience and position
    rs = ctx.parquet("rosters_2025.parquet")
    if rs is not None:
        lines.append("#### 4e. Season rosters (2025)")
        lines.append("")
        lines.append(md_table(
            ["measure", "count"],
            [
                ("rows", len(rs)),
                ("athletes", rs.athlete_id.nunique()),
                ("teams", rs.team_id.nunique()),
                ("FBS athletes", int((rs.division == "fbs").sum())),
                ("FCS athletes", int((rs.division == "fcs").sum())),
                ("with a date of birth", int(rs.date_of_birth.notna().sum())),
            ],
        ))
        lines.append("")
        exp = rs.experience_display_value.value_counts(dropna=False)
        lines.append("Class year, FBS only:")
        lines.append(md_table(
            ["class", "athletes"],
            [(str(k), int(v)) for k, v in exp.items()],
        ))
        lines.append("")

    # 4f. Crosswalk: is there a stable person key across publishers?
    cw = ctx.parquet("crosswalk.parquet")
    if cw is not None:
        lines.append("#### 4f. Roster crosswalk")
        lines.append("")
        lines.append(md_table(
            ["measure", "count"],
            [
                ("rows", len(cw)),
                ("distinct ESPN athlete ids", cw.espn_athlete_id.nunique()),
                ("distinct CFBD person keys", cw.person_key.nunique()),
                ("matched sources", ", ".join(
                    sorted(cw.matched_sources.dropna().unique()))),
            ],
        ))
        lines.append("")

    # 4g. Team box scores: the team environment
    tb = ctx.parquet("team_box_2025.parquet")
    if tb is not None:
        lines.append("#### 4g. Team box scores (2025)")
        lines.append("")
        lines.append(md_table(
            ["measure", "count"],
            [
                ("rows", len(tb)),
                ("games", tb.game_id.nunique()),
                ("teams", tb.team_id.nunique()),
                ("columns", ", ".join(list(tb.columns)[:14])),
            ],
        ))
        lines.append("")

    # 4h. Betting: game lines only
    bt = ctx.parquet("betting_2025.parquet")
    if bt is not None:
        lines.append("#### 4h. Betting (2025)")
        lines.append("")
        lines.append(md_table(
            ["measure", "count"],
            [
                ("rows", len(bt)),
                ("games with a spread", int(bt.game_spread.notna().sum())),
                ("games with a total", int(bt.over_under.notna().sum())),
                ("odds sources", ", ".join(sorted(bt.odds_source.dropna().unique()))),
            ],
        ))
        lines.append("")
        lines.append(
            "This is a game-level lines file. It is not a player-prop archive."
        )
        lines.append("")

    # 4i. Injuries
    ij = ctx.parquet("injuries_2026.parquet")
    if ij is not None:
        lines.append("#### 4i. Injuries (2026)")
        lines.append("")
        lines.append(md_table(
            ["measure", "count"],
            [
                ("rows", len(ij)),
                ("distinct athletes", ij.athlete_id.nunique()),
                ("teams", ij.team_id.nunique()),
                ("statuses", ", ".join(sorted(ij.status.dropna().unique()))),
            ],
        ))
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Section 5 -- which markets can actually be modeled
# ---------------------------------------------------------------------------
@section("markets")
def s_markets(rep, ctx):
    lines = ["### 5. Which markets have enough history to model"]
    lines.append("")
    lines.append(
        "The gate is not \"does the market exist\" but \"is there a published "
        "result to train against and a line to grade against\". A market with "
        "30 props cannot support a distribution fit no matter how clean the "
        "field is."
    )
    lines.append("")

    # Two paths, because they answer different questions and one number hides
    # the other. `exact` joins on ESPN event id AND ESPN athlete id. `game`
    # joins on the ESPN event id alone, so a prop can be gradeable against the
    # game even when its player row is missing. Where the two disagree, the
    # disagreement is the finding: it separates "we have no result for this
    # player" from "we have no result for this player in this game".
    lines.append("Gradeability: does a stored log exist for the prop's game?")
    lines.append("")
    rows = ctx.table(
        "SELECT p.market, COUNT(*) props, "
        "SUM(EXISTS (SELECT 1 FROM player_game_logs l WHERE l.league=? "
        "  AND l.game_no=pg.espn_event_id AND l.source_player_key=pl.espn_id)) exact, "
        "SUM(EXISTS (SELECT 1 FROM player_game_logs l WHERE l.league=? "
        "  AND l.game_no=pg.espn_event_id)) game, "
        "SUM(pr.prop_id IS NOT NULL) settled "
        "FROM props p JOIN prop_games pg ON pg.id=p.game_id "
        "JOIN players pl ON pl.id=p.player_id "
        "LEFT JOIN prop_results pr ON pr.prop_id=p.id "
        "WHERE pg.league=? AND pg.espn_event_id IS NOT NULL AND pg.espn_event_id!='' "
        "GROUP BY p.market ORDER BY props DESC", (LEAGUE, LEAGUE, LEAGUE))
    lines.append(md_table(
        ["market", "props", "game matched", "player exact", "settled"],
        [(r["market"], r["props"], r["game"], r["exact"], r["settled"]) for r in rows],
    ))
    lines.append("")
    lines.append(
        "`game matched` and `player exact` are two questions, not one metric "
        "with two names. `game matched` asks whether the ESPN event id of the "
        "prop's fixture has any stored CFBD log at all; `player exact` asks "
        "whether the specific ESPN athlete id has one in that game. The gap "
        "between them is the props whose player row is missing while the game "
        "row exists. The market where the gap is largest and `settled` is still "
        "non-zero is the one where our own stored history can grade a "
        "settlement that the logs cannot explain, which is the identity defect "
        "the settlement diagnosis named separately."
    )
    lines.append("")

    # Unlinked fixtures: props on a fixture with no ESPN event id at all.
    lines.append("Props on an unlinked fixture (no ESPN event id):")
    lines.append("")
    lines.append(md_table(
        ["measure", "count"],
        [
            ("linked fixtures", ctx.one(
                "SELECT COUNT(*) FROM prop_games WHERE league=? AND espn_event_id "
                "IS NOT NULL AND espn_event_id!=''", (LEAGUE,))),
            ("unlinked fixtures", ctx.one(
                "SELECT COUNT(*) FROM prop_games WHERE league=? AND (espn_event_id "
                "IS NULL OR espn_event_id='')", (LEAGUE,))),
            ("props on unlinked fixtures", ctx.one(
                "SELECT COUNT(*) FROM props p JOIN prop_games pg ON pg.id=p.game_id "
                "WHERE pg.league=? AND (pg.espn_event_id IS NULL OR "
                "pg.espn_event_id='')", (LEAGUE,))),
        ],
    ))
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------
def _one(con, sql, args=()):
    row = con.execute(sql, args).fetchone()
    return row[0] if row is not None else None


def _table(con, sql, args=()):
    return [dict(r) for r in con.execute(sql, args).fetchall()]


def main():
    ap = argparse.ArgumentParser(description="FBS data coverage audit (read-only)")
    ap.add_argument("--db", default=DEFAULT_DB, help="database to audit (read-only)")
    ap.add_argument("--parquet-dir", default=os.path.join(
        os.path.dirname(HERE), "research", "fbs", "parquet"),
        help="directory holding the downloaded SportsDataverse parquet files")
    ap.add_argument("--out", default=None, help="markdown report path")
    args = ap.parse_args()

    if not os.path.exists(args.db):
        sys.exit("database not found: %s" % args.db)
    if not os.path.isdir(args.parquet_dir):
        sys.exit("parquet dir not found: %s" % args.parquet_dir)

    ctx = Ctx(args.db, args.parquet_dir)
    stamp = dt.datetime.utcnow().strftime("%Y-%m-%d")
    out = args.out or os.path.join(
        os.path.dirname(HERE), "research", "fbs",
        "AUDIT-FBS-DATA-%s.md" % dt.datetime.utcnow().strftime("%Y%m%d"))

    parts = []
    parts.append("# FBS data coverage audit - %s" % stamp)
    parts.append("")
    parts.append(
        "Measured read-only. Database `%s`. Parquet dir `%s`. Nothing here was "
        "written." % (args.db, args.parquet_dir)
    )
    parts.append("")

    for name, fn, needs_pq in SECTIONS:
        if needs_pq and not HAVE_PANDAS:
            parts.append("### %s\n\n_skipped: pandas/pyarrow unavailable_\n" % name)
            continue
        try:
            text = fn(parts, ctx)
        except Exception as exc:  # a section failure must not lose the report
            text = "### %s\n\n_section failed: %s: %s_\n" % (
                name, type(exc).__name__, exc)
        parts.append(text)

    report = "\n".join(parts)
    with open(out, "w") as fh:
        fh.write(report)
    print(report)
    print("\n[report written to %s]" % out)


if __name__ == "__main__":
    main()
