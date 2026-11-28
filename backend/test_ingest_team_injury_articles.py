"""Offline tests of the team article discovery catalog and its cutoff boundary."""
import sqlite3
from datetime import datetime, timezone

import pytest
import ingest_team_injury_articles as ing

BASE = 'https://www.therams.com'
URL = BASE + '/sitemap/html/articles/2026/11'
PAGE = '''
<tr><td tabindex="0">2026-11-07</td><td><a href="/news/injury-report" class="x">Injury Report &amp; Week 10</a></td></tr>
<tr><td tabindex="0">2026-11-09</td><td><a href="/news/inactives">Inactives</a></td></tr>
<tr><td tabindex="0">2026-11-10</td><td><a href="/news/ir-move">Player on injured reserve</a></td></tr>
<tr><td tabindex="0">2026-11-11</td><td><a href="/news/game-preview">Game preview</a></td></tr>
'''


class FakeFetch:
    def __init__(self, page=PAGE):
        self.page = page

    def text(self, url, ttl=None):
        assert url == URL
        assert ttl == 0
        if self.page is None:
            raise RuntimeError('fetch failed')
        return self.page


def clock(day):
    return lambda: datetime(2026, 11, day, 12, tzinfo=timezone.utc)


def test_observation_cutoff_aliases_and_title_only(tmp_path, monkeypatch):
    db = tmp_path / 'test.db'
    sqlite3.connect(db).close()
    monkeypatch.setattr(ing, 'TEAM_SITES', {'LAR': BASE})
    assert ing.ingest(db, ['2026-11'], FakeFetch(), clock=clock(20))[1] == []
    assert ing.list_observed(db, 'LA', '2026-11-19T23:59:59Z')['articles'] == []
    report = ing.list_observed(db, 'LA', '2026-11-20T12:00:00Z')
    assert report['team'] == 'LAR'
    assert report['player_status_verified'] is False and report['complete'] is False
    assert len(report['articles']) == 2
    assert all(row['sitemap_url'] == URL and len(row['sitemap_sha256']) == 64 for row in report['articles'])
    assert 'Injury Report & Week 10' in [row['title'] for row in report['articles']]
    changed = PAGE.replace('Week 10', 'Corrected title')
    assert ing.ingest(db, ['2026-11'], FakeFetch(changed), clock=clock(21))[1] == []
    assert ing.list_observed(db, 'LAR', '2026-11-20T13:00:00Z') == report | {'as_of_utc': '2026-11-20T13:00:00.000000+00:00'}
    assert 'Injury Report & Corrected title' in [row['title'] for row in ing.list_observed(db, 'LAR', '2026-11-21T13:00:00Z')['articles']]


def test_failed_collection_and_absent_catalog_are_not_success(tmp_path, monkeypatch):
    db = tmp_path / 'test.db'
    sqlite3.connect(db).close()
    monkeypatch.setattr(ing, 'TEAM_SITES', {'LAR': BASE})
    with pytest.raises(sqlite3.OperationalError):
        ing.list_observed(db, 'LAR', '2026-11-20T12:00:00Z')
    assert len(ing.ingest(db, ['2026-11'], FakeFetch(None), clock=clock(20))[1]) == 1
    assert len(ing.ingest(db, ['2026-11'], FakeFetch(''), clock=clock(20))[1]) == 1
    with pytest.raises(ValueError, match='timezone-qualified'):
        ing.list_observed(db, 'LAR', '2026-11-20')
    with pytest.raises(FileNotFoundError):
        ing.ingest(tmp_path / 'missing.db', ['2026-11'], FakeFetch(), clock=clock(20))


def test_site_keys_are_canonical():
    import team_codes
    assert set(ing.TEAM_SITES) == team_codes.CANONICAL['nfl']


def test_oracle_cli_reads_catalog_without_ingesting(tmp_path, monkeypatch, capsys):
    import json
    import oracle
    db = tmp_path / 'test.db'
    sqlite3.connect(db).close()
    monkeypatch.setattr(ing, 'TEAM_SITES', {'LAR': BASE})
    ing.ingest(db, ['2026-11'], FakeFetch(), clock=clock(20))
    assert oracle.main(['--db', str(db), '--injury-articles', 'LA',
                        '--as-of', '2026-11-20T12:00:00Z']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['team'] == 'LAR'
    assert result['player_status_verified'] is False
    assert len(result['articles']) == 2
