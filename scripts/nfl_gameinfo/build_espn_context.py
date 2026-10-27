#!/usr/bin/env python3
"""Backfill game attendance, broadcast network and venue city/state from ESPN's weekly scoreboard.

Request budget: one request per season week, 18 regular-season weeks plus 4 postseason rounds, 2015-2025. That is 22
requests per season and 242 in total, all to site.web.api.espn.com. A per-game backfill would be about 3,300 requests,
so the weekly endpoint is the reduction. Requests go through the repo's shared paced_http client: 2.5 second spacing,
a per-job host budget sized to this run (242), and a disk cache, so a rerun re-spends nothing on weeks already fetched.

Durability: every week is written to the database as soon as it succeeds, with its own status row. A week that fails
after the client's retries is recorded as failed, and the run stops there. It does not write empty weeks and does not
keep going against a host that is refusing requests. Rerunning resumes at the first week without an ok status.

Matching: an ESPN event maps to a schedule game only when season, week, home team and away team all agree, after the
ESPN-to-nflverse team code map below. Unmatched events are stored with their reason, not guessed.

Known-at: attendance is only known after the game. Broadcast networks are stored as published on the scoreboard; this
job cannot show when they were first published, so their known-at stays unknown.
"""
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_BACKEND = '/root/legendarypicks/backend'
sys.path.insert(0, REPO_BACKEND)
import paced_http  # noqa: E402

DB = os.path.join(HERE, 'gameinfo.sqlite')
CACHE = os.path.join(HERE, 'espn_cache')
URL = ('https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard'
       '?seasontype={seasontype}&week={week}&dates={season}')
SEASONS = range(2015, 2026)
REG_WEEKS = range(1, 19)
POST_WEEKS = range(1, 6)  # ESPN postseason: 1 wild card, 2 divisional, 3 conference, 4 Pro Bowl, 5 Super Bowl
ESPN_TO_NFLVERSE = {'WSH': 'WAS'}
# nflverse codes the Rams LA from 2016; before that it is STL in the schedule, and ESPN's LAR is used from 2016.
RAMS_FROM = 2016
SCHEMA = """
CREATE TABLE IF NOT EXISTS nfl_game_context (
    game_id TEXT PRIMARY KEY, espn_event_id TEXT, season INTEGER, week INTEGER,
    attendance INTEGER, broadcast_networks TEXT, venue_name TEXT, venue_city TEXT, venue_state TEXT,
    neutral_site INTEGER, completed INTEGER, source TEXT, source_url TEXT, source_sha256 TEXT,
    fetched_at TEXT, attendance_known_at TEXT, broadcast_known_at TEXT);
CREATE TABLE IF NOT EXISTS nfl_game_context_fetch (
    season INTEGER, seasontype INTEGER, week INTEGER, status TEXT, events INTEGER, matched INTEGER,
    unmatched INTEGER, error TEXT, fetched_at TEXT, PRIMARY KEY (season, seasontype, week));
CREATE TABLE IF NOT EXISTS nfl_game_context_unmatched (
    season INTEGER, seasontype INTEGER, week INTEGER, espn_event_id TEXT, away TEXT, home TEXT,
    schedule_candidates INTEGER, PRIMARY KEY (espn_event_id));
"""
BUDGET = int(len(SEASONS) * (len(REG_WEEKS) + len(POST_WEEKS)))


def team(code, season):
    if code == 'LAR' and season >= RAMS_FROM:
        return 'LA'
    return ESPN_TO_NFLVERSE.get(code, code)


def events_from(doc, seasontype, week, season):
    for ev in doc.get('events', []):
        comp = ev['competitions'][0]
        home = next(c for c in comp['competitors'] if c.get('homeAway') == 'home')
        away = next(c for c in comp['competitors'] if c.get('homeAway') == 'away')
        yield {
            'espn_event_id': str(ev['id']), 'season': season, 'seasontype': seasontype, 'week': week,
            'home': team(home['team']['abbreviation'], season), 'away': team(away['team']['abbreviation'], season),
            'attendance': comp.get('attendance'),
            'broadcasts': sorted({n for b in comp.get('broadcasts', []) for n in b.get('names', [])}),
            'venue_name': comp.get('venue', {}).get('fullName'),
            'venue_city': comp.get('venue', {}).get('address', {}).get('city'),
            'venue_state': comp.get('venue', {}).get('address', {}).get('state'),
            'neutral_site': bool(comp.get('neutralSite')),
            'completed': bool(ev.get('status', {}).get('type', {}).get('completed')),
        }


