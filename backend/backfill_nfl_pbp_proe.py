#!/usr/bin/env python3
"""backfill_nfl_pbp_proe.py -- fill xpass and pass_oe on stored nfl_pbp plays from nflverse's published files.

xpass is nflverse's expected pass probability for the play and pass_oe the pass over expected, both floats (the
existing backfill in ingest_nfl_pbp_logs.py handles 0 and 1 flags only). Needed for the pass rate over expected
(PROE) feature in docs/INDEX-nfl-model-research-2026-10-12.md section 3.

Rules, the same as the earlier backfills:
- Update-only: stored rows are matched on (game_id, play_id); no other column is written and no row is inserted or
  deleted.
- Refuses, writing nothing, unless every stored play of the season is in the file, every REG file play of a stored
  game is stored, play keys do not repeat, and the file holds only the season asked for.
- Alignment: xpass is checked to sit on the right kinds of play. Measured on 2024: 99.4% of run and pass plays carry
  it and no kickoff, punt, field goal or extra point does. A season below 0.98 on run and pass plays, or with any
  value on a kind of play that never has one, is refused.
- Counts stored after the update must equal the counts in the file, or the transaction rolls back.
- Dry run unless --apply. Files are downloaded to --dir (a directory of its own) from nflverse's release and their
  sha256 is printed.

  LP_DB_PATH=<dev db> venv/bin/python backfill_nfl_pbp_proe.py --dir /abs/new/dir --seasons 2010-2025 [--apply]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import urllib.request

import ingest_nfl_pbp_logs as ing

URL = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{}.parquet"
COLS = ["xpass", "pass_oe"]
KINDS_WITH = ("run", "pass", "no_play")
MIN_ALIGNED = 0.98


def download(season, directory):
    path = os.path.join(directory, "play_by_play_%d.parquet" % season)
    if not os.path.exists(path):
        req = urllib.request.Request(URL.format(season), headers={"User-Agent": "legendarypicks-backfill"})
        with urllib.request.urlopen(req, timeout=300) as resp, open(path + ".part", "wb") as out:
            out.write(resp.read())
        os.replace(path + ".part", path)
    return path


def read_file(path, season):
    import pyarrow.parquet as pq
    pf = pq.ParquetFile(path)
    need = ["game_id", "play_id", "season", "season_type", "play_type"] + COLS
    missing = [c for c in need if c not in pf.schema_arrow.names]
    if missing:
        raise RuntimeError("%s: file lacks columns %s" % (path, missing))
    data = pf.read(columns=need).to_pydict()
    seasons = {int(s) for s in data["season"] if s is not None}
    if seasons != {season}:
        raise RuntimeError("%s: file holds seasons %s, expected only %s" % (path, sorted(seasons), season))
    plays = {}
    for i, st in enumerate(data["season_type"]):
        if st != "REG":
            continue
        key = (data["game_id"][i], data["play_id"][i])
        if None in key:
            raise RuntimeError("%s: REG play without a key: %s" % (path, key))
        if key in plays:
            raise RuntimeError("%s: play key %s appears twice" % (path, key))
        vals = tuple(None if data[c][i] is None else float(data[c][i]) for c in COLS)
        for v in vals:
            if v is not None and not (v == v):          # NaN is not a value
                vals = tuple(None if x != x else x for x in vals)
                break
        plays[key] = (vals, data["play_type"][i])
    return plays


def backfill(con, path, season, apply):
    plays = read_file(path, season)
    with open(path, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    stored = {(g, p): kind for g, p, kind in con.execute(
        "SELECT game_id, play_id, play_type FROM nfl_pbp WHERE season = ?", (season,))}
    matched = sorted(set(stored) & set(plays))
    stored_only = set(stored) - set(plays)
    file_only = set(plays) - set(stored)
    stored_games = {g for g, _ in stored}
    file_only_stored_games = [k for k in file_only if k[0] in stored_games]
    run_pass = [k for k in matched if plays[k][1] in ("run", "pass")]
    with_x = sum(plays[k][0][0] is not None for k in run_pass)
    wrong_kind = [k for k in matched if plays[k][0][0] is not None and plays[k][1] not in KINDS_WITH]
    report = {"season": season, "sha256": sha, "stored": len(stored), "matched": len(matched),
              "stored_only": len(stored_only), "file_only": len(file_only),
              "xpass_non_null": sum(plays[k][0][0] is not None for k in matched),
              "pass_oe_non_null": sum(plays[k][0][1] is not None for k in matched),
              "run_pass_aligned": (with_x / len(run_pass)) if run_pass else None,
              "value_on_wrong_kind": len(wrong_kind)}
    problems = []
    if not stored:
        problems.append("no stored plays for season %d" % season)
    if stored_only:
        problems.append("%d stored plays are not in the file, e.g. %s" % (len(stored_only), sorted(stored_only)[:3]))
    if file_only_stored_games:
        problems.append("%d file plays are missing from stored games" % len(file_only_stored_games))
    if report["run_pass_aligned"] is not None and report["run_pass_aligned"] < MIN_ALIGNED:
        problems.append("xpass is on only %.4f of run and pass plays" % report["run_pass_aligned"])
    if wrong_kind:
        problems.append("%d plays of a kind that never has xpass carry one, e.g. %s" % (len(wrong_kind), wrong_kind[:3]))
    print(json.dumps(report, sort_keys=True))
    if problems:
        raise RuntimeError("; ".join(problems))
    if not apply:
        return report
    for col in COLS:
        have = {r[1] for r in con.execute("PRAGMA table_info(nfl_pbp)")}
        if col not in have:
            con.execute('ALTER TABLE nfl_pbp ADD COLUMN "%s"' % col)
    before = con.total_changes
    con.execute("BEGIN IMMEDIATE")
    try:
        con.executemany('UPDATE nfl_pbp SET "xpass"=?, "pass_oe"=? WHERE game_id=? AND play_id=?',
                        [plays[k][0] + k for k in matched])
        if con.total_changes - before != len(matched):
            raise RuntimeError("updated %d rows, expected %d" % (con.total_changes - before, len(matched)))
        got = con.execute('SELECT COALESCE(SUM("xpass" IS NOT NULL),0), COALESCE(SUM("pass_oe" IS NOT NULL),0) '
                          "FROM nfl_pbp WHERE season = ?", (season,)).fetchone()
        if got != (report["xpass_non_null"], report["pass_oe_non_null"]):
            raise RuntimeError("stored counts %s differ from the file %s" % (got, (report["xpass_non_null"], report["pass_oe_non_null"])))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    print("applied season %d: %d rows" % (season, len(matched)))
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True, help="an absolute directory of its own for the downloaded files")
    ap.add_argument("--seasons", required=True, help="a season or a range, e.g. 2024 or 2010-2025")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    lo, _, hi = a.seasons.partition("-")
    seasons = range(int(lo), int(hi or lo) + 1)
    db = os.environ.get("LP_DB_PATH")
    if not db or os.path.basename(db) == "picks.db" or not os.path.exists(db):
        raise SystemExit("set LP_DB_PATH to an existing dev DB; picks.db is refused")
    if not os.path.isabs(a.dir):
        raise SystemExit("--dir must be absolute")
    os.makedirs(a.dir, exist_ok=True)
    con = sqlite3.connect(db, timeout=120, isolation_level=None)
    con.execute("PRAGMA busy_timeout=120000")
    try:
        for s in seasons:
            backfill(con, download(s, a.dir), s, a.apply)
        print("dry run: nothing written" if not a.apply else "done")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
