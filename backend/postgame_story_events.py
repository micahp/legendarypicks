"""Select a late lead change only from a reconciled, complete event sequence."""
import hashlib
import json
from postgame_story_audit import timestamp


def late_lead(bundle):
    game = bundle.get('game', {}); teams = bundle.get('teams', [])
    events = bundle.get('events', []); descriptor = bundle.get('event_sequence')
    if not isinstance(descriptor, dict) or len(teams) != 2 or not events:
        return None
    src = next((x for x in bundle.get('sources', []) if x.get('id') == descriptor.get('source_id')), {})
    cutoff = timestamp(bundle.get('as_of_utc')); start = timestamp(game.get('start_utc')); captured = timestamp(src.get('captured_at'))
    scores = {str(t.get('publisher_team_id')): t.get('score') for t in teams}
    if (len(scores) != 2 or any(not t.get('publisher_team_id') for t in teams) or src.get('kind') != 'final_pbp'
            or src.get('status') != 'final' or src.get('coverage') != 'complete'
            or str(src.get('source_event_id')) != str(game.get('game_id')) or src.get('teams') != scores
            or not cutoff or not start or not captured or not start <= captured <= cutoff
            or src.get('event_count') != len(events)):
        return None
    encoded = json.dumps(events, sort_keys=True, separators=(',', ':')).encode()
    if src.get('events_sha256') != hashlib.sha256(encoded).hexdigest():
        return None
    if events[0].get('kind') != 'start' or events[-1].get('kind') != 'end':
        return None
    if events[0].get('period') != 1 or events[0].get('scores') != {k: 0 for k in scores} or events[-1].get('scores') != scores:
        return None
    if events[-1].get('period', 0) < 4 or events[-1].get('clock_seconds') != 0:
        return None
    boundaries = {e.get('period') for e in events if e.get('kind') == 'period_end' and e.get('clock_seconds') == 0}
    if not {1, 2, 3}.issubset(boundaries):
        return None
    previous = None; ids = set()
    for e in events:
        current = e.get('scores', {}); clock = e.get('clock_seconds'); period = e.get('period'); seq = e.get('sequence')
        if (not e.get('id') or e['id'] in ids or type(seq) is not int or type(period) is not int or period < 1
                or type(clock) not in (int, float) or not 0 <= clock <= (720 if game.get('league') == 'nba' else 900)
                or set(current) != set(scores) or any(type(v) is not int or v < 0 for v in current.values())):
            return None
        ids.add(e['id'])
        if previous:
            if seq <= previous['sequence'] or period < previous['period'] or (period == previous['period'] and clock > previous['clock_seconds']):
                return None
            changes = [current[k] - previous['scores'][k] for k in scores]
            if any(x < 0 for x in changes) or sum(x > 0 for x in changes) > 1 or max(changes) > (4 if game.get('league') == 'nba' else 8):
                return None
            if any(changes) and e.get('kind') != 'score':
                return None
        previous = e
    if teams[0]['score'] == teams[1]['score']:
        return None
    winner = max(teams, key=lambda t: t['score']); loser = min(teams, key=lambda t: t['score'])
    win_id, lose_id = winner['publisher_team_id'], loser['publisher_team_id']
    was_behind = False
    for i, e in enumerate(events):
        if e['period'] >= 3 and e['scores'][win_id] < e['scores'][lose_id]:
            was_behind = True
        if (was_behind and e['period'] == 4 and i > 0 and e['scores'][win_id] > e['scores'][lose_id]
                and events[i-1]['scores'][win_id] <= events[i-1]['scores'][lose_id]
                and all(later['scores'][win_id] >= later['scores'][lose_id] for later in events[i:])):
            return {'event_id': e['id'], 'winner_id': winner['id'], 'loser_id': loser['id'],
                    'source_id': src['id'], 'type': 'late_lead'}
    runs = []; run = None
    for previous, current in zip(events, events[1:]):
        change = {k: current['scores'][k] - previous['scores'][k] for k in scores}
        scoring_team = next((k for k, value in change.items() if value > 0), None)
        if scoring_team is None:
            continue
        if run and run['team'] == scoring_team:
            run['points'] += change[scoring_team]; run['end'] = current
        else:
            if run:
                runs.append(run)
            run = {'team': scoring_team, 'points': change[scoring_team], 'start': current, 'end': current}
    if run:
        runs.append(run)
    runs = [r for r in runs if r['team'] == win_id and r['points'] >= 10
            and r['start']['period'] in (3, 4) and r['end']['period'] in (3, 4)]
    if runs:
        run = sorted(runs, key=lambda r: (-r['points'], r['start']['sequence']))[0]
        return {'type': 'scoring_run', 'winner_id': winner['id'], 'loser_id': loser['id'],
                'source_id': src['id'], 'start_event_id': run['start']['id'], 'end_event_id': run['end']['id'],
                'points': run['points'], 'start_period': run['start']['period'], 'end_period': run['end']['period']}
    return None
