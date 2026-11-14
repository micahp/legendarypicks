"""Deterministic postgame candidate selection and rendering; no I/O."""
import hashlib
import json
from postgame_story_audit import audit, timestamp
from postgame_story_events import late_lead

VERSION = 'postgame-v0.3'


def _players(bundle):
    """Return usable final-box-score facts, ordered independently of input order."""
    game = bundle.get('game', {})
    cutoff = timestamp(bundle.get('as_of_utc'))
    team_ids = {t.get('id') for t in bundle.get('teams', [])}
    team_map = {t.get('id'): t for t in bundle.get('teams', [])}
    sources = {s.get('id'): s for s in bundle.get('sources', [])}
    usable = []
    for p in bundle.get('players', []):
        source = sources.get(p.get('source_id'), {})
        captured = timestamp(source.get('captured_at'))
        points = p.get('stats', {}).get('points')
        if (game.get('league') == 'nba' and p.get('game_id') == game.get('game_id')
                and p.get('team_id') in team_ids and p.get('id') and p.get('name')
                and p.get('publisher_team_id') and p.get('publisher_team_id') == team_map[p['team_id']].get('publisher_team_id')
                and source.get('teams') == {str(t.get('publisher_team_id')): t.get('score') for t in bundle.get('teams', [])}
                and source.get('kind') == 'final_boxscore' and source.get('status') == 'final'
                and str(source.get('source_event_id')) == str(game.get('game_id'))
                and cutoff and captured and timestamp(game.get('start_utc')) and timestamp(game.get('start_utc')) <= captured <= cutoff
                and type(points) is int and 0 <= points <= 100):
            usable.append(p)
    return sorted(usable, key=lambda p: (-p['stats']['points'], str(p['id'])))


