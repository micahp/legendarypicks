"""Opt-in isolated demo store. Never opens an application database."""
from contextlib import closing
import hashlib
from datetime import timezone
import json
from pathlib import Path
import sqlite3

from postgame_story_audit import audit, timestamp
from postgame_rubric import grade_postgame

DEMO_DIR = (Path(__file__).resolve().parents[1] / 'docs/research/postgame-content-demo-2026-11-10').resolve()


def save_generation(path, bundle, recap):
    """Append a unique accepted generation and advance its pointer atomically.

    Refuse destinations outside /tmp and this research directory. No store is
    created by fixture replay; callers must explicitly opt in to this function.
    """
    path = Path(path).resolve()
    if not (Path('/tmp') in path.parents or DEMO_DIR in path.parents):
        raise ValueError('postgame demo store must be in /tmp or its research directory')
    canonical = json.dumps(bundle, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    checks = audit(bundle, recap)
    if not all(checks.values()) or recap.get('input_sha256') != digest or recap.get('gate') not in ('eligible', 'eligible_score_only'):
        return None
    result = {**recap, 'audit': checks}
    grade = grade_postgame(bundle, result)
    if grade['status'] not in ('eligible', 'eligible_score_only'):
        return None
    game = bundle['game']
    with closing(sqlite3.connect(path)) as c, c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS game_story_postgame_history(
          id INTEGER PRIMARY KEY, league TEXT NOT NULL, game_id TEXT NOT NULL,
          input_sha256 TEXT NOT NULL, renderer_version TEXT NOT NULL,
          as_of_utc TEXT NOT NULL, payload TEXT NOT NULL,
          UNIQUE(league,game_id,input_sha256,renderer_version));
        CREATE TABLE IF NOT EXISTS game_story_postgame_current(
          league TEXT NOT NULL, game_id TEXT NOT NULL, history_id INTEGER NOT NULL,
          PRIMARY KEY(league,game_id), FOREIGN KEY(history_id) REFERENCES game_story_postgame_history(id));
        CREATE TRIGGER IF NOT EXISTS postgame_history_no_update BEFORE UPDATE ON game_story_postgame_history BEGIN SELECT RAISE(ABORT,'append only'); END;
        CREATE TRIGGER IF NOT EXISTS postgame_history_no_delete BEFORE DELETE ON game_story_postgame_history BEGIN SELECT RAISE(ABORT,'append only'); END;
        ''')
        payload = json.dumps({'recap': result, 'rubric': grade, 'sources': bundle.get('sources', [])}, sort_keys=True, ensure_ascii=False)
        c.execute('INSERT OR IGNORE INTO game_story_postgame_history(league,game_id,input_sha256,renderer_version,as_of_utc,payload) VALUES(?,?,?,?,?,?)',
                  (game['league'], game['game_id'], digest, recap['engine_version'], timestamp(bundle['as_of_utc']).astimezone(timezone.utc).isoformat(), payload))
        row = c.execute('SELECT id FROM game_story_postgame_history WHERE league=? AND game_id=? AND input_sha256=? AND renderer_version=?',
                        (game['league'], game['game_id'], digest, recap['engine_version'])).fetchone()
        # Never make a later capture disappear when an older fixture is replayed.
        c.execute('''INSERT INTO game_story_postgame_current(league,game_id,history_id) VALUES(?,?,?)
          ON CONFLICT(league,game_id) DO UPDATE SET history_id=excluded.history_id
          WHERE (SELECT as_of_utc FROM game_story_postgame_history WHERE id=excluded.history_id) >=
                (SELECT as_of_utc FROM game_story_postgame_history WHERE id=game_story_postgame_current.history_id)''',
                  (game['league'], game['game_id'], row[0]))
        return row[0]
