#!/usr/bin/env python3
"""Stamp `player_game_logs.game_type` for NBA rows written before the boundary existed.

`ingest_nba_logs.py` never wrote the column — its INSERT did not name it — so all
24,086 nba 2026 rows carry NULL, and `AND game_type='REG'` over them matches
nothing. The column existed and the values did not, which is the exact shape
`docs/DATA-COVERAGE-CONTRACT.md` §1 describes.

The phase comes from ESPN's scoreboard envelope for the date each row already
records, resolved per `game_id` — not from a date-range rule of our own. A
rule would have to encode "regular season ends 2026-04-13", which is a number we
would be copying off the publisher into code that then stops being re-measured.
One request per distinct game date, cached by `espn_client`.

A game the publisher does not return **stays NULL and is reported**. An
unattributable row must keep saying so; that is the same decision
`stamp_team_result_source.py` made for provenance.

    python3 backfill_nba_game_types.py [--season 2026] [--apply]

Default is a dry run.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import espn_client as espn
from game_types import espn_event_phase

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)


def published_phases(dates) -> tuple[dict, list, list]:
    """{game_id: phase} for every completed game ESPN publishes on those dates."""
    phases: dict[str, str] = {}
    unreadable: list[str] = []
    not_played: list[tuple] = []
    for i, ds in enumerate(sorted(dates), 1):
        try:
            events = espn.games("nba", ds)
        except Exception as e:  # a date we cannot read is not a date with no games
            unreadable.append(f"{ds}: {type(e).__name__}: {e}")
            continue
        for g in events:
            gid = str(g.get("game_id") or "")
            if not gid:
                continue
            if not g.get("completed"):
                # A postponed game is state="post" with a score of 0. Stamping it
                # a phase would make an unplayed game indistinguishable from a
                # played one — worse than the NULL, because the NULL at least
                # kept it out of every `game_type='REG'` filter. Report instead.
                not_played.append((ds, gid, g.get("status")))
                continue
            try:
                phases[gid] = espn_event_phase("nba", g)
            except ValueError as e:
                unreadable.append(f"{ds} game {gid}: {e}")
        if i % 25 == 0:
            print(f"  read {i}/{len(dates)} dates, {len(phases)} games published")
    return phases, unreadable, not_played


def main() -> int:
    args = sys.argv[1:]
    season = int(args[args.index("--season") + 1]) if "--season" in args else 2026
    apply = "--apply" in args

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """SELECT game_id, game_date, COUNT(*) n
             FROM player_game_logs
            WHERE league='nba' AND season=? AND game_type IS NULL
            GROUP BY game_id, game_date""",
        (season,),
    ).fetchall()
    if not rows:
        print(f"nba {season}: no NULL game_type rows. Nothing to do.")
        return 0

    total_rows = sum(r["n"] for r in rows)
    dates = {r["game_date"] for r in rows if r["game_date"]}
    print(
        f"nba {season}: {total_rows} rows over {len(rows)} games "
        f"on {len(dates)} distinct dates carry a NULL game_type."
    )

    phases, unreadable, not_played = published_phases(dates)
    print(f"ESPN publishes {len(phases)} completed games across those dates.")

    if not_played:
        print(
            f"\n  NOT PLAYED: {len(not_played)} games we hold rows for were never "
            f"completed. They stay NULL, and the rows should not exist at all:"
        )
        for ds, gid, status in not_played:
            n = con.execute(
                "SELECT COUNT(*) FROM player_game_logs WHERE league='nba' AND game_id=?",
                (gid,),
            ).fetchone()[0]
            print(f"    {gid}  {ds}  {status!r}  {n} rows")

    stamp: dict[str, str] = {}
    missing = []
    by_phase = Counter()
    rows_by_phase = Counter()
    for r in rows:
        phase = phases.get(str(r["game_id"]))
        if phase is None:
            missing.append((r["game_id"], r["game_date"], r["n"]))
            continue
        stamp[str(r["game_id"])] = phase
        by_phase[phase] += 1
        rows_by_phase[phase] += r["n"]

    print("\n  phase     games   rows")
    for phase in sorted(by_phase):
        print(f"  {phase:<8} {by_phase[phase]:>6} {rows_by_phase[phase]:>6}")

    if missing:
        missing_rows = sum(m[2] for m in missing)
        print(
            f"\n  UNRESOLVED: {len(missing)} games / {missing_rows} rows stay NULL — "
            f"ESPN returned no such game on the date we recorded."
        )
        for gid, ds, n in missing[:10]:
            print(f"    {gid}  {ds}  {n} rows")
        if len(missing) > 10:
            print(f"    ... and {len(missing) - 10} more")
    if unreadable:
        print(f"\n  {len(unreadable)} dates/games could not be read:")
        for line in unreadable[:10]:
            print(f"    {line}")

    if not apply:
        print("\nDry run. Re-run with --apply to write.")
        con.close()
        return 0

    by_target = defaultdict(list)
    for gid, phase in stamp.items():
        by_target[phase].append(gid)
    written = 0
    for phase, gids in by_target.items():
        for i in range(0, len(gids), 400):
            chunk = gids[i : i + 400]
            cur = con.execute(
                "UPDATE player_game_logs SET game_type=? "
                " WHERE league='nba' AND season=? AND game_type IS NULL "
                f"   AND game_id IN ({','.join('?' * len(chunk))})",
                [phase, season, *chunk],
            )
            written += cur.rowcount
    con.commit()
    print(f"\nWrote {written} rows.")

    left = con.execute(
        "SELECT COUNT(*) FROM player_game_logs "
        " WHERE league='nba' AND season=? AND game_type IS NULL",
        (season,),
    ).fetchone()[0]
    print(f"Still NULL: {left}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
