#!/usr/bin/env python3
"""Poll RotoWire's all-player NFL news feed and store every update under the player it matches.

One request covers every NFL player, so the feed is the complete list of updates. Update ids rise with publish time, so a
poll that starts above the previous poll's highest id has missed the ids in between. Those gaps are recorded on the poll
row, and the run exits 3 so that systemd marks the unit failed. A gap means "not seen by any poll". It does not prove
that RotoWire dropped an update, and a contiguous capture does not prove the whole history was captured.

Identity: a RotoWire player id joins to players.id only through player_source_ids (source 'rotowire', league 'nfl'). A
name is never a join key. An id with no crosswalk row, or with two, is stored with player_id NULL and written to
unresolved_players for review. Nothing here creates a players row. Identity columns are rewritten on every poll, so they
reflect the crosswalk as of the latest poll.

Every version of an update is kept with its publisher time, first-seen time, source URL and original text. Starter
claims are extracted once per version (nfl_news_claims.py) and attributed to the player each claim is about.

Exit codes: 0 poll stored, 1 feed or database refused (nothing written), 2 --check-stale found a stale or missing poll,
3 poll stored but ids were missing.

Usage: ingest_nfl_player_news.py --db PATH [--feed-file XML] | --db PATH --check-stale MINUTES
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sqlite3
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import nfl_news
import nfl_news_claims

SOURCE = nfl_news.ROTOWIRE_SOURCE
LEAGUE = 'nfl'
TIMEOUT_SECONDS = 20

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS nfl_player_news_updates(
         update_id INTEGER NOT NULL,
         content_sha256 TEXT NOT NULL,
         rotowire_player_id TEXT NOT NULL,
         player_id INTEGER,
         match TEXT NOT NULL,
         team TEXT, first_name TEXT, last_name TEXT, position TEXT,
         injury_status TEXT, injury_type TEXT, injury_location TEXT, return_date TEXT,
         headline TEXT, notes TEXT, analysis TEXT, link TEXT,
         published_utc TEXT NOT NULL,
         published_raw TEXT NOT NULL,
         first_seen_utc TEXT NOT NULL,
         poll_id INTEGER NOT NULL,
         PRIMARY KEY(update_id, content_sha256))""",
    """CREATE INDEX IF NOT EXISTS idx_nfl_player_news_player
         ON nfl_player_news_updates(player_id, published_utc)""",
    """CREATE INDEX IF NOT EXISTS idx_nfl_player_news_rotowire
         ON nfl_player_news_updates(rotowire_player_id)""",
    """CREATE TABLE IF NOT EXISTS nfl_player_news_claims(
         update_id INTEGER NOT NULL,
         content_sha256 TEXT NOT NULL,
         claim_index INTEGER NOT NULL,
         extractor TEXT NOT NULL,
         subject_player_id INTEGER NOT NULL,
         update_player_id INTEGER,
         attribution TEXT NOT NULL,
         claim_class TEXT NOT NULL,
         field TEXT NOT NULL,
         span TEXT NOT NULL,
         poll_id INTEGER NOT NULL,
         PRIMARY KEY(update_id, content_sha256, claim_index, extractor))""",
    """CREATE INDEX IF NOT EXISTS idx_nfl_player_news_claims_subject
         ON nfl_player_news_claims(subject_player_id)""",
    """CREATE TABLE IF NOT EXISTS nfl_player_news_polls(
         id INTEGER PRIMARY KEY AUTOINCREMENT,
         polled_at_utc TEXT NOT NULL,
         feed_date TEXT,
         feed_min_id INTEGER NOT NULL,
         feed_max_id INTEGER NOT NULL,
         feed_count INTEGER NOT NULL,
         previous_max_id INTEGER,
         new_updates INTEGER NOT NULL,
         changed_updates INTEGER NOT NULL,
         new_claims INTEGER NOT NULL,
         claim_counts TEXT NOT NULL,
         matched INTEGER NOT NULL,
         unmatched INTEGER NOT NULL,
         boundary_gap_count INTEGER NOT NULL,
         internal_gap_count INTEGER NOT NULL,
         gap_ids TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS unresolved_players(
         id INTEGER PRIMARY KEY AUTOINCREMENT,
         source TEXT NOT NULL, raw_name TEXT NOT NULL,
         league TEXT NOT NULL, team TEXT, first_seen TEXT NOT NULL,
         count INTEGER DEFAULT 1, source_player_key TEXT, reason TEXT)""",
    """CREATE INDEX IF NOT EXISTS idx_unresolved_players_source_key
         ON unresolved_players(source,league,source_player_key)""",
)


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'legendarypicks-nfl-player-news/1'})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        if response.status != 200:
            raise OSError(f'feed returned HTTP {response.status}')
        return response.read()