def week_rows(sched, doc, url, season, seasontype, week, now):
    """Return (matched rows, unmatched rows) for one fetched week."""
    body_sha = hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()
    matched, unmatched = [], []
    for ev in events_from(doc, seasontype, week, season):
        if seasontype == 2:
            sched_week, gtype = ev['week'], 'REG'
        elif ev['week'] == 5:
            # ESPN week 5 is the Super Bowl: schedule week 21 through 2020, 22 from 2021
            sched_week, gtype = (21 if season <= 2020 else 22), None
        else:
            # schedule weeks: 2015-2020 postseason starts at 18, 2021 onward at 19
            sched_week, gtype = ev['week'] + (17 if season <= 2020 else 18), None
        cand = sched[(sched.season == season) & (sched.week == sched_week)
                     & (sched.home_team == ev['home']) & (sched.away_team == ev['away'])]
        if gtype:
            cand = cand[cand.game_type == gtype]
        if len(cand) != 1:
            unmatched.append((season, seasontype, week, ev['espn_event_id'], ev['away'], ev['home'], len(cand)))
            continue
        matched.append((cand.game_id.iloc[0], ev['espn_event_id'], season, sched_week,
                        ev['attendance'], '|'.join(ev['broadcasts']) or None, ev['venue_name'],
                        ev['venue_city'], ev['venue_state'], int(ev['neutral_site']),
                        int(ev['completed']), 'espn_site_web_scoreboard', url, body_sha, now,
                        'post_game', 'unknown'))
    return matched, unmatched


def main():
    global sched
    import pandas as pd
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    sched = pd.read_sql('select game_id, season, week, home_team, away_team, game_type from nfl_game_xwalk', con)
    fetch = paced_http.Fetcher(min_interval=2.5, retry_waits=(5.0, 20.0, 60.0), cache_dir=CACHE,
                               cache_ttl=10 * 365 * 86400, host_budget=BUDGET)
    done = {(s, t, w) for s, t, w in con.execute(
        "select season, seasontype, week from nfl_game_context_fetch where status='ok'")}
    requests, stopped_on = 0, None
    for season in SEASONS:
        for seasontype, weeks in ((2, REG_WEEKS), (3, POST_WEEKS)):
            for week in weeks:
                if (season, seasontype, week) in done:
                    continue
                url = URL.format(seasontype=seasontype, week=week, season=season)
                now = datetime.now(timezone.utc).isoformat()
                try:
                    doc = fetch.json(url)
                except Exception as exc:  # the client has already retried; record and stop
                    requests += 1
                    con.execute('INSERT OR REPLACE INTO nfl_game_context_fetch VALUES (?,?,?,?,?,?,?,?,?)',
                                (season, seasontype, week, 'failed', 0, 0, 0,
                                 f'{type(exc).__name__}: {exc}'[:300], now))
                    con.commit()
                    stopped_on = (season, seasontype, week, str(exc)[:120])
                    break
                requests += 1
                matched, unmatched = week_rows(sched, doc, url, season, seasontype, week, now)
                events = len(doc.get('events', []))
                con.executemany('INSERT OR REPLACE INTO nfl_game_context VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                matched)
                con.executemany('INSERT OR REPLACE INTO nfl_game_context_unmatched VALUES (?,?,?,?,?,?,?)', unmatched)
                con.execute('INSERT OR REPLACE INTO nfl_game_context_fetch VALUES (?,?,?,?,?,?,?,?,?)',
                            (season, seasontype, week, 'ok', events, len(matched), len(unmatched), None, now))
                con.commit()
                print(season, seasontype, week, 'events', events, 'matched', len(matched),
                      'unmatched', len(unmatched), flush=True)
            if stopped_on:
                break
        if stopped_on:
            break
    total = con.execute('select count(*) from nfl_game_context').fetchone()[0]
    ok_weeks = con.execute("select count(*) from nfl_game_context_fetch where status='ok'").fetchone()[0]
    unmatched_total = con.execute('select count(*) from nfl_game_context_unmatched').fetchone()[0]
    con.close()
    print(json.dumps({'requests_this_run': requests, 'request_budget': BUDGET, 'ok_weeks': ok_weeks,
                      'rows_in_db': total, 'unmatched_total': unmatched_total, 'stopped_on': stopped_on}))


if __name__ == '__main__':
    main()
