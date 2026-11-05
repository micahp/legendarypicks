#!/usr/bin/env python3
"""Link NFL players to RotoWire ids through native ids, and record every decision.

A player's espn_id and nfl_gsis_id are looked up in Sleeper's public identity file, which carries the RotoWire id for
each player. Names are never used. A player is linked only when every native id that resolves points to one RotoWire
id, that id is not claimed by any other player, and the player has no different RotoWire id already stored. Every other
outcome is recorded and not written:

- link: written to player_source_ids (source rotowire, league nfl).
- already_linked: the same link is already stored.
- conflict: native ids disagree, an id is claimed by two players, or a different id is already stored.
- unresolved: no native id on the player, or none of them is in the Sleeper file.

Dry run by default. --apply writes the links and the decision log. The decision log is the audit trail.
"""
from __future__ import annotations

import argparse
import collections
import sqlite3
import sys
from datetime import datetime, timezone

import nfl_news

SOURCE = nfl_news.ROTOWIRE_SOURCE
LEAGUE = 'nfl'

DECISIONS_DDL = """CREATE TABLE IF NOT EXISTS nfl_rotowire_id_decisions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_at_utc TEXT NOT NULL,
  applied INTEGER NOT NULL,
  player_id INTEGER,
  rotowire_id TEXT,
  outcome TEXT NOT NULL,
  detail TEXT)"""


def decide(players, sleeper, stored):
    """Return one decision per player with a native id. Pure: reads its inputs, writes nothing.

    players: iterable of (id, espn_id, nfl_gsis_id). sleeper: parse_sleeper_crosswalk()['by_espn'/'by_gsis'] maps.
    stored: {player_id: set of RotoWire ids already in player_source_ids for league nfl}.
    Returns (decisions, no_native_count) where decisions is a list of dicts.
    """
    by_espn, by_gsis = sleeper['by_espn'], sleeper['by_gsis']
    pending = {}
    holders = collections.defaultdict(set)
    decisions = []
    no_native = 0
    for player_id, espn, gsis in players:
        espn = str(espn or '').strip()
        gsis = str(gsis or '').strip()
        if not espn and not gsis:
            no_native += 1
            continue
        hits = [found for found in (by_espn.get(espn, set()) if espn else set(),
                                    by_gsis.get(gsis, set()) if gsis else set()) if found]
        if not hits:
            decisions.append(_decision(player_id, None, 'unresolved', 'native id not in Sleeper file'))
            continue
        combined = set().union(*hits)
        if len(combined) != 1 or any(found != combined for found in hits):
            decisions.append(_decision(player_id, None, 'conflict',
                                       f"native ids point to {sorted(combined)}"))
            continue
        rotowire_id = next(iter(combined))
        pending[player_id] = rotowire_id
        holders[rotowire_id].add(player_id)

    for player_id, rotowire_id in pending.items():
        others = sorted(holders[rotowire_id] - {player_id})
        if others:
            decisions.append(_decision(player_id, rotowire_id, 'conflict',
                                       f'rotowire id also resolves for players {others}'))
            continue
        claimed_elsewhere = sorted(other for other, keys in stored.items()
                                   if rotowire_id in keys and other != player_id)
        if claimed_elsewhere:
            decisions.append(_decision(player_id, rotowire_id, 'conflict',
                                       f'rotowire id already stored for players {claimed_elsewhere}'))
            continue
        held = stored.get(player_id, set())
        if rotowire_id in held:
            decisions.append(_decision(player_id, rotowire_id, 'already_linked', ''))
        elif held:
            decisions.append(_decision(player_id, rotowire_id, 'conflict',
                                       f'player already stored under {sorted(held)}'))
        else:
            decisions.append(_decision(player_id, rotowire_id, 'link', ''))
    return decisions, no_native


def _decision(player_id, rotowire_id, outcome, detail):
    return {'player_id': player_id, 'rotowire_id': rotowire_id, 'outcome': outcome, 'detail': detail}


def _stored_links(con):
    stored = collections.defaultdict(set)
    for player_id, key in con.execute(
            'SELECT player_id, source_player_key FROM player_source_ids WHERE source=? AND league=?',
            (SOURCE, LEAGUE)):
        stored[int(player_id)].add(str(key).strip())
    return stored


def run(con, sleeper, apply, now=None):
    now = now or datetime.now(timezone.utc).isoformat()
    players = con.execute('SELECT id, espn_id, nfl_gsis_id FROM players WHERE league=?', (LEAGUE,)).fetchall()
    decisions, no_native = decide(((row[0], row[1], row[2]) for row in players), sleeper, _stored_links(con))
    counts = collections.Counter(d['outcome'] for d in decisions)
    if apply:
        con.execute(DECISIONS_DDL)
        with con:
            for d in decisions:
                con.execute('INSERT INTO nfl_rotowire_id_decisions(run_at_utc, applied, player_id, rotowire_id, outcome, '
                            'detail) VALUES (?,?,?,?,?,?)',
                            (now, 1, d['player_id'], d['rotowire_id'], d['outcome'], d['detail']))
                if d['outcome'] == 'link':
                    con.execute('INSERT INTO player_source_ids(source, league, source_player_key, player_id, first_seen, '
                                'last_seen) VALUES (?,?,?,?,?,?)',
                                (SOURCE, LEAGUE, d['rotowire_id'], d['player_id'], now, now))
    return {'players_with_native_id': len(players) - no_native, 'no_native_id': no_native, 'counts': dict(counts),
            'decisions': decisions}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--db', required=True, help='SQLite database (always named explicitly)')
    ap.add_argument('--apply', action='store_true', help='write the links and the decision log (default: dry run)')
    a = ap.parse_args(argv)

    result = nfl_news.load_sleeper_crosswalk()
    crosswalk = result.get('crosswalk') if result else None
    if not crosswalk:
        print(f"ID backfill refused, nothing written: Sleeper crosswalk unavailable ({result.get('status') if result else 'no result'})",
              file=sys.stderr)
        return 1
    # A dry run opens the database read-only, so it cannot create anything.
    uri = f'file:{a.db}' + ('' if a.apply else '?mode=ro')
    con = sqlite3.connect(uri, uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        summary = run(con, crosswalk, apply=a.apply)
    except sqlite3.Error as exc:
        print(f'ID backfill: database error, nothing written: {exc}', file=sys.stderr)
        return 1
    finally:
        con.close()
    c = summary['counts']
    mode = 'applied' if a.apply else 'dry run, nothing written'
    print(f"NFL RotoWire ID backfill ({mode}): {summary['players_with_native_id']} NFL players with a native id; "
          f"link {c.get('link', 0)}, already linked {c.get('already_linked', 0)}, conflicts {c.get('conflict', 0)}, "
          f"unresolved {c.get('unresolved', 0)}; without any native id {summary['no_native_id']} (not decided)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
