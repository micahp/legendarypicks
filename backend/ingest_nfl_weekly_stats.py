"""ingest_nfl_weekly_stats.py -- per-game NFL logs COPIED from nflverse's
maintained weekly box score, instead of re-derived from play-by-play.

Why this exists
---------------
`ingest_nfl_pbp_logs.py` aggregates 372-column play-by-play into per-player-game
lines. Its docstring justified that with "nflverse's pre-built weekly summary
404s for 2025". That is false: the release was renamed `player_stats` ->
`stats_player`, and both 2024 and 2025 return 200. The derivation was built on a
premise nobody rechecked.

The cost of re-deriving was eight defects found in one week, every one of them a
bug in a reimplementation of arithmetic nflverse already publishes correctly:
sacks counted as pass attempts, two-point plays counted as attempts and targets,
lateral receiving and rushing yards dropped, EPA summing `no_play`/`field_goal`
rows, a dropbacks regression, and -- in the hand-rolled `fpts()` -- fumbles lost
never subtracted (184 rows), two-point conversions never added (83), and
special-teams touchdowns never credited (15).

Every field the pbp rollup produces is present in the weekly artifact, including
`passing_epa` and `passing_cpoe`. Snap counts and Next Gen metrics already come
from their own ingests (`ingest_nfl_snap_counts.py`,
`ingest_nfl_ngs_receiving.py`) and are untouched here.

Scope of v1, deliberately narrow
--------------------------------
Emits the SAME row set as the pbp rollup -- players with offensive involvement --
so the swap can be diffed row-for-row against the ingest it replaces. The
artifact also carries defensive and kicking lines (19,421 player-weeks for 2025
against the rollup's 5,377), which would fix the 0% IDP/kicker coverage, but
expanding the row set and verifying a swap at the same time are two changes.
Expansion is a follow-up, behind `--all-positions`.

Retention of raw plays (`nfl_pbp`) stays with the pbp ingest. That table is
genuinely additive for future play-level work; it is only the ROLLUP half this
replaces.

Usage: python3 ingest_nfl_weekly_stats.py [--year 2025] [--dry-run]
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest_nfl_logs import ensure_table  # noqa: E402
from team_codes import normalize

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

SOURCE = "nflverse_weekly"
URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
       "stats_player/stats_player_week_{year}.parquet")

# our key <- official column. The whole point of this module: a mapping, not a
# computation. Anything that needs arithmetic belongs upstream, in nflverse.
_MAP = {
    "att": "attempts",
    "cmp": "completions",
    "pass_yds": "passing_yards",
    "pass_td": "passing_tds",
    "intc": "passing_interceptions",
    "air_yds": "passing_air_yards",
    "pass_epa": "passing_epa",
    "cpoe": "passing_cpoe",
    "carries": "carries",
    "rush_yds": "rushing_yards",
    "rush_td": "rushing_tds",
    "targets": "targets",
    "target_share": "target_share",
    "rec": "receptions",
    "rec_yds": "receiving_yards",
    "rec_td": "receiving_tds",
    "fpts": "fantasy_points",
    "fpts_ppr": "fantasy_points_ppr",
    # Kicker buckets — published verbatim, never re-derived
    "fg_made": "fg_made",
    "fg_att": "fg_att",
    "fg_missed": "fg_missed",
    "fg_blocked": "fg_blocked",
    "fg_long": "fg_long",
    "fg_pct": "fg_pct",
    "fg_made_0_19": "fg_made_0_19",
    "fg_made_20_29": "fg_made_20_29",
    "fg_made_30_39": "fg_made_30_39",
    "fg_made_40_49": "fg_made_40_49",
    "fg_made_50_59": "fg_made_50_59",
    "fg_made_60_": "fg_made_60_",
    "fg_missed_0_19": "fg_missed_0_19",
    "fg_missed_20_29": "fg_missed_20_29",
    "fg_missed_30_39": "fg_missed_30_39",
    "fg_missed_40_49": "fg_missed_40_49",
    "fg_missed_50_59": "fg_missed_50_59",
    "fg_missed_60_": "fg_missed_60_",
    "pat_made": "pat_made",
    "pat_att": "pat_att",
    "pat_missed": "pat_missed",
    "gwfg_made": "gwfg_made",
    "gwfg_att": "gwfg_att",
}

# Groups are emitted only when the player actually had that role, so a QB does
# not acquire a zero receiving line (the pbp ingest has a test for exactly this).
_PASS_KEYS = ("att", "cmp", "pass_yds", "pass_td", "intc", "air_yds",
              "pass_epa", "cpoe", "dropbacks")
_RUSH_KEYS = ("carries", "rush_yds", "rush_td")
_RECV_KEYS = ("targets", "target_share", "rec", "rec_yds", "rec_td")
_TWO_POINT_COLS = (
    "passing_2pt_conversions",
    "rushing_2pt_conversions",
    "receiving_2pt_conversions",
)

_KICK_KEYS = (
    "fg_made", "fg_att", "fg_missed", "fg_blocked", "fg_long", "fg_pct",
    "fg_made_0_19", "fg_made_20_29", "fg_made_30_39", "fg_made_40_49",
    "fg_made_50_59", "fg_made_60_",
    "fg_missed_0_19", "fg_missed_20_29", "fg_missed_30_39",
    "fg_missed_40_49", "fg_missed_50_59", "fg_missed_60_",
    "pat_made", "pat_att", "pat_missed",
    "gwfg_made", "gwfg_att",
)

# Replace both the canonical keys and the legacy nflverse names written by
# ingest_nfl_logs.py.  The 2024 DEV rows still carry those legacy aliases; they
# are box-score data, not snap/NGS enrichment, and must not survive the swap.
_OWNED = set(_MAP) | set(_MAP.values()) | {"dropbacks", "interceptions"} | set(_KICK_KEYS)

_NEEDED = sorted(set(_MAP.values()) | {
    "player_id", "player_display_name", "position", "season", "week",
    "season_type", "game_id", "team", "opponent_team", "sacks_suffered",
} | set(_TWO_POINT_COLS) | set(_KICK_KEYS))


def fetch(year: int, cache_dir: str) -> str:
    """Download the artifact once and report its sha256.

    nflverse rewrites historical files in place -- the 2020 parquet was
    re-uploaded in 2025 -- so the digest is the only thing that makes a run
    reproducible. Print it; a pinned run should compare against a known value.
    """
    path = os.path.join(cache_dir, "stats_player_week_{}.parquet".format(year))
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


def _assert_unique_weeks(table: dict) -> None:
    """Fail before writing if season types reuse a numeric week.

    player_game_logs uses ``game_no=str(week)`` as part of its natural key.  The
    current artifacts continue REG 1-18 into POST 19-22, but a future PRE/REG
    overlap would silently overwrite rows unless that empirical invariant is
    checked on every run.
    """
    season_types_by_week = {}
    for raw_week, raw_season_type in zip(table["week"], table["season_type"]):
        if raw_week is None or raw_season_type is None:
            raise RuntimeError("artifact has a null week or season_type")
        week = int(raw_week)
        season_type = str(raw_season_type).strip()
        if not season_type:
            raise RuntimeError("artifact has a blank season_type for week {}".format(week))
        season_types_by_week.setdefault(week, set()).add(season_type)

    collisions = {
        week: sorted(season_types)
        for week, season_types in season_types_by_week.items()
        if len(season_types) > 1
    }
    if collisions:
        detail = ", ".join(
            "week {} ({})".format(week, "/".join(season_types))
            for week, season_types in sorted(collisions.items())
        )
        raise RuntimeError(
            "artifact reuses game_no week values across season types: {}".format(detail)
        )


def build_rows(path: str, all_positions: bool = False):
    import pyarrow.parquet as pq

    have = set(pq.ParquetFile(path).schema.names)
    missing = [c for c in _NEEDED if c not in have]
    if missing:
        raise RuntimeError("artifact is missing expected columns: {}".format(missing))

    t = pq.read_table(path, columns=_NEEDED).to_pydict()
    _assert_unique_weeks(t)
    out = []
    seen_keys = {}
    for i in range(len(t["player_id"])):
        row = {c: t[c][i] for c in _NEEDED}
        att = _num(row["attempts"]) or 0
        sac = _num(row["sacks_suffered"]) or 0
        car = _num(row["carries"]) or 0
        tgt = _num(row["targets"]) or 0
        converted_two_point = any(_num(row[key]) for key in _TWO_POINT_COLS)
        if not all_positions and not (
            att or sac or car or tgt or converted_two_point
        ):
            continue

        week = int(row["week"])
        natural_key = (str(row["player_id"]), week)
        if natural_key in seen_keys:
            raise RuntimeError(
                "artifact has duplicate player/week key {} week {} (games {} and {})"
                .format(
                    natural_key[0],
                    week,
                    seen_keys[natural_key],
                    row["game_id"],
                )
            )
        seen_keys[natural_key] = row["game_id"]

        stats = {}
        # A kicker is anyone who attempted a field goal or PAT
        fg_att = _num(row["fg_att"]) or 0
        pat_att_val = _num(row["pat_att"]) or 0
        is_kicker = bool(fg_att or pat_att_val)
        groups = ((_PASS_KEYS, att or sac), (_RUSH_KEYS, car),
                  (_RECV_KEYS, tgt), (_KICK_KEYS, is_kicker))
        for keys, active in groups:
            if not active:
                continue
            for k in keys:
                if k == "dropbacks":
                    # verified equal to attempts + sacks_suffered against the
                    # artifact; the only derived value kept, because nflverse
                    # publishes no dropback column.
                    stats[k] = att + sac
                    continue
                v = _num(row[_MAP[k]])
                if v is not None:
                    stats[k] = v
        for k in ("fpts", "fpts_ppr"):
            v = _num(row[_MAP[k]])
            if v is not None:
                stats[k] = v
        if not stats:
            continue
        out.append({
            "gsis": row["player_id"],
            "week": week,
            "game_id": row["game_id"],
            "team": normalize("nfl", row["team"]),
            "opponent": normalize("nfl", row["opponent_team"]),
            "position": row["position"],
            "season_type": row["season_type"],
            "stats": stats,
        })
    return out


def upsert_rows(con: sqlite3.Connection, year: int, rows) -> tuple:
    """Write canonical weekly rows while preserving other ingests' enrichment."""
    con.row_factory = sqlite3.Row
    ensure_table(con)

    gsis_to_player = {
        r["nfl_gsis_id"]: r["id"]
        for r in con.execute(
            "SELECT id, nfl_gsis_id FROM players WHERE league='nfl' "
            "AND nfl_gsis_id IS NOT NULL AND nfl_gsis_id != ''")
    }
    existing = {}
    for r in con.execute(
        "SELECT source_player_key, game_no, stats FROM player_game_logs "
        "WHERE league='nfl' AND season=? AND source_player_key IS NOT NULL "
        "AND game_no IS NOT NULL", (year,)
    ):
        try:
            prior = json.loads(r["stats"])
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "invalid NFL stats JSON for source_player_key={} game_no={}".format(
                    r["source_player_key"], r["game_no"])
            ) from exc
        if not isinstance(prior, dict):
            raise RuntimeError(
                "NFL stats must be an object for source_player_key={} game_no={}".format(
                    r["source_player_key"], r["game_no"])
            )
        existing[(r["source_player_key"], r["game_no"])] = prior

    written = preserved_rows = 0
    for row in rows:
        game_no = str(row["week"])
        prior = existing.get((row["gsis"], game_no), {})
        # Snap counts and Next Gen metrics belong to other ingests -- carry them
        # through untouched. Box-score keys in either vocabulary are replaced.
        keep = {key: value for key, value in prior.items() if key not in _OWNED}
        if keep:
            preserved_rows += 1
        stats = dict(keep)
        stats.update(row["stats"])
        con.execute(
            """INSERT INTO player_game_logs
               (player_id, league, season, game_no, game_id, game_type, team, opponent,
                stats, source, source_player_key)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(league, source_player_key, season, game_no) DO UPDATE SET
                 player_id=COALESCE(excluded.player_id, player_game_logs.player_id),
                 game_id=excluded.game_id,
                 game_type=excluded.game_type,
                 team=excluded.team,
                 opponent=excluded.opponent,
                 stats=excluded.stats,
                 source=excluded.source""",
            (gsis_to_player.get(row["gsis"]), "nfl", year, game_no,
             row["game_id"], row.get("season_type"), row["team"], row["opponent"],
             json.dumps(stats),
             SOURCE, row["gsis"]))
        written += 1

    con.commit()
    return written, preserved_rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--dry-run", action="store_true",
                    help="build and report, write nothing")
    ap.add_argument("--all-positions", action="store_true",
                    help="include defensive and kicking lines (row-set expansion)")
    ap.add_argument("--cache-dir", default="/tmp")
    args = ap.parse_args()

    print("nflverse weekly box score -> player_game_logs  (year={})".format(args.year))
    path = fetch(args.year, args.cache_dir)
    rows = build_rows(path, args.all_positions)
    print("  built {} player-game rows".format(len(rows)))
    if args.dry_run:
        print("  dry run: nothing written")
        return

    con = sqlite3.connect(DB)
    written, preserved_rows = upsert_rows(con, args.year, rows)
    con.close()
    print("  wrote {} rows ({} carried forward snap/NGS keys)".format(
        written, preserved_rows))


if __name__ == "__main__":
    main()