def generate_recap(bundle):
    material = json.dumps(bundle, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    digest = hashlib.sha256(material.encode()).hexdigest()
    teams = bundle.get('teams', [])
    out = {'engine_version': VERSION, 'input_sha256': digest, 'headline': '', 'lede': '',
           'paragraphs': [], 'candidates': [], 'claims': [], 'selected': None, 'gate': 'blocked'}
    if len(teams) == 2 and all(type(t.get('score')) is int and t['score'] >= 0 and t.get('name') for t in teams):
        a, b = teams
        ids = [s.get('id') for s in bundle.get('sources', []) if s.get('id', '').startswith('scoreboard:')]
        # Older fixture consumers may supply a differently named source.
        if not ids:
            ids = [s.get('id') for s in bundle.get('sources', []) if s.get('kind') != 'final_boxscore']
        out['claims'].append({'type': 'result', 'teams': [{'id': t.get('id'), 'score': t['score']} for t in teams], 'source_ids': ids})
        fallback = {'angle_id': 'final_result', 'candidate_type': 'fallback', 'priority': 0,
                    'data_quality': 'score_only', 'evidence_ids': ids, 'reason': 'Final score',
                    'entities': [a.get('id'), b.get('id')], 'template_key': 'result'}
        out['candidates'].append(fallback)
        out['selected'] = 'final_result'
        if a['score'] == b['score']:
            out['headline'] = f"{a['name']} and {b['name']} tie {a['score']}-{b['score']}"
            out['lede'] = f"{a['name']} and {b['name']} finished level at {a['score']}-{b['score']}."
        else:
            winner, loser = sorted(teams, key=lambda t: t['score'], reverse=True)
            score = f"{winner['score']}-{loser['score']}"
            margin = winner['score'] - loser['score']
            out['headline'] = f"{winner['name']} defeat {loser['name']}, {score}"
            out['lede'] = f"{winner['name']} defeated {loser['name']} {score}, a {margin}-point margin."
            for player in _players(bundle):
                points = player['stats']['points']
                # A headline needs a notable performance from the winning team.
                rebounds = player['stats'].get('rebounds')
                double_double = type(rebounds) is int and rebounds >= 10 and 20 <= points < 30
                if (points < 30 and not double_double) or player['team_id'] != winner['id']:
                    continue
                candidate = {'angle_id': 'player:' + str(player['id']), 'candidate_type': 'standout_player',
                             'priority': 30, 'data_quality': 'final_boxscore',
                             'evidence_ids': [player['source_id']], 'entities': [player['id'], player['team_id']],
                             'facts': {'points': points, **({'rebounds': rebounds} if double_double else {})},
                             'reason': '20 points and 10 rebounds' if double_double else '30 or more points in a win',
                             'template_key': 'nba_double_double' if double_double else 'nba_points'}
                out['candidates'].append(candidate)
                if out['selected'] == 'final_result':
                    out['selected'] = candidate['angle_id']
                    if double_double:
                        out['headline'] = f"{player['name']} posts a double-double as {winner['name']} beat {loser['name']}"
                        out['lede'] = f"{player['name']} had {points} points and {rebounds} rebounds as {winner['name']} defeated {loser['name']} {score}, a {margin}-point margin."
                    else:
                        out['headline'] = f"{player['name']} scores {points} as {winner['name']} beat {loser['name']}"
                        out['lede'] = f"{player['name']} scored {points} points as {winner['name']} defeated {loser['name']} {score}, a {margin}-point margin."
                    out['claims'].append({'type': 'player_stat', 'player_id': player['id'], 'team_id': player['team_id'],
                                          'game_id': player['game_id'], 'stat': 'points', 'value': points,
                                          'source_id': player['source_id']})
                    if double_double:
                        out['claims'].append({'type': 'player_stat', 'player_id': player['id'], 'team_id': player['team_id'],
                                              'game_id': player['game_id'], 'stat': 'rebounds', 'value': rebounds,
                                              'source_id': player['source_id']})
        if bundle.get('game', {}).get('league') == 'nfl' and a['score'] != b['score']:
            winner = max(teams, key=lambda t: t['score'])
            for player in sorted(bundle.get('players', []), key=lambda x: str(x.get('id', ''))):
                src = next((x for x in bundle.get('sources', []) if x.get('id') == player.get('source_id')), {})
                captured = timestamp(src.get('captured_at')); cutoff = timestamp(bundle.get('as_of_utc'))
                yards = player.get('stats', {}).get('passing_yards'); touchdowns = player.get('stats', {}).get('passing_touchdowns')
                if (player.get('id') and player.get('name') and player.get('team_id') == winner['id']
                        and player.get('publisher_team_id') == winner.get('publisher_team_id') and player.get('publisher_team_id')
                        and player.get('game_id') == bundle['game']['game_id']
                        and src.get('kind') == 'final_boxscore' and src.get('status') == 'final'
                        and str(src.get('source_event_id')) == str(bundle['game']['game_id'])
                        and src.get('teams') == {str(t.get('publisher_team_id')): t['score'] for t in teams}
                        and cutoff and captured and timestamp(bundle['game'].get('start_utc')) and timestamp(bundle['game'].get('start_utc')) <= captured <= cutoff and type(yards) is int and yards >= 200
                        and type(touchdowns) is int and touchdowns >= 1):
                    suffix = '' if touchdowns == 1 else 's'
                    out['paragraphs'].append(f"{player['name']} threw for {yards} yards and {touchdowns} touchdown{suffix}.")
                    out['claims'].append({'type': 'passing_line', 'player_id': player['id'], 'team_id': player['team_id'],
                                          'game_id': player['game_id'], 'yards': yards, 'touchdowns': touchdowns,
                                          'source_id': player['source_id']})
                    out['candidates'].append({'angle_id': 'passing:' + str(player['id']),
                                              'candidate_type': 'supporting_player', 'priority': -1,
                                              'data_quality': 'final_boxscore', 'entities': [player['id'], player['team_id']],
                                              'facts': {'yards': yards, 'touchdowns': touchdowns},
                                              'evidence_ids': [player['source_id']], 'reason': 'Passing line supports the result',
                                              'template_key': 'nfl_passing'})
                    break
        if bundle.get('game', {}).get('league') == 'nfl' and a['score'] != b['score']:
            winner, loser = sorted(teams, key=lambda t: t['score'], reverse=True)
            candidates = []
            for player in bundle.get('players', []):
                src = next((x for x in bundle.get('sources', []) if x.get('id') == player.get('source_id')), {})
                captured = timestamp(src.get('captured_at')); cutoff = timestamp(bundle.get('as_of_utc')); start = timestamp(bundle['game'].get('start_utc'))
                if not (player.get('id') and player.get('name') and player.get('team_id') == winner['id']
                        and player.get('publisher_team_id') == winner.get('publisher_team_id') and player.get('publisher_team_id')
                        and player.get('game_id') == bundle['game']['game_id'] and src.get('kind') == 'final_boxscore'
                        and src.get('status') == 'final' and str(src.get('source_event_id')) == str(bundle['game']['game_id'])
                        and src.get('teams') == {str(t.get('publisher_team_id')): t['score'] for t in teams}
                        and start and cutoff and captured and start <= captured <= cutoff):
                    continue
                for stat in ('rushing_yards', 'receiving_yards'):
                    yards = player.get('stats', {}).get(stat)
                    if type(yards) is int and yards >= 100:
                        candidates.append((yards, stat, str(player['id']), player))
            candidates.sort(key=lambda x: (-x[0], x[1], x[2]))
            for yards, stat, _, player in candidates:
                angle_id = 'yardage:' + stat + ':' + str(player['id'])
                out['candidates'].append({'angle_id': angle_id, 'candidate_type': 'standout_player', 'priority': 30,
                                          'data_quality': 'final_boxscore', 'entities': [player['id'], player['team_id']],
                                          'facts': {stat: yards}, 'evidence_ids': [player['source_id']],
                                          'reason': '100 or more yards in a win', 'template_key': stat})
                if out['selected'] == 'final_result':
                    out['selected'] = angle_id
                    unit = 'rushing yards' if stat == 'rushing_yards' else 'receiving yards'
                    verb = 'runs for' if stat == 'rushing_yards' else 'has'
                    past = 'ran for' if stat == 'rushing_yards' else 'had'
                    headline_unit = 'yards' if stat == 'rushing_yards' else unit
                    out['headline'] = f"{player['name']} {verb} {yards} {headline_unit} as {winner['name']} defeat {loser['name']}"
                    out['lede'] = f"{player['name']} {past} {yards} {unit} as {winner['name']} defeated {loser['name']} {winner['score']}-{loser['score']}."
                    out['claims'].append({'type': 'nfl_yards', 'player_id': player['id'], 'team_id': player['team_id'],
                                          'game_id': player['game_id'], 'stat': stat, 'value': yards, 'source_id': player['source_id']})
        event = late_lead(bundle)
        if event:
            winner = next(t for t in teams if t['id'] == event['winner_id'])
            loser = next(t for t in teams if t['id'] == event['loser_id'])
            player_claims = [c for c in out['claims'] if c['type'] == 'player_stat']
            out['claims'] = [c for c in out['claims'] if c['type'] == 'result']
            out['paragraphs'] = []
            out['claims'].append(event)
            if event['type'] == 'late_lead':
                out['selected'] = 'late_lead:' + event['event_id']
                out['headline'] = f"{winner['name']} take the lead in the fourth quarter, defeat {loser['name']}"
                out['lede'] = f"{winner['name']} moved ahead in the fourth quarter and never trailed again, defeating {loser['name']} {winner['score']}-{loser['score']}."
                reason = 'Regained a lead in the fourth quarter and never trailed again'
            else:
                out['selected'] = 'scoring_run:' + event['start_event_id']
                period_text = {(3, 3): 'in the third quarter', (4, 4): 'in the fourth quarter',
                               (3, 4): 'across the third and fourth quarters'}[(event['start_period'], event['end_period'])]
                out['headline'] = f"{winner['name']} score {event['points']} straight points in win over {loser['name']}"
                out['lede'] = f"{winner['name']} scored {event['points']} straight points {period_text} in a {winner['score']}-{loser['score']} win over {loser['name']}."
                reason = 'Unanswered scoring run of at least 10 points'
            out['candidates'].append({'angle_id': out['selected'], 'candidate_type': 'game_swung', 'priority': 50,
                                      'data_quality': 'complete_pbp', 'evidence_ids': [event['source_id']],
                                      'entities': [winner['id'], loser['id']], 'facts': dict(event),
                                      'reason': reason, 'template_key': event['type']})
            if player_claims:
                first = player_claims[0]
                player = next(p for p in bundle['players'] if p['id'] == first['player_id'])
                rebounds = next((c['value'] for c in player_claims if c['stat'] == 'rebounds'), None)
                if rebounds is None:
                    out['paragraphs'].append(f"{player['name']} scored {first['value']} points.")
                else:
                    out['paragraphs'].append(f"{player['name']} had {first['value']} points and {rebounds} rebounds.")
                out['claims'].append({'type': 'supporting_nba_line', 'player_id': first['player_id'],
                                      'game_id': first['game_id'], 'team_id': first['team_id'],
                                      'source_id': first['source_id'], 'points': first['value'], 'rebounds': rebounds})
        segments = bundle.get('segments', {})
        period_scores = segments.get('period_scores', {})
        source = next((x for x in bundle.get('sources', []) if x.get('id') == segments.get('source_id')), {})
        cutoff = timestamp(bundle.get('as_of_utc')); captured = timestamp(source.get('captured_at'))
        if (bundle.get('game', {}).get('league') == 'nba' and source.get('kind') == 'final_boxscore'
                and source.get('status') == 'final' and str(source.get('source_event_id')) == str(bundle['game']['game_id'])
                and cutoff and captured and timestamp(bundle['game'].get('start_utc')) and timestamp(bundle['game'].get('start_utc')) <= captured <= cutoff
                and source.get('teams') == {str(t.get('publisher_team_id')): t['score'] for t in teams}
                and all(t.get('publisher_team_id') in period_scores and len(period_scores[t['publisher_team_id']]) >= 4
                        and all(type(n) is int and n >= 0 for n in period_scores[t['publisher_team_id']])
                        and sum(period_scores[t['publisher_team_id']]) == t['score'] for t in teams)):
            halves = {t['id']: sum(period_scores[t['publisher_team_id']][:2]) for t in teams}
            if halves[a['id']] != halves[b['id']]:
                leader, trailing = sorted(teams, key=lambda t: halves[t['id']], reverse=True)
                out['paragraphs'].append(f"{leader['name']} led {halves[leader['id']]}-{halves[trailing['id']]} at halftime.")
                out['claims'].append({'type': 'halftime_score', 'leader_id': leader['id'], 'trailing_id': trailing['id'],
                                      'leader_score': halves[leader['id']], 'trailing_score': halves[trailing['id']],
                                      'source_id': segments['source_id']})
        out['candidates'].sort(key=lambda c: (-c['priority'], c['angle_id']))
    out['audit'] = audit(bundle, out)
    if all(out['audit'].values()):
        out['gate'] = 'eligible' if len(out['claims']) > 1 else 'eligible_score_only'
    return out
