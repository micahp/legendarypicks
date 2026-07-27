#!/usr/bin/env python3
"""
ingest_nfl_pbp_logs.py — per-GAME NFL logs derived from nflverse play-by-play.

nflverse's pre-built weekly summary 404s for 2025, but the raw play-by-play IS
published (richer: per-play EPA, CPOE, air yards). This aggregates pbp into
per-player-per-game lines (passing / rushing / receiving + EPA) and writes them
to player_game_logs — the richest free option for the latest NFL season.

Usage: python3 ingest_nfl_pbp_logs.py [--year 2025]
"""
import sys, os, json, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest_nfl_logs import ensure_table

DB = os.environ.get("LP_DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")


# Plays worth keeping. This ingest already downloads all 372 pbp columns and
# builds a ~388MB frame to produce the per-game rollup below, then throws every
# play away -- so the rollup was the only record, and no number in it could be
# checked without re-downloading and recomputing by hand.
#
# Only 34 columns are retained, not all 372: 372 undocumented columns is a schema
# nobody can reason about in three months, and the play text (`desc`) alone is
# 4.7MB/season. Measured cost of this subset: 15.7MB per season in SQLite with
# the indexes below, against a 122MB picks.db.
#
# NOTE: this is the curated query layer, NOT an archival copy. nflverse rewrites
# historical files in place -- the 2020 parquet was re-uploaded in 2025 -- so
# retaining the raw artifact with a checksum is a separate, still-open job.
_PLAY_COLS = [
    "game_id", "play_id", "season", "week", "posteam", "defteam",
    "home_team", "away_team", "game_date",
    "qtr", "down", "ydstogo", "yardline_100", "game_seconds_remaining",
    "play_type", "epa", "wpa", "qb_epa", "air_yards", "yards_gained", "cpoe",
    "passer_player_id", "rusher_player_id", "receiver_player_id",
    "pass_location", "run_location", "run_gap", "complete_pass", "touchdown",
    "series", "series_result", "drive", "success", "shotgun",
]

_ROLLUP_STAT_FIELDS = [
    "att", "cmp", "pass_yds", "pass_td", "intc", "air_yds", "pass_epa", "cpoe",
    "carries", "rush_yds", "rush_td", "targets", "rec", "rec_yds", "rec_td",
]
_ROLLUP_OWNED_STATS = set(_ROLLUP_STAT_FIELDS) | {"fpts", "fpts_ppr"}


def ensure_pbp_table(con: sqlite3.Connection) -> None:
    """Create nfl_pbp (additive, idempotent). One row per play."""
    cols = ", ".join('"{}"'.format(c) for c in _PLAY_COLS)
    con.execute("CREATE TABLE IF NOT EXISTS nfl_pbp ({}, UNIQUE(game_id, play_id))".format(cols))
    # Player-scoped lookups are the whole point -- every chart asks "this player,
    # this season". Without these each question scans the full play table.
    con.execute("CREATE INDEX IF NOT EXISTS idx_pbp_game ON nfl_pbp(game_id, play_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_pbp_passer ON nfl_pbp(passer_player_id, season)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_pbp_rusher ON nfl_pbp(rusher_player_id, season)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_pbp_receiver ON nfl_pbp(receiver_player_id, season)")
    con.commit()


def load_existing_stats(con: sqlite3.Connection, year: int) -> dict:
    """Return the current season rollups keyed by their source natural key."""
    existing = {}
    for row in con.execute(
        """SELECT source_player_key, game_no, stats
           FROM player_game_logs
           WHERE league='nfl' AND season=?
             AND source_player_key IS NOT NULL AND game_no IS NOT NULL""",
        (year,),
    ):
        try:
            stats = json.loads(row["stats"])
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "invalid NFL stats JSON for source_player_key={} game_no={}".format(
                    row["source_player_key"], row["game_no"]
                )
            ) from exc
        if not isinstance(stats, dict):
            raise RuntimeError(
                "NFL stats must be an object for source_player_key={} game_no={}".format(
                    row["source_player_key"], row["game_no"]
                )
            )
        existing[(str(row["source_player_key"]), str(row["game_no"]))] = stats
    return existing


