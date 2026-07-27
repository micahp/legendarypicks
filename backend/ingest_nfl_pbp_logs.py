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
# A curated subset, not all 372: 372 undocumented columns is a schema nobody can
# reason about in three months, and the play text (`desc`) alone is 4.7MB/season.
# Measured cost of the original 34-column subset: 15.7MB per season in SQLite.
#
# The selection rule is not "columns that look interesting" -- it is **every
# column the rollup below reads**. The first cut broke that rule: it kept
# `receiver_player_id` but not `receiving_yards`, and none of the lateral or
# eligibility columns, so the retained plays could not reproduce (and therefore
# could not falsify) the very numbers derived from them. Adding a field to the
# aggregation means adding its source columns here.
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
    # Eligibility: which plays count toward an official stat line (see _eligible).
    "sack", "two_point_attempt",
    # The yardage and event columns the rollup actually sums.
    "pass_attempt", "rush_attempt", "passing_yards", "rushing_yards",
    "receiving_yards", "pass_touchdown", "rush_touchdown", "interception",
    # Laterals. A completed pass that is pitched onward credits the extra yards
    # to a second player; ignoring these silently under-counts the receiver.
    "lateral_receiver_player_id", "lateral_receiver_player_name",
    "lateral_receiving_yards",
    "lateral_rusher_player_id", "lateral_rusher_player_name",
    "lateral_rushing_yards",
]

_ROLLUP_STAT_FIELDS = [
    "att", "cmp", "pass_yds", "pass_td", "intc", "air_yds", "pass_epa", "cpoe",
    "dropbacks",
    "carries", "rush_yds", "rush_td", "targets", "rec", "rec_yds", "rec_td",
]
_ROLLUP_OWNED_STATS = set(_ROLLUP_STAT_FIELDS) | {"fpts", "fpts_ppr"}


