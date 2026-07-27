"""ingest_nfl_depth_charts.py -- current role, from the PUBLISHED depth chart.

Why this exists
---------------
Snap share and target share describe the role a player HAD. A drafter needs the
role he HAS. For a rookie those are not the same question -- there is no prior
role at all, and the board would otherwise have nothing to say about a player
going 17th overall.

Sizing the gap before building anything: of 2,511 ADP rows, 1,392 sit at exactly
170.0 -- that is ESPN's undrafted default, not an ADP. Only 248 players carry a
real ADP, and of those only SEVEN have zero NFL games. All seven are in this
artifact with a depth rank:

    Jeremiyah Love  ARI RB rank 1   (ADP 17.5, 98% owned)
    Carnell Tate    TEN WR rank 1   (ADP 66.9, 94% owned)
    Kenyon Sadiq    NYJ TE rank 1   (ADP 136.5, 68% owned)
    ... plus four more at rank 2

So the "no signal on rookies" gap closes with ADP + percent_owned + depth rank.
It does not need a licensed news feed or college statistics. That was the
kill-check, and it came back negative on building either.

What this is NOT
----------------
Not an injury source. The official NFL injury report is published separately
(nflverse `injuries`, 2009-2025) and is the right source when in-season
week-to-week availability matters. A depth chart moving is evidence about ROLE;
inferring "he must be hurt" from it would be exactly the unfounded claim the
data-UI doctrine bans.

Shape of the artifact
---------------------
A rolling snapshot, not a weekly table: 129 dated snapshots in 2026 so far,
~3,174 rows in the latest. We keep only the newest snapshot per season, because
the board asks "what is his role today", not "how did the chart drift". History
is recoverable from upstream if that changes.

Usage: python3 ingest_nfl_depth_charts.py [--year 2026] [--dry-run]
"""
import argparse
import hashlib
import os
import sqlite3
import sys
import urllib.request

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

SOURCE = "nflverse_depth_charts"
URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
       "depth_charts/depth_charts_{year}.parquet")

_NEEDED = ["dt", "team", "player_name", "espn_id", "gsis_id",
           "pos_grp", "pos_name", "pos_abb", "pos_slot", "pos_rank"]

# Fantasy-relevant offensive positions. The artifact carries the full roster
# including defence and special teams; the draft board only asks about these.
_OFFENSE = {"QB", "RB", "FB", "WR", "TE"}