def ensure_schema(con):
    for statement in SCHEMA:
        con.execute(statement)


def _published_utc(raw):
    return nfl_news._parse_datetime(raw).astimezone(timezone.utc).isoformat()


def _identity(crosswalk, rotowire_id):
    """(player_id, match) for one RotoWire player id. A single NFL crosswalk row is the only match."""
    candidates = crosswalk.get(rotowire_id, set())
    if len(candidates) == 1:
        return next(iter(candidates)), 'crosswalk'
    if candidates:
        return None, 'ambiguous_crosswalk'
    return None, 'no_crosswalk_row'


def _load_crosswalk(con):
    crosswalk = collections.defaultdict(set)
    rows = con.execute(
        'SELECT source_player_key, player_id FROM player_source_ids WHERE source=? AND league=? AND player_id IS NOT NULL',
        (SOURCE, LEAGUE)).fetchall()
    for key, player_id in rows:
        crosswalk[str(key).strip()].add(int(player_id))
    return crosswalk


def _roster(con, team_code, cache):
    if team_code not in cache:
        rows = con.execute('SELECT id, name FROM players WHERE league=? AND team=?', (LEAGUE, team_code)).fetchall()
        cache[team_code] = [nfl_news_claims.roster_entry(row[0], row[1]) for row in rows]
    return cache[team_code]


def _update_review_queue(con, rotowire_id, match, latest, now):
    """Keep unresolved_players in step with the crosswalk for one RotoWire id."""
    if match == 'crosswalk':
        con.execute('DELETE FROM unresolved_players WHERE source=? AND league=? AND source_player_key=?',
                    (SOURCE, LEAGUE, rotowire_id))
        return
    count = con.execute('SELECT COUNT(DISTINCT update_id) FROM nfl_player_news_updates WHERE rotowire_player_id=?',
                        (rotowire_id,)).fetchone()[0]
    raw_name = f"{latest['first_name']} {latest['last_name']}".strip()
    existing = con.execute('SELECT id FROM unresolved_players WHERE source=? AND league=? AND source_player_key=?',
                           (SOURCE, LEAGUE, rotowire_id)).fetchone()
    if existing:
        con.execute('UPDATE unresolved_players SET raw_name=?, team=?, count=?, reason=? WHERE id=?',
                    (raw_name, latest['team'], count, match, existing[0]))
    else:
        con.execute(
            'INSERT INTO unresolved_players(source, raw_name, league, team, first_seen, count, source_player_key, reason) '
            'VALUES (?,?,?,?,?,?,?,?)',
            (SOURCE, raw_name, LEAGUE, latest['team'], now, count, rotowire_id, match))


def _own_name(con, player_id):
    if player_id is None:
        return None
    row = con.execute('SELECT name FROM players WHERE id=?', (player_id,)).fetchone()
    return row[0] if row else None


