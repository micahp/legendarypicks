"""The oracle answers from stored rows only: next slate, projection status, last sim run, and unknowns as None."""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oracle  # noqa: E402

SCHEMA = """
CREATE TABLE nfl_schedule (game_id TEXT, season INTEGER, game_type TEXT, week INTEGER, gameday TEXT, gametime TEXT,
    away_team TEXT, home_team TEXT, home_score INTEGER, source TEXT, ingested_at TEXT, first_observed TEXT);
CREATE TABLE nfl_schedule_versions (game_id TEXT, observed_at TEXT, content_sha256 TEXT);
CREATE TABLE nfl_line_snapshots (snapshot_id INTEGER PRIMARY KEY, league TEXT, game_id TEXT, source TEXT,
    captured_at TEXT, spread_line REAL, total_line REAL);
CREATE TABLE game_projections (run_id TEXT, league TEXT, game_id TEXT, season INTEGER, week INTEGER, locked INTEGER,
    locked_at TEXT);
CREATE TABLE model_runs (run_id TEXT, league TEXT, season INTEGER, week INTEGER, model TEXT, model_version TEXT,
    started_at TEXT, finished_at TEXT, status TEXT);
"""


def make_db(path, schedule=(), projections=(), lines=(), runs=()):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.executemany('INSERT INTO nfl_schedule VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', schedule)
    conn.executemany('INSERT INTO game_projections (run_id, league, game_id, season, week, locked, locked_at) '
                     'VALUES (?,?,?,?,?,?,?)', projections)
    conn.executemany('INSERT INTO nfl_line_snapshots (league, game_id, source, captured_at, spread_line, total_line) '
                     'VALUES (?,?,?,?,?,?)', lines)
    conn.executemany('INSERT INTO model_runs VALUES (?,?,?,?,?,?,?,?,?)', runs)
    conn.commit()
    conn.close()
    return str(path)


def game(game_id, season, week, gameday, home_score=None, away='AAA', home='BBB'):
    return (game_id, season, 'REG', week, gameday, '13:00', away, home, home_score, 'nflverse_games', None, None)


@pytest.fixture
def season_db(tmp_path):
    schedule = [game('2026_10_AAA_BBB', 2026, 10, '2026-11-12', home_score=20),
                game('2026_11_CCC_DDD', 2026, 11, '2026-11-22', away='CCC', home='DDD'),
                game('2026_11_EEE_FFF', 2026, 11, '2026-11-19', away='EEE', home='FFF')]
    return make_db(tmp_path / 'picks.db', schedule=schedule)


def test_next_slate_is_the_week_of_the_first_unplayed_game_on_or_after_today(season_db):
    slate, stale = oracle.next_slate(oracle.connect(season_db), '2026-11-17')
    assert (slate['season'], slate['week']) == (2026, 11)
    assert stale == []


def test_an_unplayed_game_dated_before_today_is_a_warning_not_the_next_slate(tmp_path):
    schedule = [game('2026_10_AAA_BBB', 2026, 10, '2026-11-12'),
                game('2026_11_EEE_FFF', 2026, 11, '2026-11-19', away='EEE', home='FFF')]
    path = make_db(tmp_path / 'picks.db', schedule=schedule)
    answer = oracle.build_answer(path, '2026-11-17', store=str(tmp_path / 'no-store'))
    assert answer['next_slate']['week'] == 11
    assert answer['warnings'] == ['unplayed game dated before today: 2026_10_AAA_BBB (2026-11-12)']


def test_projection_status_is_none_preview_or_locked(tmp_path):
    schedule = [game('2026_11_EEE_FFF', 2026, 11, '2026-11-19', away='EEE', home='FFF'),
                game('2026_11_CCC_DDD', 2026, 11, '2026-11-22', away='CCC', home='DDD'),
                game('2026_11_GGG_HHH', 2026, 11, '2026-11-22', away='GGG', home='HHH')]
    projections = [('preview-run', 'nfl', '2026_11_EEE_FFF', 2026, 11, 0, None),
                   ('locked-run', 'nfl', '2026_11_CCC_DDD', 2026, 11, 1, '2026-11-18T12:00:00Z')]
    path = make_db(tmp_path / 'picks.db', schedule=schedule, projections=projections)
    detail = {g['game_id']: g for g in oracle.build_answer(path, '2026-11-17',
                                                           store=str(tmp_path / 'no-store'))['next_slate']['games_detail']}
    assert detail['2026_11_EEE_FFF']['projections']['status'] == 'preview'
    assert detail['2026_11_CCC_DDD']['projections']['status'] == 'locked'
    assert detail['2026_11_GGG_HHH']['projections']['status'] == 'none'


def test_a_missing_line_is_none_not_a_guess(tmp_path):
    schedule = [game('2026_11_EEE_FFF', 2026, 11, '2026-11-19', away='EEE', home='FFF')]
    path = make_db(tmp_path / 'picks.db', schedule=schedule)
    answer = oracle.build_answer(path, '2026-11-17', store=str(tmp_path / 'no-store'))
    assert answer['next_slate']['first_game']['line'] is None
    assert answer['next_slate']['first_game']['schedule_first_observed'] is None


def test_the_last_sim_run_is_the_newest_entry_of_any_week():
    entries = [{'run_id': 'old', 'season': 2026, 'week': 8, 'game_id': 'A', 'created_at_utc': '2026-10-27T18:00:00Z'},
               {'run_id': 'new', 'season': 2026, 'week': 10, 'game_id': 'B', 'created_at_utc': '2026-11-10T09:00:00Z'}]
    assert oracle.last_sim_run(entries)['run_id'] == 'new'
    assert oracle.last_sim_run([]) is None
    assert [r['run_id'] for r in oracle.slate_sim_runs(entries, 2026, 8)] == ['old']


def test_the_database_is_opened_read_only(season_db):
    conn = oracle.connect(season_db)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM nfl_schedule")
    conn.close()


def test_no_unplayed_game_on_or_after_today_says_so(tmp_path):
    path = make_db(tmp_path / 'picks.db', schedule=[game('2026_10_AAA_BBB', 2026, 10, '2026-11-12', home_score=20)])
    answer = oracle.build_answer(path, '2026-11-17', store=str(tmp_path / 'no-store'))
    assert answer['next_slate'] is None
    assert 'no unplayed NFL game' in oracle.render_text(answer)