def ensure_table(con: sqlite3.Connection) -> None:
    """Create nfl_depth_chart (additive, idempotent).

    One row per player per season, holding the LATEST snapshot only.
    """
    con.execute("""
        CREATE TABLE IF NOT EXISTS nfl_depth_chart (
            player_id    INTEGER,           -- FK players.id; NULL if unresolved
            season       INTEGER NOT NULL,
            gsis_id      TEXT NOT NULL,
            team         TEXT,
            player_name  TEXT,
            pos_abb      TEXT,              -- QB / RB / WR / TE
            pos_name     TEXT,              -- 'Running Back', 'Wide Receiver'
            pos_rank     INTEGER,           -- 1 = starter at that spot
            snapshot_at  TEXT,              -- artifact dt this row came from
            source       TEXT,
            ingested_at  TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (season, gsis_id, pos_abb)
        )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_ndc_player "
                "ON nfl_depth_chart(player_id, season)")
    con.commit()


def fetch(year: int, cache_dir: str) -> str:
    """Download the artifact once and report its sha256.

    nflverse republishes this file continuously through the season, so the
    digest is the only thing that makes a run reproducible.
    """
    path = os.path.join(cache_dir, "depth_charts_{}.parquet".format(year))
    if not os.path.exists(path):
        urllib.request.urlretrieve(URL.format(year=year), path)
    with open(path, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    print("  artifact: {} ({} bytes)".format(os.path.basename(path),
                                             os.path.getsize(path)))
    print("  sha256  : {}".format(digest))
    return path


def build_rows(path: str):
    """Latest snapshot only, offensive skill positions only."""
    import pyarrow.parquet as pq

    have = set(pq.ParquetFile(path).schema.names)
    missing = [c for c in _NEEDED if c not in have]
    if missing:
        raise RuntimeError("artifact is missing expected columns: {}".format(missing))

    t = pq.read_table(path, columns=_NEEDED).to_pydict()
    n = len(t["dt"])
    if not n:
        raise RuntimeError("artifact is empty")
    latest = max(d for d in t["dt"] if d)
    print("  {} snapshots; keeping latest {}".format(len(set(t["dt"])), latest))

    out = {}
    for i in range(n):
        if t["dt"][i] != latest:
            continue
        pos = (t["pos_abb"][i] or "").strip().upper()
        gsis = (t["gsis_id"][i] or "").strip()
        if pos not in _OFFENSE or not gsis:
            continue
        rank = t["pos_rank"][i]
        key = (gsis, pos)
        # A player can appear at several slots of the same position group; keep
        # the best (lowest) rank, which is the role he is actually competing for.
        if key in out and out[key]["pos_rank"] is not None and rank is not None:
            if out[key]["pos_rank"] <= rank:
                continue
        out[key] = {
            "gsis_id": gsis,
            "espn_id": str(t["espn_id"][i] or "").strip(),
            "team": t["team"][i],
            "player_name": t["player_name"][i],
            "pos_abb": pos,
            "pos_name": t["pos_name"][i],
            "pos_rank": int(rank) if rank is not None else None,
            "snapshot_at": latest,
        }
    return list(out.values())


def run(year: int, cache_dir: str, dry_run: bool = False) -> int:
    path = fetch(year, cache_dir)
    rows = build_rows(path)
    print("  built {} offensive depth-chart rows".format(len(rows)))

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    ensure_table(con)

    # Two resolution paths, because players.nfl_gsis_id mixes id schemes: 651
    # active players carry an ESPN-style synthetic key ('LOV121782') in a column
    # named for gsis, and every one of them has zero game logs. They are exactly
    # the rookies this ingest exists to cover, so a gsis-only join would miss the
    # whole point -- Jeremiyah Love (ADP 17.5) resolved by neither name nor gsis.
    # espn_id bridges them: 619 of the 651 map to a real gsis in this artifact.
    # See docs/ROADMAP.md B7 for repairing the spine itself.
    gsis_to_player, espn_to_player = {}, {}
    for r in con.execute(
            "SELECT id, nfl_gsis_id, espn_id FROM players WHERE league='nfl'"):
        if r["nfl_gsis_id"]:
            gsis_to_player[str(r["nfl_gsis_id"])] = r["id"]
        if r["espn_id"]:
            espn_to_player[str(r["espn_id"])] = r["id"]

    def resolve(row):
        return (gsis_to_player.get(row["gsis_id"])
                or espn_to_player.get(row["espn_id"]))

    by_gsis = sum(1 for r in rows if gsis_to_player.get(r["gsis_id"]))
    resolved = sum(1 for r in rows if resolve(r))
    print("  {} of {} rows resolve to the player spine "
          "({} by gsis, {} rescued by espn_id)".format(
              resolved, len(rows), by_gsis, resolved - by_gsis))

    if dry_run:
        for r in rows[:5]:
            print("    DRY {} {} {} rank={}".format(
                r["player_name"], r["team"], r["pos_abb"], r["pos_rank"]))
        con.close()
        return 0

    for r in rows:
        con.execute(
            """INSERT INTO nfl_depth_chart
               (player_id, season, gsis_id, team, player_name, pos_abb,
                pos_name, pos_rank, snapshot_at, source)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(season, gsis_id, pos_abb) DO UPDATE SET
                 player_id=COALESCE(excluded.player_id, nfl_depth_chart.player_id),
                 team=excluded.team,
                 player_name=excluded.player_name,
                 pos_name=excluded.pos_name,
                 pos_rank=excluded.pos_rank,
                 snapshot_at=excluded.snapshot_at,
                 ingested_at=datetime('now')""",
            (resolve(r), year, r["gsis_id"], r["team"],
             r["player_name"], r["pos_abb"], r["pos_name"], r["pos_rank"],
             r["snapshot_at"], SOURCE))
    con.commit()

    total = con.execute(
        "SELECT COUNT(*) FROM nfl_depth_chart WHERE season=?", (year,)).fetchone()[0]
    starters = con.execute(
        "SELECT COUNT(*) FROM nfl_depth_chart WHERE season=? AND pos_rank=1",
        (year,)).fetchone()[0]
    print("  wrote {} rows; {} total for {}, {} of them rank-1".format(
        len(rows), total, year, starters))
    con.close()
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cache-dir", default=os.environ.get("LP_CACHE_DIR", "/tmp"))
    args = ap.parse_args()

    print("ingest_nfl_depth_charts: {} -> {}".format(args.year, DB))
    run(args.year, args.cache_dir, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
