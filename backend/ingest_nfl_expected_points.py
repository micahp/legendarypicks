"""ingest_nfl_expected_points.py -- merge PUBLISHED expected fantasy points
into existing NFL game logs.

Why this exists
---------------
The draft board's headline number is a per-game average, and a per-game average
over a short sample is mostly touchdown variance. Expected fantasy points (xFP)
prices the OPPORTUNITY a player was given -- targets, air yards, carries, and
where on the field they happened -- rather than whether the ball bounced in.
It is the same idea as the availability work: separate what the player was
given from what happened to come of it.

Measured on our own data (2024 -> 2025, QB/RB/WR/TE), xFP per game predicts next
season's actual PPR per game better than actual PPR per game does, and the gap
is widest exactly where the sample is thinnest:

    2024 sample     actual PPR/g -> 2025      xFP/g -> 2025
    <= 4 games          r = 0.374              r = 0.424
    >= 10 games         r = 0.775              r = 0.778

Read that honestly: xFP makes a 3-game sample LESS MISLEADING, not reliable.
r = 0.42 is still weak. The board must keep showing sample size next to it.

Published, not derived
----------------------
ffverse/ffopportunity publishes per-player-week expected points (2006-2025).
This module is a mapping, not a computation -- the same rule as
ingest_nfl_weekly_stats.py. Anything needing a model belongs upstream. See
docs/ROADMAP.md and the nflverse lesson: check whether the value is published
before building a derivation of it.

Scoring
-------
ffopportunity's ``total_fantasy_points`` matched our ``fpts_ppr`` on 97.5% of
5,629 shared 2025 rows and our standard ``fpts`` on only 26.1%, so the expected
column is PPR and directly comparable to the board's PPR contract. That is an
empirical claim about someone else's artifact, so ``--check-scoring`` re-verifies
it on every run rather than trusting this docstring.

Usage: python3 ingest_nfl_expected_points.py [--year 2025] [--dry-run]
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import urllib.request

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

SOURCE = "ffopportunity_ep_weekly"
URL = ("https://github.com/ffverse/ffopportunity/releases/download/"
       "latest-data/ep_weekly_{year}.parquet")

# our key <- official column. A mapping, not a computation.
_MAP = {
    "xfpts_ppr": "total_fantasy_points_exp",
}

_NEEDED = sorted(set(_MAP.values()) | {
    "player_id", "game_id", "week", "season", "total_fantasy_points",
})

# Below this agreement rate with our own PPR column, the upstream artifact has
# changed scoring conventions and the merge must not proceed.
_PPR_AGREEMENT_FLOOR = 0.90


def fetch(year: int, cache_dir: str) -> str:
    """Download the artifact once and report its sha256.

    ffopportunity republishes `latest-data` in place as the season progresses,
    so the digest is the only thing that makes a run reproducible.
    """
    path = os.path.join(cache_dir, "ep_weekly_{}.parquet".format(year))
    if not os.path.exists(path):
        urllib.request.urlretrieve(URL.format(year=year), path)
    with open(path, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    print("  artifact: {} ({} bytes)".format(os.path.basename(path),
                                             os.path.getsize(path)))
    print("  sha256  : {}".format(digest))
    return path


def _num(v):
    """Parquet nulls arrive as None or NaN; both mean 'absent', not zero."""
    if v is None or v != v:
        return None
    f = float(v)
    return int(f) if f.is_integer() else round(f, 3)


def _assert_ppr_scoring(matched: list) -> None:
    """Fail before writing if the upstream artifact is no longer PPR.

    ``matched`` is a list of (their_actual, our_ppr) pairs. If ffopportunity
    switched to standard or half-PPR, ``xfpts_ppr`` would silently become
    incomparable to every other number on the board -- a wrong number with no
    symptom. Cheap to check, so check it every run.
    """
    pairs = [(t, o) for t, o in matched if t is not None and o is not None]
    if not pairs:
        raise RuntimeError("no overlapping rows to verify scoring against")
    agree = sum(1 for t, o in pairs if abs(t - o) < 0.02) / len(pairs)
    print("  scoring : {:.1f}% of {} shared rows match our PPR column".format(
        agree * 100, len(pairs)))
    if agree < _PPR_AGREEMENT_FLOOR:
        raise RuntimeError(
            "expected-points artifact no longer agrees with our PPR scoring "
            "({:.1f}% < {:.0f}% floor) -- upstream scoring likely changed; "
            "do not merge".format(agree * 100, _PPR_AGREEMENT_FLOOR * 100))


def run(year: int, cache_dir: str, dry_run: bool = False) -> int:
    import pyarrow.parquet as pq

    path = fetch(year, cache_dir)
    have = set(pq.ParquetFile(path).schema.names)
    missing = [c for c in _NEEDED if c not in have]
    if missing:
        raise RuntimeError("artifact is missing expected columns: {}".format(missing))
    t = pq.read_table(path, columns=_NEEDED).to_pydict()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # (gsis id, game_id) -> game log row. Both keys come straight from nflverse
    # ids, so this is an exact join rather than a name match.
    log_index = {}
    our_ppr = {}
    for r in con.execute(
            "SELECT id, source_player_key, game_id, stats FROM player_game_logs "
            "WHERE league='nfl' AND season=? AND source_player_key IS NOT NULL "
            "AND game_id IS NOT NULL", (year,)):
        key = (r["source_player_key"], r["game_id"])
        log_index[key] = r["id"]
        try:
            our_ppr[key] = json.loads(r["stats"]).get("fpts_ppr")
        except (json.JSONDecodeError, TypeError):
            our_ppr[key] = None
    print("  {} existing {} game logs to match against".format(len(log_index), year))

    pending = []
    scoring_pairs = []
    no_log = 0
    for i in range(len(t["player_id"])):
        key = (t["player_id"][i], t["game_id"][i])
        log_id = log_index.get(key)
        if log_id is None:
            # Defensive/kicking lines and players with no game log. Expected.
            no_log += 1
            continue
        scoring_pairs.append((_num(t["total_fantasy_points"][i]), our_ppr.get(key)))

        add = {}
        for our_key, col in _MAP.items():
            v = _num(t[col][i])
            if v is not None:
                add[our_key] = v
        if add:
            pending.append((log_id, add))

    print("  matched {} expected-point rows to game logs (skipped {} with no "
          "game log)".format(len(pending), no_log))
    _assert_ppr_scoring(scoring_pairs)

    if dry_run:
        for log_id, add in pending[:5]:
            r = con.execute(
                "SELECT p.name, l.team, l.game_no FROM player_game_logs l "
                "LEFT JOIN players p ON p.id=l.player_id WHERE l.id=?",
                (log_id,)).fetchone()
            print("    DRY {} {} wk{} += {}".format(
                r["name"], r["team"], r["game_no"], add))
        con.close()
        return 0

    # json_patch merges the new key without disturbing existing ones, so this is
    # safe to re-run and never clobbers the box score already present.
    for log_id, add in pending:
        con.execute(
            "UPDATE player_game_logs SET stats = json_patch(stats, ?) WHERE id=?",
            (json.dumps(add), log_id))
    con.commit()

    carried = con.execute(
        "SELECT COUNT(*) FROM player_game_logs WHERE league='nfl' AND season=? "
        "AND json_extract(stats,'$.xfpts_ppr') IS NOT NULL", (year,)).fetchone()[0]
    print("  Updated {} rows; {} {} logs now carry xfpts_ppr".format(
        len(pending), carried, year))
    con.close()
    return len(pending)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cache-dir", default=os.environ.get("LP_CACHE_DIR", "/tmp"))
    args = ap.parse_args()

    print("ingest_nfl_expected_points: {} -> {}".format(args.year, DB))
    run(args.year, args.cache_dir, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
