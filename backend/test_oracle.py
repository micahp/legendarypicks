"""The oracle answers from stored rows only: next slate, projection status, last sim run, and unknowns as None."""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oracle  # noqa: E402

SCHEMA = """
CREATE TABLE nfl_schedule (game_id TEXT, season INTEGER, game_type TEXT, week INTEGER, gameday TEXT, gametime TEXT,
    away_team TEXT, home_team TEXT, away_score INTEGER, home_score INTEGER, source TEXT, ingested_at TEXT,
    first_observed TEXT);
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
    conn.executemany('INSERT INTO nfl_schedule VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', schedule)
    conn.executemany('INSERT INTO game_projections (run_id, league, game_id, season, week, locked, locked_at) '
                     'VALUES (?,?,?,?,?,?,?)', projections)
    conn.executemany('INSERT INTO nfl_line_snapshots (league, game_id, source, captured_at, spread_line, total_line) '
                     'VALUES (?,?,?,?,?,?)', lines)
    conn.executemany('INSERT INTO model_runs VALUES (?,?,?,?,?,?,?,?,?)', runs)
    conn.commit()
    conn.close()
    return str(path)


def game(game_id, season, week, gameday, home_score=None, away='AAA', home='BBB'):
    away_score = None if home_score is None else home_score - 3
    return (game_id, season, 'REG', week, gameday, '13:00', away, home, away_score, home_score, 'nflverse_games',
            None, None)


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


def test_full_slate_lists_every_game_of_the_next_slate_in_kickoff_order(season_db):
    slate = oracle.full_slate(season_db, '2026-11-17')
    assert (slate['season'], slate['week'], slate['games_total'], slate['unplayed']) == (2026, 11, 2, 2)
    assert [g['game_id'] for g in slate['games']] == ['2026_11_EEE_FFF', '2026_11_CCC_DDD']


def test_full_slate_of_a_named_week_ignores_today_and_shows_scores(season_db):
    slate = oracle.full_slate(season_db, '2026-11-17', season=2026, week=10)
    assert slate['games_total'] == 1
    assert slate['games'][0]['played'] is True
    assert slate['games'][0]['home_score'] == 20


def test_full_slate_of_a_week_with_no_games_is_none(season_db):
    assert oracle.full_slate(season_db, '2026-11-17', season=2026, week=18) is None


def test_game_detail_returns_every_stored_fact_for_one_game(tmp_path):
    schedule = [game('2026_11_EEE_FFF', 2026, 11, '2026-11-19', away='EEE', home='FFF')]
    projections = [('preview-run', 'nfl', '2026_11_EEE_FFF', 2026, 11, 0, None)]
    lines = [('nfl', '2026_11_EEE_FFF', 'odds_api', '2026-11-18T12:00:00Z', -3.5, 47.5)]
    runs = [('preview-run', 'nfl', 2026, 11, 'nfl-v1', 'v1', '2026-11-17T17:00:00Z', None, 'preview')]
    path = make_db(tmp_path / 'picks.db', schedule=schedule, projections=projections, lines=lines, runs=runs)
    conn = sqlite3.connect(path)
    conn.execute('INSERT INTO nfl_schedule_versions VALUES (?,?,?)', ('2026_11_EEE_FFF', '2026-11-16 09:00:00', 'abc'))
    conn.commit()
    conn.close()
    detail = oracle.game_detail(path, '2026_11_EEE_FFF', store=str(tmp_path / 'no-store'))
    assert detail['schedule']['away_team'] == 'EEE'
    assert detail['schedule_versions'][0]['content_sha256'] == 'abc'
    assert detail['lines'][0]['spread_line'] == -3.5
    assert detail['projection_status']['status'] == 'preview'
    assert detail['projections'][0]['run_id'] == 'preview-run'
    assert detail['model_runs_for_week'][0]['model'] == 'nfl-v1'
    assert detail['sim_runs'] == []


def test_an_unknown_game_id_has_no_detail(season_db):
    assert oracle.game_detail(season_db, '2099_01_XXX_YYY', store='/nonexistent') is None


class FakeScoreboard:
    def __init__(self, events):
        self.payload = {'events': events}
        self.urls = []

    def json(self, url, ttl=None):
        self.urls.append(url)
        return self.payload


def espn_event(date, home, away):
    return {'date': date, 'competitions': [{'competitors': [
        {'homeAway': 'home', 'team': {'abbreviation': home}}, {'homeAway': 'away', 'team': {'abbreviation': away}}]}]}


TNF = {'game_id': '2026_11_IND_HOU', 'gameday': '2026-11-19', 'gametime': '20:15', 'away_team': 'IND', 'home_team': 'HOU'}


def test_scoreboard_kickoff_agrees_with_the_schedule_read_as_eastern():
    fake = FakeScoreboard([espn_event('2026-11-20T01:15Z', 'HOU', 'IND')])
    kickoff, url = oracle.scoreboard_kickoff(fake, TNF)
    assert kickoff == oracle.datetime(2026, 11, 20, 1, 15)
    assert url.endswith('/nfl/scoreboard?dates=20261119')


def test_scoreboard_kickoff_refuses_a_different_time():
    fake = FakeScoreboard([espn_event('2026-11-19T00:15Z', 'HOU', 'IND')])
    with pytest.raises(ValueError, match='differs from schedule'):
        oracle.scoreboard_kickoff(fake, TNF)


class FakeSnapUpdate:
    @staticmethod
    def load_published(raw_dir, season, players_csv=None):
        return {'schema': 'fake', 'season': season, 'team_snaps': [['HOU', 9, 0.6], ['HOU', 11, 0.7]],
                'player_snaps': [['HOU', 9, 'p1', 'WR', 40.0], ['HOU', 11, 'p1', 'WR', 41.0]],
                'active': [['HOU', 9, ['p1']], ['HOU', 11, ['p1']]], 'coverage': {'offense_rows': 2}}


def test_snap_counts_keep_only_the_weeks_played(monkeypatch):
    monkeypatch.setitem(sys.modules, 'snap_update', FakeSnapUpdate)
    data = oracle.build_snap_counts('/raw', '/players.csv', 2026, 10)
    assert [row[1] for row in data['team_snaps']] == [9]
    assert [row[1] for row in data['player_snaps']] == [9]
    assert [row[1] for row in data['active']] == [9]
    assert data['through_week'] == 10


def test_snap_counts_refuse_a_season_with_no_week_through_the_cutoff(monkeypatch):
    monkeypatch.setitem(sys.modules, 'snap_update', FakeSnapUpdate)
    with pytest.raises(ValueError, match='through week 8'):
        oracle.build_snap_counts('/raw', '/players.csv', 2026, 8)


def test_scoreboard_kickoff_refuses_when_the_game_is_missing_or_ambiguous():
    with pytest.raises(ValueError, match='0 matching'):
        oracle.scoreboard_kickoff(FakeScoreboard([espn_event('2026-11-20T01:15Z', 'HOU', 'JAX')]), TNF)
    twice = [espn_event('2026-11-20T01:15Z', 'HOU', 'IND')] * 2
    with pytest.raises(ValueError, match='2 matching'):
        oracle.scoreboard_kickoff(FakeScoreboard(twice), TNF)


def test_a_streak_is_the_current_run_and_ties_break_nothing():
    assert oracle._streak(['W', 'W', 'L', 'W', 'T']) == 'W1'
    assert oracle._streak(['L', 'L', 'W', 'W']) == 'W2'
    assert oracle._streak(['T']) == ''
    assert oracle._streak([]) == ''


def test_streak_file_counts_only_games_available_at_the_cutoff(tmp_path):
    path = tmp_path / 'streaks.db'
    conn = sqlite3.connect(path)
    conn.executescript("""CREATE TABLE nfl_schedule (game_id TEXT, season INTEGER, game_type TEXT, gameday TEXT,
        gametime TEXT, home_team TEXT, away_team TEXT, home_score INTEGER, away_score INTEGER);""")
    games = [
        ('g1', '2026-11-08', '13:00', 'HOU', 'IND', 20, 10),   # HOU wins
        ('g2', '2026-11-15', '13:00', 'IND', 'HOU', 30, 27),   # IND wins, HOU loses
        ('g3', '2026-11-15', '13:00', 'WSH', 'LAR', 17, 24),   # LAR wins -> LA, WSH loses -> WAS
        ('g4', '2026-11-17', '20:15', 'DEN', 'KC', 20, 17),    # kicks off after the cutoff
        ('target', '2026-11-19', '20:15', 'HOU', 'IND', None, None),
    ]
    conn.executemany("INSERT INTO nfl_schedule VALUES (?,?,?,?,?,?,?,?,?)",
                     [(gid, 2026, 'REG', day, time, home, away, hs, as_) for gid, day, time, home, away, hs, as_ in games])
    conn.commit()
    conn.close()
    cutoff = oracle.datetime(2026, 11, 17, 12, 0, tzinfo=oracle.timezone.utc)
    payload, used = oracle.build_streaks(path, cutoff, 'target')
    assert used == ['g1', 'g2', 'g3']
    assert payload['teams']['HOU'] == {'streak': 'L1'}
    assert payload['teams']['IND'] == {'streak': 'W1'}
    assert payload['teams']['LA'] == {'streak': 'W1'}
    assert payload['teams']['WAS'] == {'streak': 'L1'}
    assert 'DEN' not in payload['teams']


def test_player_prop_comparison_reads_the_forward_platt_rows(tmp_path):
    path = tmp_path / 'props.db'
    conn = sqlite3.connect(path)
    conn.executescript("""CREATE TABLE players (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE player_forward_platt (run_id TEXT, game_id TEXT, team TEXT, player_id INTEGER, market TEXT,
            line REAL, source TEXT, over_odds INTEGER, under_odds INTEGER, p_over_fair REAL, p_over_raw REAL,
            p_over_platt REAL, books_at_line INTEGER, selection TEXT, model_version TEXT, as_of TEXT);""")
    conn.execute("INSERT INTO players VALUES (1, 'Pat Test')")
    conn.executemany("INSERT INTO player_forward_platt VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        ('r1', 'G1', 'IND', 1, 'receptions', 4.5, 'rotowire:fanduel', -110, -110, 0.5, 0.45, 0.6, 2,
         'nearest_even_odds', 'v2-platt', 't'),
        ('r1', 'G1', 'IND', 1, 'rushing_yards', 40.5, 'rotowire:fanduel', -115, -105, 0.51, 0.5, 0.48, 1,
         'nearest_even_odds', 'v2-platt', 't')])
    conn.commit()
    conn.close()
    rows = oracle.player_prop_comparison(path, 'G1')
    assert [r['market'] for r in rows] == ['receptions', 'rushing_yards']
    assert rows[0]['player'] == 'Pat Test'
    assert rows[0]['edge_platt'] == 0.1
    assert oracle.player_prop_comparison(path, 'NOPE') == []


def test_player_prop_comparison_refuses_a_database_without_the_table(tmp_path):
    path = tmp_path / 'empty.db'
    sqlite3.connect(path).close()
    with pytest.raises(ValueError, match='not readable'):
        oracle.player_prop_comparison(path, 'G1')
