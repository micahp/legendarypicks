"""The team sitemap ingest: parsing, what counts as an injury or inactive article, and loud failures."""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ingest_team_injury_articles as ing  # noqa: E402

BASE = 'https://www.baltimoreravens.com'
PAGE = """
<table><tbody>
<tr><td tabindex="0">2026-11-07</td><td><a href="/news/injury-report-ravens-vikings-ronnie-stanley" class="x">
 Injury Report: Ravens vs. Vikings &amp; Week 10</a></td></tr>
<tr><td tabindex="0">2026-11-09</td><td><a href="/news/ravens-vikings-inactives-healthy-scratches" class="x">Inactives</a></td></tr>
<tr><td tabindex="0">2026-11-10</td><td><a href="/news/ravens-ir-move" class="x">Ravens place player on injured reserve</a></td></tr>
<tr><td tabindex="0">2026-11-11</td><td><a href="/news/practice-squad-signing" class="x">Practice squad signing</a></td></tr>
<tr><td tabindex="0">2026-11-12</td><td><a href="/news/game-preview" class="x">Game preview</a></td></tr>
</tbody></table>
"""


class FakeFetch:
    def __init__(self, pages):
        self.pages = pages

    def text(self, url, ttl=None):
        if url not in self.pages:
            raise RuntimeError(f'{url} failed: retries exhausted')
        return self.pages[url]


def test_rows_parse_with_absolute_urls_and_clean_titles():
    rows = ing.parse_sitemap(PAGE, BASE)
    assert len(rows) == 5
    assert rows[0] == ('2026-11-07', BASE + '/news/injury-report-ravens-vikings-ronnie-stanley',
                       'Injury Report: Ravens vs. Vikings & Week 10')


def test_only_injury_inactive_and_practice_articles_are_kept():
    kinds = {url.rsplit('/', 1)[-1]: ing.classify(url, title) for _, url, title in ing.parse_sitemap(PAGE, BASE)}
    assert kinds == {
        'injury-report-ravens-vikings-ronnie-stanley': 'injury_report',
        'ravens-vikings-inactives-healthy-scratches': 'inactives',
        'ravens-ir-move': None,            # injured reserve alone is not an injury report
        'practice-squad-signing': 'practice',
        'game-preview': None,
    }


def test_a_month_keeps_only_articles_dated_in_that_month():
    fetch = FakeFetch({f'{BASE}/sitemap/html/articles/2026/11': PAGE})
    rows, parsed = ing.fetch_month(fetch, BASE, '2026-11')
    assert parsed == 5
    assert all(date.startswith('2026-11') for date, _, _ in rows)


def test_ingest_counts_new_and_already_held_and_stores_only_kept_rows(tmp_path, monkeypatch):
    db = str(tmp_path / 'dev.db')
    pages = {f'{site}/sitemap/html/articles/2026/11': '' for site in ing.TEAM_SITES.values()}
    pages[f'{BASE}/sitemap/html/articles/2026/11'] = PAGE
    monkeypatch.setattr(ing, 'TEAM_SITES', {'BAL': BASE})
    lines, failures = ing.ingest(db, ['2026-11'], FakeFetch(pages))
    assert failures == []
    assert lines[0] == ('BAL 2026-11: 5 rows on the sitemap, 3 injury or inactive articles, 3 new, 0 already held')
    lines, failures = ing.ingest(db, ['2026-11'], FakeFetch({f'{BASE}/sitemap/html/articles/2026/11': PAGE}))
    assert failures == []
    assert lines[0].endswith('0 new, 3 already held')
    con = sqlite3.connect(db)
    assert con.execute('SELECT COUNT(*) FROM team_injury_articles').fetchone()[0] == 3
    con.close()


def test_a_sitemap_that_cannot_be_fetched_is_a_failure_not_a_skip(tmp_path, monkeypatch):
    monkeypatch.setattr(ing, 'TEAM_SITES', {'BAL': BASE})
    lines, failures = ing.ingest(str(tmp_path / 'dev.db'), ['2026-11'], FakeFetch({}))
    assert len(failures) == 1 and failures[0].startswith('BAL 2026-11: ')
    assert 'FAILED' in lines[0]


def test_an_empty_sitemap_is_a_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(ing, 'TEAM_SITES', {'BAL': BASE})
    fetch = FakeFetch({f'{BASE}/sitemap/html/articles/2026/11': '<html>changed page</html>'})
    lines, failures = ing.ingest(str(tmp_path / 'dev.db'), ['2026-11'], fetch)
    assert failures == ['BAL 2026-11: sitemap parsed to 0 article rows; the page format may have changed']


def test_every_team_has_a_site():
    assert len(ing.TEAM_SITES) == 32
