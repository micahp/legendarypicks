#!/usr/bin/env python3
"""Poll RotoWire's all-player NFL news feed and store every update under the player it matches.

One request covers every NFL player, so the feed is the complete list of updates. Update ids rise with publish time, so
a poll that starts above the previous poll's highest id has missed the ids in between. Those gaps are recorded on the
poll row, not hidden. A gap is "not seen by any poll", not proof that RotoWire dropped an update.

Identity: a RotoWire player id joins to players.id only through player_source_ids (source 'rotowire', league 'nfl'). A
name is never a join key. An id with no crosswalk row, or with two, is stored with player_id NULL and written to
unresolved_players for review. Nothing here creates a players row. Identity columns are rewritten on every poll, so they
reflect the crosswalk as of the latest poll.

Usage: ingest_nfl_player_news.py --db PATH [--feed-file XML]. The database is always named explicitly.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sqlite3
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import nfl_news

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
             previous_max_id, new_updates, changed_updates, matched, unmatched, boundary_gap_count,
             internal_gap_count, gap_ids)
           VALUES (?,?,?,?,?,?,0,0,0,0,?,?,?)""",
        (polled_at, feed['feed_date'], feed_min, feed_max, len(items), previous, len(boundary), len(internal),
         json.dumps(gap_ids)))
    poll_id = cursor.lastrowid

    new_updates = changed_updates = 0
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

    for rotowire_id, (player_id, match) in identity.items():
        con.execute('UPDATE nfl_player_news_updates SET player_id=?, match=? WHERE rotowire_player_id=?',
                    (player_id, match, rotowire_id))
        _update_review_queue(con, rotowire_id, match, latest_by_player[rotowire_id], polled_at)

    matched = sum(1 for item in items if identity[item['source_player_id']][1] == 'crosswalk')
    unmatched = len(items) - matched
    con.execute('UPDATE nfl_player_news_polls SET new_updates=?, changed_updates=?, matched=?, unmatched=? WHERE id=?',
                (new_updates, changed_updates, matched, unmatched, poll_id))
    return {'poll_id': poll_id, 'feed_count': len(items), 'feed_min': feed_min, 'feed_max': feed_max,
            'new_updates': new_updates, 'changed_updates': changed_updates, 'matched': matched,
            'unmatched': unmatched, 'boundary_gaps': len(boundary), 'internal_gaps': len(internal)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--db', required=True, help='SQLite database to write (always named explicitly)')
    ap.add_argument('--feed-file', help='parse this saved XML instead of fetching the live feed')
    ap.add_argument('--url', default=nfl_news.ROTOWIRE_NFL_NEWS_URL)
    a = ap.parse_args(argv)

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
          f"unmatched {summary['unmatched']} queued for review; id gaps {summary['boundary_gaps']} since the "
          f"previous poll and {summary['internal_gaps']} inside this feed")
    return 0


if __name__ == '__main__':
    sys.exit(main())
