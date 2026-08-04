#!/usr/bin/env python3
"""Fill the NHL log keys the boxscore publishes and the game-log endpoint does not.

`B/position-content[D]` fails because 500 sampled defenceman logs never record
`blockedShots` or `hits` -- the two things a defenceman is actually measured on.
That is not an acquisition gap. `ingest_nhl_logs.py` reads

    api-web.nhle.com/v1/player/{id}/game-log/{season}/{type}

which publishes ten skater keys and none of those. The SAME publisher's boxscore

    api-web.nhle.com/v1/gamecenter/{gameId}/boxscore

carries `blockedShots`, `hits`, `takeaways`, `giveaways` and `sog` for every
skater in the game, and for goalies `saves`, `shotsAgainst`, `goalsAgainst` and
the strength splits. Verified on game 2025030416 on 2026-08-04. It has been
published all along; nobody read it. That makes this the fifth surfacing gap of
the day, after NFL touchdowns, MLB counting stats, NBA 2026 and MLB team/position.

Two wins in one pass. `ingest_nhl_logs.py` computes `saves` as
`shotsAgainst - goalsAgainst` and marks it INTERIM in a comment, noting that a
game can have more than one goalie -- which is exactly where a derivation earns
its mistakes. The boxscore publishes `saves` directly, so the derived value is
replaced by the published one rather than corroborated by it.

Cost: one request per GAME rather than one per player per game type. A season is
1,394 games against the 1,748 requests that produced the same rows, and each
request enriches every player who appeared. Paced, budgeted and disk-cached, so a
refusal costs nothing to resume.

    ./venv/bin/python backfill_nhl_boxscore_stats.py --db data/picks.dev.db --season 2026
    ./venv/bin/python backfill_nhl_boxscore_stats.py --db data/picks.dev.db --season 2026 --apply
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# The pacing, per-host budget and disk cache live in espn_client. The name is
# about where they were first needed, not what they can address -- every one of
# them keys on the URL's host, so pointing them at api-web.nhle.com is correct.
# Five ingests have each written their own copy of this; importing is how that
# stops at five. Consolidating the other four is follow-up, not this change.
import espn_client as paced


BOXSCORE = "https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore"

# Published by the boxscore, absent from the game-log endpoint. `sog` is here
# because the game-log calls the same quantity `shots`; both are kept under their
# own published names rather than one being renamed into the other, so a reader
# can always tell which endpoint a number came from.
SKATER_KEYS = ("blockedShots", "hits", "takeaways", "giveaways", "sog", "shifts")

# `saves` is the point of this list. The log ingest derives it by subtraction and
# says so; here it is read.
GOALIE_KEYS = ("saves", "shotsAgainst", "goalsAgainst", "toi", "starter",
               "evenStrengthShotsAgainst", "powerPlayShotsAgainst",
               "shorthandedShotsAgainst")


def boxscore_stats(game_id: str) -> dict:
    """{playerId: {published key: value}} for every player in the game."""
    doc = paced._get(BOXSCORE.format(game_id=game_id), ttl=86400 * 30)
    out = {}
    by_game = doc.get("playerByGameStats") or {}
    for side in ("homeTeam", "awayTeam"):
        team = by_game.get(side) or {}
        for group in ("forwards", "defense", "goalies"):
            keys = GOALIE_KEYS if group == "goalies" else SKATER_KEYS
            for player in team.get(group) or []:
                pid = player.get("playerId")
                if pid is None:
                    continue
                out[str(pid)] = {
                    k: player[k] for k in keys
                    if player.get(k) is not None
                }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("LP_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"))
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="first N games only")
    args = ap.parse_args()

    # The 100-per-host budget is a measured ESPN figure and there is no evidence
    # it applies here -- `ingest_nhl_logs.py` has been making ~1,748 unpaced
    # requests to this host without being refused. Applying it anyway would add
    # fourteen 60s cooldowns to a 1,394-game run for a limit nobody has observed.
    # Pace at the interval `ingest_nhl_season_stats.py` already uses for nhle.com
    # and leave the budget to the host it was measured on.
    paced._HOST_BUDGET = int(os.environ.get("LP_NHL_HOST_BUDGET", "0"))
    paced.set_min_interval(float(os.environ.get("LP_NHL_MIN_INTERVAL", "0.5")))
    paced.set_disk_cache(os.environ.get("LP_ESPN_CACHE_DIR") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "espn-cache"),
        ttl=86400 * 30)

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    games = [r[0] for r in con.execute(
        "SELECT DISTINCT game_id FROM player_game_logs "
        "WHERE league='nhl' AND season=? AND game_id IS NOT NULL ORDER BY game_id",
        (args.season,))]
    if args.limit:
        games = games[:args.limit]
    print(f"NHL {args.season}: {len(games)} games to read"
          f"{'' if args.apply else '  (DRY RUN)'}")

    updated = unmatched = no_new = 0
    added_keys = collections.Counter()
    failures = []
    for i, game_id in enumerate(games, 1):
        try:
            published = boxscore_stats(game_id)
        except Exception as exc:
            # A game we cannot read is a game we do not enrich. It is recorded
            # and skipped rather than aborting: this is an enrichment job, and
            # failing 1,394 games over one refusal is the exact mistake
            # roster_sync made.
            failures.append((game_id, str(exc)[:80]))
            continue
        rows = con.execute(
            "SELECT id, source_player_key, stats FROM player_game_logs "
            "WHERE league='nhl' AND season=? AND game_id=?",
            (args.season, game_id)).fetchall()
        for row in rows:
            extra = published.get(str(row["source_player_key"]))
            if not extra:
                unmatched += 1
                continue
            stats = json.loads(row["stats"] or "{}")
            new = {k: v for k, v in extra.items() if stats.get(k) != v}
            if not new:
                no_new += 1
                continue
            stats.update(new)
            for k in new:
                added_keys[k] += 1
            if args.apply:
                con.execute("UPDATE player_game_logs SET stats=? WHERE id=?",
                            (json.dumps(stats), row["id"]))
            updated += 1
        if args.apply and i % 50 == 0:
            con.commit()
            print(f"  {i}/{len(games)} games | {updated} rows enriched")
    if args.apply:
        con.commit()

    print(f"\nrows enriched   {updated}")
    print(f"rows unmatched  {unmatched}  (in our logs, not in the boxscore)")
    print(f"rows unchanged  {no_new}")
    print("keys filled     " + ", ".join(
        f"{k}={n}" for k, n in added_keys.most_common()))
    if failures:
        print(f"games not read  {len(failures)} -- first few: {failures[:3]}")
    if not args.apply:
        print("\nDRY RUN -- nothing written. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
