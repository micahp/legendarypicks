#!/usr/bin/env python3
"""Promote MLS season `player_stats` from dev to prod, keyed on the PUBLISHER id.

Why this exists
---------------
Measured 2026-08-17: `player_stats` where `league='mls'` holds 850 rows on
picks.dev.db and 332 on picks.db, and prod is a strict SUBSET — 518 rows only on
dev, 0 only on prod. The visible consequence is that prod's MLS scoring leader
comes out as Anders Dreyer while dev's is Lionel Messi, because Messi's row is
one of the 518. The Stats tab ships in v0.8.0, so prod would launch the surface
with a leaderboard missing its most recognisable name.

This is a DATA fix. It reaches production the moment it runs and does not wait on
a release (`docs/ROADMAP.md`, "a data fix reaches prod the moment it runs").

The key
-------
`players.id` is an autoincrement local to each database and the two have forked,
so a row-copy that carried `player_id` across would attach stats to whoever
happens to hold that integer on the other side. Every mapping here goes through
`players.espn_id`, which prod already declares `UNIQUE(espn_id, league)`, and
never through a name. Names are used for nothing but the run log.

That is the rule the MLB corruption was created by breaking, and the guardrail
this roadmap put on any id-allocating merge: record source id, target id, and the
publisher id justifying each. `--mapping-out` writes exactly that, and the run
refuses to write anything without it.

A dev row whose player has no prod `players` row gets that player inserted first,
carrying its espn_id, so the stats row has a real owner rather than a dangling
`player_id`. Those inserts are the only new ids this script allocates and every
one is listed in the mapping artifact.

Back up first, and back up INTO `backend/data/`
-----------------------------------------------
    venv/bin/python -c "import sqlite3; sqlite3.connect('data/picks.db').execute(
        \"VACUUM INTO 'data/picks.db.pre-mls-promotion-<stamp>'\")"

`VACUUM INTO`, never `cp` — a plain copy races live writers. And the destination
must be `backend/data/`: both `.gitignore` and `backend/.dockerignore` exclude
backups by matching `data/picks.db*`, anchored to that directory. A backup written
anywhere else is caught by neither. That miss has now cost a 7.45GB image
(2026-08-04), 0.93GB of context (2026-08-11), and a 236MB file sitting untracked
in `backend/backups/` (2026-08-17, this script's first run).

Usage
-----
    venv/bin/python promote_mls_player_stats.py --check
    venv/bin/python promote_mls_player_stats.py --apply --mapping-out ops/mls-promotion-2026-08-17.json
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone

LEAGUE = "mls"
DEFAULT_SOURCE = "data/picks.dev.db"
DEFAULT_TARGET = "data/picks.db"


def _connect(path: str, readonly: bool) -> sqlite3.Connection:
    if readonly:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    else:
        con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def _stats_columns(con: sqlite3.Connection) -> list[str]:
    return [d[1] for d in con.execute("PRAGMA table_info(player_stats)")]


def plan(src: sqlite3.Connection, dst: sqlite3.Connection) -> dict:
    """Everything the run would do, computed before anything is written."""
    dst_by_espn = {
        row["espn_id"]: row["id"]
        for row in dst.execute(
            "SELECT id, espn_id FROM players WHERE league=? AND espn_id IS NOT NULL",
            (LEAGUE,),
        )
    }
    dst_owned = {
        row["player_id"]
        for row in dst.execute(
            "SELECT player_id FROM player_stats WHERE league=?", (LEAGUE,)
        )
    }

    shared = [c for c in _stats_columns(src) if c in set(_stats_columns(dst)) and c != "id"]

    to_update, to_insert, new_players, unresolvable = [], [], [], []
    for row in src.execute(
        """SELECT ps.*, p.espn_id AS _espn_id, p.name AS _p_name, p.team AS _p_team,
                  p.position AS _p_position, p.position_group AS _p_position_group,
                  p.active AS _p_active, p.entity_type AS _p_entity_type
           FROM player_stats ps
           JOIN players p ON p.id = ps.player_id AND p.league = ps.league
           WHERE ps.league = ?""",
        (LEAGUE,),
    ):
        espn_id = row["_espn_id"]
        if not espn_id:
            # No publisher id means no key we are willing to join on. Refused
            # rather than matched by name — that is the defect this guards.
            unresolvable.append({"src_player_id": row["player_id"], "name": row["player_name"],
                                 "reason": "no espn_id on the source players row"})
            continue
        target_id = dst_by_espn.get(espn_id)
        record = {
            "espn_id": espn_id,
            "src_player_id": row["player_id"],
            "name": row["player_name"],
            "values": {c: row[c] for c in shared if c != "player_id"},
        }
        if target_id is None:
            record["new_player"] = {
                "name": row["_p_name"], "team": row["_p_team"], "league": LEAGUE,
                "espn_id": espn_id, "position": row["_p_position"],
                "position_group": row["_p_position_group"],
                "active": row["_p_active"], "entity_type": row["_p_entity_type"],
            }
            new_players.append(record)
        else:
            record["dst_player_id"] = target_id
            (to_update if target_id in dst_owned else to_insert).append(record)

    return {
        "league": LEAGUE,
        "source_rows": sum(1 for _ in src.execute(
            "SELECT 1 FROM player_stats WHERE league=?", (LEAGUE,))),
        "target_rows_before": sum(1 for _ in dst.execute(
            "SELECT 1 FROM player_stats WHERE league=?", (LEAGUE,))),
        "update": to_update,
        "insert": to_insert,
        "new_players": new_players,
        "unresolvable": unresolvable,
    }


def apply(dst: sqlite3.Connection, computed: dict) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    allocated = []

    for rec in computed["new_players"]:
        np = rec["new_player"]
        cur = dst.execute(
            """INSERT INTO players(name, team, league, espn_id, position,
                                   position_group, active, entity_type, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)
               ON CONFLICT(espn_id, league) DO NOTHING""",
            (np["name"], np["team"], np["league"], np["espn_id"], np["position"],
             np["position_group"], np["active"], np["entity_type"], now),
        )
        target = dst.execute(
            "SELECT id FROM players WHERE league=? AND espn_id=?",
            (LEAGUE, np["espn_id"]),
        ).fetchone()
        rec["dst_player_id"] = target["id"]
        allocated.append({"espn_id": np["espn_id"], "dst_player_id": target["id"],
                          "name": np["name"], "inserted": cur.rowcount == 1})

    written = 0
    for rec in computed["new_players"] + computed["insert"] + computed["update"]:
        values = dict(rec["values"])
        values["player_id"] = rec["dst_player_id"]
        cols = list(values)
        placeholders = ",".join("?" * len(cols))
        updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "player_id")
        dst.execute(
            f"""INSERT INTO player_stats({",".join(cols)}) VALUES({placeholders})
                ON CONFLICT(player_id, league, season, stat_type)
                DO UPDATE SET {updates}""",
            [values[c] for c in cols],
        )
        written += 1

    dst.commit()
    return {"rows_written": written, "players_allocated": allocated}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=DEFAULT_SOURCE)
    ap.add_argument("--target", default=DEFAULT_TARGET)
    ap.add_argument("--check", action="store_true", help="measure and print, write nothing")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--mapping-out", default="",
                    help="where to write the id mapping; required with --apply")
    args = ap.parse_args()

    if args.apply and not args.mapping_out:
        print("refusing to apply without --mapping-out: an id-allocating merge that does "
              "not record its mapping forces the next pass to re-derive it from names")
        return 2
    if not args.apply and not args.check:
        args.check = True

    with closing(_connect(args.source, True)) as src, \
            closing(_connect(args.target, not args.apply)) as dst:
        computed = plan(src, dst)
        print(f"{LEAGUE}: source={computed['source_rows']} rows, "
              f"target={computed['target_rows_before']} rows")
        print(f"  update existing owner : {len(computed['update'])}")
        print(f"  insert for known player: {len(computed['insert'])}")
        print(f"  insert + new player   : {len(computed['new_players'])}")
        print(f"  unresolvable (no espn_id): {len(computed['unresolvable'])}")
        for u in computed["unresolvable"][:5]:
            print(f"     refused: {u['name']} ({u['reason']})")

        if not args.apply:
            return 0

        result = apply(dst, computed)
        after = dst.execute(
            "SELECT COUNT(*) AS n FROM player_stats WHERE league=?", (LEAGUE,)
        ).fetchone()["n"]
        print(f"  wrote {result['rows_written']} rows; target now {after}")

        os.makedirs(os.path.dirname(args.mapping_out) or ".", exist_ok=True)
        with open(args.mapping_out, "w") as fh:
            json.dump({
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "league": LEAGUE,
                "source": args.source,
                "target": args.target,
                "joined_on": "players.espn_id",
                "target_rows_before": computed["target_rows_before"],
                "target_rows_after": after,
                "players_allocated": result["players_allocated"],
                "mapping": [
                    {"espn_id": r["espn_id"], "src_player_id": r["src_player_id"],
                     "dst_player_id": r["dst_player_id"], "name": r["name"]}
                    for r in computed["new_players"] + computed["insert"] + computed["update"]
                ],
                "unresolvable": computed["unresolvable"],
            }, fh, indent=2)
        print(f"  mapping written to {args.mapping_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