def ensure_pbp_table(con: sqlite3.Connection) -> None:
    """Create nfl_pbp (additive, idempotent). One row per play."""
    cols = ", ".join('"{}"'.format(c) for c in _PLAY_COLS)
    con.execute("CREATE TABLE IF NOT EXISTS nfl_pbp ({}, UNIQUE(game_id, play_id))".format(cols))
    # CREATE TABLE IF NOT EXISTS is a no-op against a table built from an older,
    # shorter _PLAY_COLS -- so widen it explicitly. Without this the positional
    # INSERT below would bind 50 values into a 34-column table.
    have = {r[1] for r in con.execute("PRAGMA table_info(nfl_pbp)")}
    for col in _PLAY_COLS:
        if col not in have:
            con.execute('ALTER TABLE nfl_pbp ADD COLUMN "{}"'.format(col))
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

    # Which plays count toward an official stat line. The original rollup used
    # the raw pbp flags directly, as if `pass_attempt == 1` meant "a pass
    # attempt". It does not: nflverse sets it on sacks and on two-point
    # conversions, neither of which is an official attempt. Reconciled against
    # nflverse's own weekly artifact for 2025, that inflated `att` on 514 of
    # 5,377 player-games (432 by exactly the passer's sack count) and `targets`
    # on 88. With this filter both reconcile to zero differences.
    eligible = df[(df["sack"] != 1) & (df["two_point_attempt"] != 1)]

    # Passing — group by passer per game
    pa = eligible[eligible["passer_player_id"].notna()].groupby(["passer_player_id"] + keys).agg(
        att=("pass_attempt", "sum"), cmp=("complete_pass", "sum"),
        pass_yds=("passing_yards", "sum"), pass_td=("pass_touchdown", "sum"),
        intc=("interception", "sum"), air_yds=("air_yards", "sum"),
        cpoe=("cpoe", "mean"),
        name=("passer_player_name", "first")).reset_index().rename(columns={"passer_player_id": "pid"})

    # EPA is deliberately NOT restricted to eligible plays: a sack is a real
    # negative outcome of a dropback and belongs in a quarterback's EPA. That
    # makes `att` and `pass_epa` different denominators, so the dropback count
    # is carried explicitly rather than left implicit in `att` -- which is what
    # `epa_per_db` in routers/nfl_usage.py had been dividing by.
    db = df[df["passer_player_id"].notna()].groupby(["passer_player_id"] + keys).agg(
        pass_epa=("qb_epa", "sum"), dropbacks=("pass_attempt", "sum"),
    ).reset_index().rename(columns={"passer_player_id": "pid"})
    pa = pa.merge(db, on=["pid"] + keys, how="outer")

    # Rushing
    ru = eligible[eligible["rusher_player_id"].notna()].groupby(["rusher_player_id"] + keys).agg(
        carries=("rush_attempt", "sum"), rush_yds=("rushing_yards", "sum"),
        rush_td=("rush_touchdown", "sum"),
        name=("rusher_player_name", "first")).reset_index().rename(columns={"rusher_player_id": "pid"})

    # Receiving — each eligible play with a receiver = a target
    re = eligible[eligible["receiver_player_id"].notna()].groupby(["receiver_player_id"] + keys).agg(
        targets=("play_id", "count"), rec=("complete_pass", "sum"),
        rec_yds=("receiving_yards", "sum"), rec_td=("pass_touchdown", "sum"),
        name=("receiver_player_name", "first")).reset_index().rename(columns={"receiver_player_id": "pid"})

    # Laterals. `receiving_yards` stops at the player who caught the ball, so a
    # pitch onward left the yards credited to nobody: DJ Moore's 2025 week 1 was
    # stored as 57 against an official 68, the missing 11 being the lateral. The
    # lateral player may have no other touch in the game, hence an outer merge.
    def _lateral(id_col, name_col, yds_col, out_col):
        lat = eligible[eligible[id_col].notna()].groupby([id_col] + keys).agg(
            **{out_col: (yds_col, "sum"), "lat_name": (name_col, "first")}
        ).reset_index().rename(columns={id_col: "pid"})
        return lat

    # KNOWN RESIDUAL: the pbp schema has exactly one lateral slot per play, so a
    # play pitched twice cannot be represented. nflverse publishes a separate
    # `multiple_lateral_yards.rds` supplement for precisely this, which is an R
    # serialization this venv cannot read. Two 2025 player-games remain off as a
    # result (00-0034827 wk15, 00-0036252 wk18) out of 5,377. Every other field
    # reconciles exactly; do not "fix" these two by fudging the lateral sums.
    lat_re = _lateral("lateral_receiver_player_id", "lateral_receiver_player_name",
                      "lateral_receiving_yards", "lat_rec_yds")
    lat_ru = _lateral("lateral_rusher_player_id", "lateral_rusher_player_name",
                      "lateral_rushing_yards", "lat_rush_yds")

    merged = pa.merge(ru, on=["pid"] + keys, how="outer", suffixes=("", "_r")) \
               .merge(re, on=["pid"] + keys, how="outer", suffixes=("", "_e")) \
               .merge(lat_re, on=["pid"] + keys, how="outer", suffixes=("", "_lr")) \
               .merge(lat_ru, on=["pid"] + keys, how="outer", suffixes=("", "_lu"))
    # Sum where either side exists, but stay NaN where neither does -- the write
    # loop below omits NaN fields, and filling with 0 would put `rec_yds: 0` in
    # every quarterback's blob.
    for base, lat in (("rec_yds", "lat_rec_yds"), ("rush_yds", "lat_rush_yds")):
        present = merged[base].notna() | merged[lat].notna()
        merged[base] = (merged[base].fillna(0) + merged[lat].fillna(0)).where(present)
    merged["name"] = merged["name"].fillna(merged.get("name_r")).fillna(merged.get("name_e")) \
                                   .fillna(merged.get("lat_name")).fillna(merged.get("lat_name_lu"))
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
    produced = set()
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
        produced.add((gsis, game_no))
        ingested += 1

    # Rows this run no longer produces. Tightening the eligibility rule means a
    # player whose only "target" was a two-point conversion now has no stat line
    # at all -- but his row from the previous, looser run still sits there with
    # `targets: 1`. Left alone that stale value survives every future run,
    # because a row that is never produced is never updated. Strip only the
    # rollup-owned keys; snap counts and Next Gen enrichment from other ingests
    # are somebody else's data and stay.
    stale_rows = 0
    stale_keys = 0
    for (gsis, game_no), old in existing_stats.items():
        if (gsis, game_no) in produced:
            continue
        drop = [k for k in old if k in _ROLLUP_OWNED_STATS]
        if not drop:
            continue
        kept = {k: v for k, v in old.items() if k not in _ROLLUP_OWNED_STATS}
        con.execute(
            """UPDATE player_game_logs SET stats=?
               WHERE league='nfl' AND source_player_key=? AND season=? AND game_no=?""",
            (json.dumps(kept), gsis, year, game_no))
        stale_rows += 1
        stale_keys += len(drop)

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
    if stale_rows:
        print(f"  Cleared {stale_keys} stale rollup keys from {stale_rows} rows this run no longer produces")
    print(f"  Ingested {ingested} NFL pbp game-logs ({resolved} spine-resolved)")
    con.close()
    return ingested


if __name__ == "__main__":
    year = 2025
    if "--year" in sys.argv:
        year = int(sys.argv[sys.argv.index("--year") + 1])
    ingest(year)
