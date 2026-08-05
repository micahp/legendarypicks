"""The season-key boundary: a foreign publisher's season vocabulary -> ours.

Sibling of `team_codes.normalize()`, and it exists for the same reason. A wrong
team code does not raise, it misses — 178 players, silently. A wrong season key
behaves identically: `WHERE season=2026` over rows written as `20252026` returns
zero, and zero reads as "we have no data" rather than "we asked the wrong
question". That is exactly how NHL 2026 came to sit at `partial` with all 1,312
of its games present in the database.

**Ours is ESPN's key, and ESPN has no league-wide convention.** Measured
2026-08-02 from `types[].startDate/endDate` (docs/DATA-COVERAGE-CONTRACT.md, "On
the season key"):

    NBA  seasons/2026 -> 2025-10-21 .. 2026-04-13   keys by the year it ENDS
    NHL  seasons/2026 -> 2025-10-07 .. 2026-04-18   keys by the year it ENDS
    NFL  seasons/2026 -> 2026-09-09 .. 2027-01-13   keys by the year it STARTS
    MLB  seasons/2026 -> 2026-03-25 .. 2026-09-29   one calendar year
    EPL  seasons/2025 =  "2025-26 English Premier League"   the year it STARTS

So there is no rule of the form "use the start year" to apply here, and any
helper that offered one would be wrong for half the leagues. Each entry below
records the *measured* correspondence for one publisher, one league.

Re-measured 2026-08-05 from `sports.core.api.espn.com/.../seasons/{year}`, and
extended a year so the *upcoming*-season case is answered too — that is the one
that looks like an off-by-one and is not:

    nba  2026 = 2025-10-01 .. 2026-06-27  "2025-26"    2027 = "2026-27"
    nhl  2026 = 2025-09-20 .. 2026-07-01  "2025-26"    2027 = "2026-27"
    nfl  2026 = 2026-08-06 .. 2027-02-16  "2026"       (2027 not yet published)
    mlb  2026 = 2026-02-19 .. 2026-11-12  "2026"       2027 = "2027"

**Why `roster_snapshots` holds 2027 for NHL/NBA and 2026 for NFL/MLB.** It is not
a bug and it is not two conventions — it is one convention applied to leagues
whose seasons start in different years. A roster captured in August 2026 belongs
to the *upcoming* season: for NHL and NBA that season ends in 2027, for NFL and
MLB it is 2026. Checked and confirmed 2026-08-05, after being flagged twice as a
suspected inconsistency. Do not "fix" it.

**Status 2026-08-05:** every season value in prod is ESPN's key. The last holdout
was `player_game_logs` for NHL — 48,017 rows still carrying nhle.com's raw
`20252026`, because `migrate_nhl_season_keys.py` had been run against dev and
never against prod. A season-scoped join between `player_stats` and
`player_game_logs` returned **0** for NHL while returning 6k-52k for every other
league. Migrated; it now returns 48,017.

Normalise at the boundary — in the ingest, at the moment the foreign value is
read — never in a query. A query that translates keys has to be remembered at
every call site; a boundary has to be remembered once.
"""

from __future__ import annotations

# Publishers whose season key is not ESPN's, keyed by (source, league).
#
# nhle.com publishes an 8-digit YYYYZZZZ spanning both calendar years of the
# season ("20252026"). ESPN keys the same season 2026 — the year it ends — so the
# correspondence is the second half. This is measured, not inferred: it is only
# true because NHL happens to be an end-year league for ESPN. Do NOT copy this
# entry for a new publisher without reading that publisher's dates and ESPN's
# dates for the same season and confirming they name the same window.
_SPAN_TO_END_YEAR = {("nhle.com", "nhl")}


