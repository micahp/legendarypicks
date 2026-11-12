#!/usr/bin/env python3
"""Build once, then read historical E1 outcome classifications without running classify().

The SQLite artifact stores original E1 source rows and four classification variants
(qb_scrambles on/off x separate_sack_fumbles on/off). Its source and classifier
identities are verified before any historical sampling pool is loaded.

A full build is performed outside simulation startup. For incremental ingestion,
refresh a known changed game explicitly, under a verified game-only source update.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import itertools
import json
import os
from pathlib import Path
import sqlite3
import sys

import e0_single_play as e0
import e1_drive as e1
import reference_build_cache

SCHEMA = 'lp.nfl.preclassified-e1-history.v1'
VARIANTS = tuple((scrambles, sacks) for scrambles in (False, True) for sacks in (False, True))
COLUMNS = ', '.join(e1.COLUMNS)


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def _classifier_identity():
    return {Path(path).name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
            for path in (e1.__file__, e0.__file__, __file__)}


def _source_identity(db):
    return reference_build_cache.database_identity(db)


def _open_source(db, game_id=None):
    con = sqlite3.connect(f'file:{Path(db).resolve()}?mode=ro', uri=True, timeout=10)
    try:
        condition = 'AND game_id = ?' if game_id is not None else ''
        params = (game_id,) if game_id is not None else ()
        cursor = con.execute(
            f'SELECT {COLUMNS} FROM nfl_pbp WHERE season >= {min(e1.POOL_SEASONS)} '
            f'AND week <= 18 {condition} ORDER BY game_id, play_id', params)
        for row in cursor:
            yield dict(zip(e1.COLUMNS, row))
    finally:
        con.close()


def _classified_game(rows):
    for index, row in enumerate(rows):
        nxt = rows[index + 1] if index + 1 < len(rows) else None
        variants = {}
        for scrambles, sack_fumbles in VARIANTS:
            counts = Counter()
            hit = e1.classify(row, nxt, counts, include_qb_scrambles=scrambles,
                              separate_sack_fumbles=sack_fumbles)
            key = f'{int(scrambles)}{int(sack_fumbles)}'
            variants[key] = {'hit': hit, 'excluded': dict(counts)}
        yield (row['game_id'], int(row['play_id']), int(row['season']), int(row['week']),
               _encode(row), _encode(variants))


def _insert_games(target, source):
    count = 0
    games = 0
    for _game_id, group in itertools.groupby(source, key=lambda r: r['game_id']):
        records = list(_classified_game(list(group)))
        target.executemany('INSERT INTO classified VALUES (?,?,?,?,?,?)', records)
        count += len(records)
        games += 1
    return {'rows': count, 'games': games}


def _meta_get(con):
    return {name: json.loads(value) for name, value in con.execute('SELECT name,value FROM metadata')}


def _meta_put(con, name, value):
    con.execute('INSERT OR REPLACE INTO metadata (name,value) VALUES (?,?)', (name, _encode(value)))


def _initialize(con):
    con.executescript("""
        CREATE TABLE classified (
            game_id TEXT NOT NULL, play_id INTEGER NOT NULL,
            season INTEGER NOT NULL, week INTEGER NOT NULL,
            row_json TEXT NOT NULL, classification_json TEXT NOT NULL,
            PRIMARY KEY (game_id, play_id)
        );
        CREATE INDEX classified_cutoff ON classified(season, week, game_id, play_id);
        CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL);
    """)


def build(db, out, *, replace=False):
    """Cold preprocessing only. Atomically replace a complete artifact."""
    out = Path(out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and not replace:
        raise FileExistsError(f'{out}: already exists; use --replace for a complete rebuild')
    temp = out.with_name(f'{out.name}.{os.getpid()}.partial')
    if temp.exists():
        raise FileExistsError(temp)
    before = _source_identity(db)
    try:
        with sqlite3.connect(temp) as con:
            _initialize(con)
            stats = _insert_games(con, _open_source(db))
            if _source_identity(db) != before:
                raise RuntimeError('source database changed during preprocessing; discard artifact')
            _meta_put(con, 'schema', SCHEMA)
            _meta_put(con, 'source_identity', before)
            _meta_put(con, 'classifier_identity', _classifier_identity())
            _meta_put(con, 'counts', stats)
            _meta_put(con, 'incremental_game_updates', [])
            con.commit()
        os.chmod(temp, 0o600)
        os.replace(temp, out)
    finally:
        if temp.exists():
            temp.unlink()
    return stats


def refresh_game(db, out, game_id, *, only_this_game_changed=False):
    """Refresh one ingested game; caller must attest no other source games changed."""
    if not only_this_game_changed:
        raise ValueError('explicit --only-this-game-changed is required for incremental refresh')
    out = Path(out).expanduser().resolve(strict=True)
    before = _source_identity(db)
    with sqlite3.connect(out) as con:
        metadata = _meta_get(con)
        if metadata.get('schema') != SCHEMA or metadata.get('classifier_identity') != _classifier_identity():
            raise ValueError('materialization schema/classifier mismatch; rebuild the complete artifact')
        # Do not mark the entire DB verified until the caller confirms this game
        # is the only source change. The normal load also checks the metadata.
        records = list(_classified_game(list(_open_source(db, game_id))))
        if not records:
            raise ValueError(f'no regular-season source rows found for {game_id}')
        if _source_identity(db) != before:
            raise RuntimeError('source database changed during incremental classification')
        con.execute('DELETE FROM classified WHERE game_id = ?', (game_id,))
        con.executemany('INSERT INTO classified VALUES (?,?,?,?,?,?)', records)
        _meta_put(con, 'source_identity', before)
        updates = metadata.get('incremental_game_updates', [])
        _meta_put(con, 'incremental_game_updates', updates + [game_id])
        # Updated counts remain accurate even when a game gains/loses plays.
        _meta_put(con, 'counts', {
            'rows': con.execute('SELECT COUNT(*) FROM classified').fetchone()[0],
            'games': con.execute('SELECT COUNT(DISTINCT game_id) FROM classified').fetchone()[0],
        })
        con.commit()
    return {'game_id': game_id, 'rows': len(records)}


def load_pools(db, artifact, *, eligible_before=None, regulation_only=False,
               include_qb_scrambles=False, team_before_season=None,
               known_clean_penalties=False, separate_sack_fumbles=False):
    """Reproduce e1.build_pools() from preclassified rows, never invoking e1.classify."""
    if eligible_before is not None:
        season, week = (int(v) for v in eligible_before)
        e1.holdout.refuse_unless_cutoff(season, 'pool cutoff', eligible_before)
        if season < min(e1.POOL_SEASONS) or not 1 <= week <= 18:
            raise ValueError('dynamic pool cutoff must be week 1-18 of 2022 or later')
    con = sqlite3.connect(f'file:{Path(artifact).expanduser().resolve(strict=True)}?mode=ro',
                          uri=True, timeout=10)
    try:
        metadata = _meta_get(con)
        if metadata.get('schema') != SCHEMA:
            raise ValueError('unknown historical classification schema; rebuild materialization')
        if _encode(metadata.get('classifier_identity')) != _encode(_classifier_identity()):
            raise ValueError('historical classifier source changed; rebuild materialization')
        if _encode(metadata.get('source_identity')) != _encode(_source_identity(db)):
            raise ValueError('historical source DB changed; refresh affected games or rebuild materialization')
        if eligible_before is None:
            clause = 'season IN (' + ','.join('?' for _ in e1.POOL_SEASONS) + ')'
            params = tuple(e1.POOL_SEASONS)
        else:
            clause = 'season >= ? AND (season < ? OR (season = ? AND week < ?))'
            params = (min(e1.POOL_SEASONS), season, season, week)
        cursor = con.execute(
            f'SELECT row_json,classification_json FROM classified WHERE {clause} '
            'AND week <= 18 ORDER BY game_id,play_id', params)
        rows, pool, excluded = [], {}, Counter()
        team_pool = {} if team_before_season is not None else None
        variant = f'{int(include_qb_scrambles)}{int(separate_sack_fumbles)}'
        team_variant = f'0{int(separate_sack_fumbles)}'
        for raw, precomputed in cursor:
            row, variants = json.loads(raw), json.loads(precomputed)
            rows.append(row)
            overtime = row['qtr'] is None or int(row['qtr']) > 4
            if regulation_only and overtime:
                excluded['overtime rows (regulation-only pool)'] += 1
            in_main = not (regulation_only and overtime)
            in_team = team_pool is not None and int(row['season']) < team_before_season
            if not (in_main or in_team):
                continue
            if known_clean_penalties and row.get('penalty') != 0:
                reason = ('known penalty row excluded (strict clean pool)' if row.get('penalty') == 1
                          else 'unknown or unrecognized penalty status excluded (strict clean pool)')
                excluded[reason] += 1
                continue
            if row['play_type'] not in e1.PLAY_TYPES or row['down'] is None or not 1 <= row['down'] <= 4:
                if in_main:
                    excluded['unsupported play type or invalid down'] += 1
                continue
            key = e0.pool_key(int(row['down']), row['ydstogo'], row['yardline_100'])
            if in_main:
                selected = variants[variant]
                excluded.update(selected['excluded'])
                hit = selected['hit']
                if hit is not None:
                    pool.setdefault(key, []).append((hit[0], row, hit[1], hit[2]))
            if in_team:
                team_hit = variants[team_variant]['hit']
                if team_hit is not None:
                    team_pool.setdefault(key, []).append((team_hit[0], row, team_hit[1], team_hit[2]))
        return rows, pool, excluded, team_pool
    finally:
        con.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('build', 'refresh-game', 'inspect'))
    parser.add_argument('--db', default=e1.DEFAULT_DB)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--replace', action='store_true')
    parser.add_argument('--game-id')
    parser.add_argument('--only-this-game-changed', action='store_true')
    args = parser.parse_args(argv)
    if args.action == 'build':
        stats = build(args.db, args.out, replace=args.replace)
    elif args.action == 'refresh-game':
        if not args.game_id:
            parser.error('--game-id is required for refresh-game')
        stats = refresh_game(args.db, args.out, args.game_id,
                             only_this_game_changed=args.only_this_game_changed)
    else:
        with sqlite3.connect(args.out) as con:
            stats = _meta_get(con)
    print(json.dumps(stats, sort_keys=True))


if __name__ == '__main__':
    main()