def ingest(year: int = 2025) -> int:
    import warnings; warnings.filterwarnings("ignore")
    import nfl_data_py as nfl
    import pandas as pd

    print(f"Loading nflverse pbp {year}...")
    df = nfl.import_pbp_data([year])
    df = df[df["season_type"] == "REG"] if "season_type" in df.columns else df
    print(f"  {len(df)} plays")

    keys = ["game_id", "week", "posteam", "defteam"]

    # Passing — group by passer per game
    pa = df[df["passer_player_id"].notna()].groupby(["passer_player_id"] + keys).agg(
        att=("pass_attempt", "sum"), cmp=("complete_pass", "sum"),
        pass_yds=("passing_yards", "sum"), pass_td=("pass_touchdown", "sum"),
        intc=("interception", "sum"), air_yds=("air_yards", "sum"),
        pass_epa=("qb_epa", "sum"), cpoe=("cpoe", "mean"),
        name=("passer_player_name", "first")).reset_index().rename(columns={"passer_player_id": "pid"})

    # Rushing
    ru = df[df["rusher_player_id"].notna()].groupby(["rusher_player_id"] + keys).agg(
        carries=("rush_attempt", "sum"), rush_yds=("rushing_yards", "sum"),
        rush_td=("rush_touchdown", "sum"),
        name=("rusher_player_name", "first")).reset_index().rename(columns={"rusher_player_id": "pid"})

    # Receiving — each play with a receiver = a target
    re = df[df["receiver_player_id"].notna()].groupby(["receiver_player_id"] + keys).agg(
        targets=("play_id", "count"), rec=("complete_pass", "sum"),
        rec_yds=("receiving_yards", "sum"), rec_td=("pass_touchdown", "sum"),
        name=("receiver_player_name", "first")).reset_index().rename(columns={"receiver_player_id": "pid"})

    merged = pa.merge(ru, on=["pid"] + keys, how="outer", suffixes=("", "_r")) \
               .merge(re, on=["pid"] + keys, how="outer", suffixes=("", "_e"))
    merged["name"] = merged["name"].fillna(merged.get("name_r")).fillna(merged.get("name_e"))
    print(f"  {len(merged)} player-game lines")

    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    ensure_table(con)
    existing_stats = load_existing_stats(con, year)

    # Retain the plays before deriving anything from them.
    ensure_pbp_table(con)
    have = [c for c in _PLAY_COLS if c in df.columns]
    if len(have) != len(_PLAY_COLS):
        # Fail loud rather than silently persisting a narrower table than the
        # readers expect -- a missing column here means nflverse renamed
        # something, which is exactly the class of drift that went unnoticed
        # between the 2024 and 2025 schemas.
        raise RuntimeError("pbp source is missing expected columns: {}".format(
            sorted(set(_PLAY_COLS) - set(have))))
    plays = df[_PLAY_COLS].astype(object).where(df[_PLAY_COLS].notna(), None)
    con.executemany(
        "INSERT OR REPLACE INTO nfl_pbp VALUES ({})".format(",".join("?" * len(_PLAY_COLS))),
        plays.itertuples(index=False, name=None))
    con.commit()
    print(f"  retained {con.execute('SELECT COUNT(*) FROM nfl_pbp WHERE season=?', (year,)).fetchone()[0]} plays")

    # game_date and home_away were passed as literal None on every row, leaving
    # them NULL across all 10,717 NFL rows, while the source frame carried both
    # the whole time. Build the lookup once from the plays just retained.
    game_meta = {}
    for gid, gdate, home in df[["game_id", "game_date", "home_team"]].itertuples(index=False, name=None):
        if gid not in game_meta:
            game_meta[gid] = (str(gdate)[:10] if gdate is not None and gdate == gdate else None, home)
    gsis_to_player = {
        r["nfl_gsis_id"]: r["id"]
        for r in con.execute("SELECT id, nfl_gsis_id FROM players WHERE league='nfl' AND nfl_gsis_id IS NOT NULL AND nfl_gsis_id != ''")
    }

    # standard / PPR fantasy from the projected line
    def fpts(s, ppr=0.0):
        return round(
            s.get("pass_yds", 0) * 0.04 + s.get("pass_td", 0) * 4 - s.get("intc", 0) * 2
            + s.get("rush_yds", 0) * 0.1 + s.get("rush_td", 0) * 6
            + s.get("rec_yds", 0) * 0.1 + s.get("rec_td", 0) * 6 + s.get("rec", 0) * ppr, 2)

    ingested = 0
    preserved_key_count = 0
    preserved_row_count = 0
    preserved_key_names = set()
    for _, row in merged.iterrows():
        gsis = str(row["pid"])
        pid = gsis_to_player.get(gsis)
        owned_stats = {}
        for f in _ROLLUP_STAT_FIELDS:
            v = row.get(f)
            if v is None or v != v:  # NaN
                continue
            fv = float(v)
            owned_stats[f] = int(fv) if fv.is_integer() else round(fv, 2)
        owned_stats["fpts"] = fpts(owned_stats)
        owned_stats["fpts_ppr"] = fpts(owned_stats, 1.0)
        game_no = str(int(row["week"]))
        preserved = {
            key: value
            for key, value in existing_stats.get((gsis, game_no), {}).items()
            if key not in _ROLLUP_OWNED_STATS
        }
        if preserved:
            preserved_key_count += len(preserved)
            preserved_row_count += 1
            preserved_key_names.update(preserved)
        stats = dict(preserved)
        stats.update(owned_stats)
        game_date, home_team = game_meta.get(row["game_id"], (None, None))
        home_away = ("home" if row["posteam"] == home_team else "away") if home_team else None
        con.execute(
            """INSERT INTO player_game_logs
               (player_id, league, season, game_no, game_id, game_date, team,
                opponent, home_away, stats, source, source_player_key)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(league, source_player_key, season, game_no) DO UPDATE SET
                 player_id=COALESCE(excluded.player_id, player_game_logs.player_id),
                 game_id=excluded.game_id,
                 game_date=COALESCE(excluded.game_date, player_game_logs.game_date),
                 team=excluded.team,
                 opponent=excluded.opponent,
                 home_away=COALESCE(excluded.home_away, player_game_logs.home_away),
                 stats=excluded.stats,
                 source=excluded.source""",
            (pid, "nfl", year, game_no, row["game_id"], game_date,
             row["posteam"], row["defteam"], home_away, json.dumps(stats),
             "nflverse_pbp", gsis))
        ingested += 1

    con.commit()
    resolved = con.execute(
        "SELECT COUNT(*) FROM player_game_logs WHERE league='nfl' AND season=? AND source='nflverse_pbp' AND player_id IS NOT NULL",
        (year,)).fetchone()[0]
    print(
        "  Preserved {} existing stat keys across {} player-game rows ({})".format(
            preserved_key_count,
            preserved_row_count,
            ", ".join(sorted(preserved_key_names)) or "none",
        )
    )
    print(f"  Ingested {ingested} NFL pbp game-logs ({resolved} spine-resolved)")
    con.close()
    return ingested


if __name__ == "__main__":
    year = 2025
    if "--year" in sys.argv:
        year = int(sys.argv[sys.argv.index("--year") + 1])
    ingest(year)