def normalize_season(source: str, league: str, season) -> int:
    """Return the ESPN-keyed season for a value published by `source`.

    Raises ValueError rather than guessing. A season key that cannot be
    translated is not a value to pass through — passing it through is what put
    two vocabularies in one database.
    """
    src = str(source or "").strip().lower()
    lg = str(league or "").strip().lower()
    raw = str(season or "").strip()

    if not raw:
        raise ValueError(f"empty season from {src or '<no source>'}/{lg or '<no league>'}")

    if (src, lg) in _SPAN_TO_END_YEAR and len(raw) == 8 and raw.isdigit():
        start, end = int(raw[:4]), int(raw[4:])
        if end != start + 1:
            raise ValueError(
                f"{src} published season {raw!r} whose halves are not consecutive "
                f"years ({start}, {end}) — the format is not what this boundary "
                f"was measured against"
            )
        return end

    # Already a plain year, from this publisher or another. Accepted, and range
    # -checked: a 4-digit value is the only other shape we have ever seen, and
    # letting an unrecognised one through is the failure mode this module exists
    # to stop.
    if raw.isdigit() and len(raw) == 4:
        return int(raw)

    raise ValueError(
        f"no measured season-key correspondence for {src}/{lg} value {raw!r}; "
        f"read the publisher's startDate/endDate and ESPN's for the same season, "
        f"then add the case here — see docs/DATA-COVERAGE-CONTRACT.md"
    )


# ---------------------------------------------------------------------------
#  Detection — because a boundary only protects what is written after it
# ---------------------------------------------------------------------------

# Every table holding a season-keyed row, and how to scope it to one league.
# A table absent from this list is not audited, which is the same as saying it
# cannot be trusted to agree with the others.
SEASON_KEYED_TABLES = (
    ("player_game_logs", "league"),
    ("player_stats", "league"),
    ("team_game_results", "league"),
    ("team_stats_coverage", "league"),
)


def audit_season_keys(conn, tables=SEASON_KEYED_TABLES):
    """Every (league, table) whose season column holds more than one key shape.

    This is the check that was missing. The NHL split was visible in the
    database for as long as it existed — `20252026` in one table and `2026` in
    another, four keystrokes apart — and nothing looked, because every surface
    that could have noticed queried one table at a time and got a plausible
    answer back. `reconcile_totals` finally surfaced it as `ours=0
    published=1312`, i.e. as MISSING DATA, which is the wrong diagnosis: the
    data was complete and the question was misspelled.

    Returns a list of dicts, one per offending (league, column-shape) group.
    Empty means every league speaks one season vocabulary per table.

    Shape, not value, is what is compared: 4-digit vs 8-digit. Two different
    4-digit years in one table are just two seasons.
    """
    findings = []
    for table, league_col in tables:
        try:
            rows = conn.execute(
                f"SELECT {league_col} AS lg, LENGTH(CAST(season AS TEXT)) AS shape,"
                f" COUNT(*) AS n, MIN(season) AS lo, MAX(season) AS hi"
                f" FROM {table} WHERE season IS NOT NULL AND season != ''"
                f" GROUP BY lg, shape"
            ).fetchall()
        except Exception:
            # A table this database does not have is not a finding. A table it
            # has and cannot read is — but that is a different alarm, and
            # silencing it here would be the presence-as-integrity mistake.
            continue
        by_league = {}
        for r in rows:
            lg, shape, n, lo, hi = r[0], r[1], r[2], r[3], r[4]
            by_league.setdefault(lg, []).append((shape, n, lo, hi))
        for lg, shapes in by_league.items():
            if len(shapes) > 1:
                findings.append({
                    "table": table,
                    "league": lg,
                    "shapes": sorted(shapes),
                })
    return findings


def cross_table_split(conn, league, tables=SEASON_KEYED_TABLES):
    """The season keys one league carries in each table, for comparison.

    `audit_season_keys` catches a split *within* a table. This catches the one
    that actually bit: each table internally consistent, and no two agreeing.
    """
    out = {}
    for table, league_col in tables:
        try:
            rows = conn.execute(
                f"SELECT DISTINCT season FROM {table} WHERE {league_col}=?"
                f" AND season IS NOT NULL AND season != '' ORDER BY season",
                (league,),
            ).fetchall()
        except Exception:
            continue
        out[table] = [r[0] for r in rows]
    return out
