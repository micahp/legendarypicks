"""Capture a fixed, previously unexposed postgame corpus. Does not generate stories.

This acquisition step reads one local SQLite database in read-only mode and
fetches publisher JSON. The actual story replay is a separate offline command.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import urllib.request

from postgame_story_facts import load_scoreboard

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / 'docs/research/postgame-content-demo-2026-11-10'
SEED = '20261111-postgame-heldout-v03'
COACHED_PAIRS = {frozenset(x.split(':')) for x in ('CHI:SEA', 'SAC:DAL', 'NOP:MEM', 'BOS:HOU', 'UTA:SA', 'POR:DEN')}


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'LegendaryPicksResearch/1.0'})
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read()
    return raw, json.loads(raw)


def integer(value):
    s = str(value)
    return int(s) if s.lstrip('-').isdigit() else None


def enrich(bundle):
    league = bundle['game']['league']; gid = bundle['game']['game_id']
    sport = 'basketball/nba' if league == 'nba' else 'football/nfl'
    summary_url = f'https://site.api.espn.com/apis/site/v2/sports/{sport}/summary?event={gid}'
    raw, summary = fetch(summary_url)
    captured = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    comp = summary['header']['competitions'][0]
    if comp['status']['type']['name'] != 'STATUS_FINAL' or not comp['status']['type'].get('completed'):
        raise ValueError('publisher summary is not final')
    refs = {c['team']['abbreviation']: c for c in comp['competitors']}
    for team in bundle['teams']:
        ref = refs[team['id']]
        if int(ref['score']) != team['score']:
            raise ValueError('publisher summary and scoreboard disagree')
        team['publisher_team_id'] = ref['team']['id']
    totals = {t['publisher_team_id']: t['score'] for t in bundle['teams']}
    box_id = 'boxscore:' + gid
    players = {}
    for team_box in summary.get('boxscore', {}).get('players', []):
        team = next(t for t in bundle['teams'] if t['publisher_team_id'] == team_box['team']['id'])
        for group in team_box.get('statistics', []):
            keys = group['keys']
            if league == 'nba':
                fields = {'points': 'points', 'rebounds': 'rebounds', 'assists': 'assists'}
            elif group.get('name') == 'passing':
                fields = {'passing_yards': 'passingYards', 'passing_touchdowns': 'passingTouchdowns'}
            elif group.get('name') == 'rushing':
                fields = {'rushing_yards': 'rushingYards'}
            elif group.get('name') == 'receiving':
                fields = {'receiving_yards': 'receivingYards'}
            else:
                continue
            if any(key not in keys for key in fields.values()):
                continue
            for row in group.get('athletes', []):
                values = row.get('stats', [])
                if row.get('didNotPlay') or len(values) != len(keys):
                    continue
                identity = row['athlete']['id']; player_key = (team['id'], identity)
                player = players.setdefault(player_key, {'id': identity, 'name': row['athlete']['displayName'],
                            'game_id': gid, 'team_id': team['id'], 'publisher_team_id': team['publisher_team_id'],
                            'source_id': box_id, 'stats': {}})
                for name, key in fields.items():
                    value = integer(values[keys.index(key)])
                    if value is not None:
                        player['stats'][name] = value
    if league == 'nba':
        for t in bundle['teams']:
            if sum(p['stats'].get('points', 0) for p in players.values() if p['team_id'] == t['id']) != t['score']:
                raise ValueError('boxscore player points do not match final score')
    box = {'id': box_id, 'kind': 'final_boxscore', 'status': 'final', 'source': 'espn',
           'source_event_id': gid, 'captured_at': captured, 'url': summary_url, 'teams': totals,
           'raw_response_sha256': hashlib.sha256(raw).hexdigest()}
    bundle['players'] = list(players.values()); bundle['sources'].append(box); bundle['as_of_utc'] = captured
    if league == 'nba':
        periods = {c['team']['id']: [int(q['displayValue']) for q in c.get('linescores', [])] for c in comp['competitors']}
        if all(t['publisher_team_id'] in periods and sum(periods[t['publisher_team_id']]) == t['score'] for t in bundle['teams']):
            bundle['segments'] = {'source_id': box_id, 'period_scores': periods}
        plays = summary.get('plays', [])
        monotonic = bool(plays) and all(int(a['sequenceNumber']) < int(b['sequenceNumber']) for a, b in zip(plays, plays[1:]))
        if monotonic:
            core_url = f'https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/{gid}/competitions/{gid}/plays?limit=1000'
            try:
                core_raw, core = fetch(core_url); other = core['items']
                fields = ('id', 'sequenceNumber', 'awayScore', 'homeScore')
                matched = (core['pageCount'] == 1 and core['count'] == len(other) == len(plays)
                           and all(all(a.get(k) == b.get(k) for k in fields) and a['period']['number'] == b['period']['number']
                                   and a['clock']['displayValue'] == b['clock']['displayValue'] for a, b in zip(plays, other)))
                if matched:
                    away = next(t for t in bundle['teams'] if t['side'] == 'away')['publisher_team_id']
                    home = next(t for t in bundle['teams'] if t['side'] == 'home')['publisher_team_id']
                    events = []
                    for i, play in enumerate(plays):
                        parts = play['clock']['displayValue'].split(':')
                        clock = float(parts[-1]) + (60 * int(parts[-2]) if len(parts) > 1 else 0)
                        clock = int(clock) if clock.is_integer() else clock
                        score = {away: play['awayScore'], home: play['homeScore']}
                        changed = i > 0 and score != events[-1]['scores']
                        kind = 'start' if i == 0 else 'end' if i == len(plays)-1 else 'period_end' if play['type']['text'] == 'End Period' else 'score' if changed else 'play'
                        events.append({'id': play['id'], 'sequence': int(play['sequenceNumber']), 'period': play['period']['number'],
                                       'clock_seconds': clock, 'kind': kind, 'scores': score})
                    event_capture = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                    source = {'id': 'pbp:' + gid, 'kind': 'final_pbp', 'status': 'final', 'coverage': 'complete',
                              'source': 'espn', 'source_event_id': gid, 'captured_at': event_capture, 'url': summary_url,
                              'crosscheck_url': core_url, 'event_count': len(events), 'teams': totals,
                              'raw_response_sha256': hashlib.sha256(raw).hexdigest(),
                              'crosscheck_raw_response_sha256': hashlib.sha256(core_raw).hexdigest(),
                              'events_sha256': hashlib.sha256(json.dumps(events, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}
                    bundle['events'] = events; bundle['event_sequence'] = {'source_id': source['id']}
                    bundle['sources'].append(source); bundle['as_of_utc'] = event_capture
            except (OSError, ValueError, KeyError, TypeError):
                bundle['event_sequence'] = 'unavailable: cross-check failed'
    return bundle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prior = {json.loads(line)['game_id'] for line in (RESEARCH / 'heldout_results.jsonl').read_text().splitlines()}
    prior |= {p.stem for p in (RESEARCH / 'fixtures').glob('*.json')}
    con = sqlite3.connect(args.db.resolve().as_uri() + '?mode=ro', uri=True)
    con.row_factory = sqlite3.Row; con.execute('PRAGMA query_only=ON')
    selected = []
    for league in ('nfl', 'nba'):
        rows = con.execute('SELECT game_id,payload FROM scoreboard_snapshots WHERE league=? AND state=?', (league, 'post')).fetchall()
        eligible = []
        for row in rows:
            p = json.loads(row['payload']); pair = frozenset((p.get('away', {}).get('abbrev'), p.get('home', {}).get('abbrev')))
            if row['game_id'] not in prior and pair not in COACHED_PAIRS:
                eligible.append(row['game_id'])
        eligible = sorted(set(eligible), key=lambda gid: hashlib.sha256((SEED + ':' + league + ':' + gid).encode()).hexdigest())
        if len(eligible) < 50:
            raise SystemExit('not enough unexposed games: ' + league)
        selected.extend((league, gid) for gid in eligible[:50])
    con.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if args.output.exists():
        for line in args.output.read_text().splitlines():
            row = json.loads(line)
            existing.append((row['game']['league'], row['game']['game_id']))
        if existing != selected[:len(existing)] or len(existing) > len(selected):
            raise SystemExit('existing corpus does not match the fixed sample; refusing to change it')
    with args.output.open('a') as output:
        for index, (league, gid) in enumerate(selected[len(existing):], len(existing) + 1):
            bundle = load_scoreboard(args.db, league, gid)
            try:
                bundle = enrich(copy.deepcopy(bundle))
            except Exception as exc:
                bundle['capture_issue'] = type(exc).__name__ + ': ' + str(exc)
            output.write(json.dumps(bundle, sort_keys=True, ensure_ascii=False) + '\n'); output.flush()
            if index % 10 == 0:
                print(f'Captured {index}/100 (no stories generated)', flush=True)
            time.sleep(0.15)
    print('Corpus captured; replay is a separate offline step.')


if __name__ == '__main__':
    main()