def _store_claims(con, item, digest, own_player_id, poll_id, roster_cache):
    """Extract and store the starter claims of one new version. Returns the claim counts."""
    try:
        team_code = nfl_news.normalize_team(item['team'])
    except Exception:
        team_code = None
    roster = _roster(con, team_code, roster_cache) if team_code else []
    claims, counts = nfl_news_claims.extract(item, own_player_id, roster, _own_name(con, own_player_id))
    for index, claim in enumerate(claims):
        con.execute(
            """INSERT INTO nfl_player_news_claims(update_id, content_sha256, claim_index, extractor, subject_player_id,
                 update_player_id, attribution, claim_class, field, span, poll_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (item['id'], digest, index, nfl_news_claims.EXTRACTOR, claim['subject_player_id'], own_player_id,
             claim['attribution'], claim['claim_class'], claim['field'], claim['span'], poll_id))
    return counts


def rebuild_claims(con):
    """Recompute the claim rows of the current extractor from every stored version. Returns the number of claims.

    The claim table is derived. Rebuilding it from the stored text lets a corrected extractor replace earlier output
    without touching the stored articles.
    """
    con.execute('DELETE FROM nfl_player_news_claims WHERE extractor=?', (nfl_news_claims.EXTRACTOR,))
    roster_cache = {}
    versions = con.execute(
        """SELECT u.*, p.name AS own_name FROM nfl_player_news_updates u
           LEFT JOIN players p ON p.id = u.player_id""").fetchall()
    stored = 0
    for row in versions:
        try:
            team_code = nfl_news.normalize_team(row['team'])
        except Exception:
            team_code = None
        roster = _roster(con, team_code, roster_cache) if team_code else []
        item = {'headline': row['headline'], 'notes': row['notes'], 'analysis': row['analysis'], 'team': row['team']}
        claims, _ = nfl_news_claims.extract(item, row['player_id'], roster, row['own_name'])
        for index, claim in enumerate(claims):
            con.execute(
                """INSERT INTO nfl_player_news_claims(update_id, content_sha256, claim_index, extractor, subject_player_id,
                     update_player_id, attribution, claim_class, field, span, poll_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (row['update_id'], row['content_sha256'], index, nfl_news_claims.EXTRACTOR, claim['subject_player_id'],
                 row['player_id'], claim['attribution'], claim['claim_class'], claim['field'], claim['span'],
                 row['poll_id']))
            stored += 1
    return stored


def poll(con, feed, polled_at):
    """Store one parsed feed snapshot in one transaction. Returns the counts printed for this poll."""
    items = feed['items']
    ids = [item['id'] for item in items]
    feed_min, feed_max = min(ids), max(ids)
    seen = set(ids)

    previous = con.execute('SELECT MAX(feed_max_id) FROM nfl_player_news_polls').fetchone()[0]
    boundary = list(range(previous + 1, feed_min)) if previous is not None and feed_min > previous + 1 else []
    internal = [uid for uid in range(feed_min, feed_max + 1) if uid not in seen]
    gap_ids = boundary + internal

    crosswalk = _load_crosswalk(con)
    latest_by_player = {}
    for item in items:  # the feed is newest first, so the first item seen for a player is the latest
        latest_by_player.setdefault(item['source_player_id'], item)

    identity = {rotowire_id: _identity(crosswalk, rotowire_id) for rotowire_id in latest_by_player}
    cursor = con.execute(
        """INSERT INTO nfl_player_news_polls(polled_at_utc, feed_date, feed_min_id, feed_max_id, feed_count,
             previous_max_id, new_updates, changed_updates, new_claims, claim_counts, matched, unmatched,
             boundary_gap_count, internal_gap_count, gap_ids)
           VALUES (?,?,?,?,?,?,0,0,0,'{}',0,0,?,?,?)""",
        (polled_at, feed['feed_date'], feed_min, feed_max, len(items), previous, len(boundary), len(internal),
         json.dumps(gap_ids)))
    poll_id = cursor.lastrowid

    new_updates = changed_updates = 0
    claim_counts = collections.Counter()
    roster_cache = {}
    for item in items:
        digest = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
        if con.execute('SELECT 1 FROM nfl_player_news_updates WHERE update_id=? AND content_sha256=?',
                       (item['id'], digest)).fetchone():
            continue
        if con.execute('SELECT 1 FROM nfl_player_news_updates WHERE update_id=?', (item['id'],)).fetchone():
            changed_updates += 1
        else:
            new_updates += 1
        player_id, match = identity[item['source_player_id']]
        con.execute(
            """INSERT INTO nfl_player_news_updates(update_id, content_sha256, rotowire_player_id, player_id, match,
                 team, first_name, last_name, position, injury_status, injury_type, injury_location, return_date,
                 headline, notes, analysis, link, published_utc, published_raw, first_seen_utc, poll_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (item['id'], digest, item['source_player_id'], player_id, match, item['team'], item['first_name'],
             item['last_name'], item['position'], item['injury_status'], item['injury_type'],
             item['injury_location'], item['return_date'], item['headline'], item['notes'], item['analysis'],
             item['link'], _published_utc(item['published']), item['published'], polled_at, poll_id))
        claim_counts.update(_store_claims(con, item, digest, player_id, poll_id, roster_cache))

    for rotowire_id, (player_id, match) in identity.items():
        con.execute('UPDATE nfl_player_news_updates SET player_id=?, match=? WHERE rotowire_player_id=?',
                    (player_id, match, rotowire_id))
        _update_review_queue(con, rotowire_id, match, latest_by_player[rotowire_id], polled_at)

    matched = sum(1 for item in items if identity[item['source_player_id']][1] == 'crosswalk')
    unmatched = len(items) - matched
    new_claims = sum(claim_counts[key] for key in ('own', 'named_in_other_update'))
    con.execute(
        'UPDATE nfl_player_news_polls SET new_updates=?, changed_updates=?, new_claims=?, claim_counts=?, matched=?, '
        'unmatched=? WHERE id=?',
        (new_updates, changed_updates, new_claims, json.dumps(dict(claim_counts), sort_keys=True), matched, unmatched,
         poll_id))
    return {'poll_id': poll_id, 'feed_count': len(items), 'feed_min': feed_min, 'feed_max': feed_max,
            'new_updates': new_updates, 'changed_updates': changed_updates, 'new_claims': new_claims,
            'claim_counts': dict(claim_counts), 'matched': matched, 'unmatched': unmatched,
            'boundary_gaps': len(boundary), 'internal_gaps': len(internal)}


def check_stale(con, max_age_minutes, now):
    """Return (ok, message) for the newest stored poll."""
    row = con.execute('SELECT id, polled_at_utc FROM nfl_player_news_polls ORDER BY id DESC LIMIT 1').fetchone()
    if row is None:
        return False, 'NFL player news: no poll has been stored'
    polled = datetime.fromisoformat(row[1])
    age = now - polled
    if age > timedelta(minutes=max_age_minutes):
        return False, (f'NFL player news: last poll {row[0]} at {row[1]} is {int(age.total_seconds() // 60)} minutes old, '
                       f'older than {max_age_minutes}')
    return True, f'NFL player news: last poll {row[0]} at {row[1]}, {int(age.total_seconds() // 60)} minutes old'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--db', required=True, help='SQLite database to write (always named explicitly)')
    ap.add_argument('--feed-file', help='parse this saved XML instead of fetching the live feed')
    ap.add_argument('--url', default=nfl_news.ROTOWIRE_NFL_NEWS_URL)
    ap.add_argument('--check-stale', type=int, metavar='MINUTES',
                    help='do not poll; exit 2 if the newest stored poll is older than MINUTES')
    ap.add_argument('--rebuild-claims', action='store_true',
                    help='do not poll; recompute the claim rows of the current extractor from the stored versions')
    a = ap.parse_args(argv)

    if a.rebuild_claims:
        con = sqlite3.connect(a.db, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            with con:
                ensure_schema(con)
                stored = rebuild_claims(con)
        except sqlite3.Error as exc:
            print(f'NFL player news: claim rebuild failed, rolled back: {exc}', file=sys.stderr)
            return 1
        finally:
            con.close()
        print(f'NFL player news: rebuilt {stored} starter claims with extractor {nfl_news_claims.EXTRACTOR}')
        return 0

    if a.check_stale is not None:
        con = sqlite3.connect(f'file:{a.db}?mode=ro', uri=True, timeout=10)
        try:
            ok, message = check_stale(con, a.check_stale, datetime.now(timezone.utc))
        except sqlite3.Error as exc:
            print(f'NFL player news: cannot read poll history: {exc}', file=sys.stderr)
            return 2
        finally:
            con.close()
        print(message, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 2

    try:
        raw = Path(a.feed_file).read_bytes() if a.feed_file else fetch(a.url)
        feed = nfl_news.parse_news_feed(raw)
    except (OSError, ValueError, TypeError) as exc:
        print(f'NFL player news: feed refused, nothing written: {exc}', file=sys.stderr)
        return 1

    polled_at = datetime.now(timezone.utc).isoformat()
    con = sqlite3.connect(a.db, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        with con:
            ensure_schema(con)
            summary = poll(con, feed, polled_at)
    except sqlite3.Error as exc:
        print(f'NFL player news: database error, poll rolled back: {exc}', file=sys.stderr)
        return 1
    finally:
        con.close()

    print(f"NFL player news poll {summary['poll_id']}: feed {summary['feed_count']} updates, ids "
          f"{summary['feed_min']}-{summary['feed_max']}; new updates {summary['new_updates']}, changed "
          f"{summary['changed_updates']}; players matched {summary['matched']} of {summary['feed_count']}, "
          f"unmatched {summary['unmatched']} queued for review; starter claims stored {summary['new_claims']} "
          f"({json.dumps(summary['claim_counts'], sort_keys=True)}); id gaps {summary['boundary_gaps']} since the "
          f"previous poll and {summary['internal_gaps']} inside this feed")
    if summary['boundary_gaps'] or summary['internal_gaps']:
        print(f"ALERT NFL player news poll {summary['poll_id']}: feed ids missing ({summary['boundary_gaps']} "
              f"before this feed, {summary['internal_gaps']} inside it); see nfl_player_news_polls.gap_ids",
              file=sys.stderr)
        return 3
    return 0


if __name__ == '__main__':
    sys.exit(main())
