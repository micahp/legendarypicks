"""Independently recompute every supported postgame claim and its wording."""
import datetime as dt
import hashlib
import json
import re


def timestamp(value):
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


def _audit_late_lead(bundle, claim):
    """Recompute sequence integrity and the claimed lead without renderer logic."""
    teams = bundle.get('teams', []); game = bundle.get('game', {}); events = bundle.get('events', [])
    desc = bundle.get('event_sequence')
    if len(teams) != 2 or not isinstance(desc, dict) or desc.get('source_id') != claim.get('source_id'):
        return False
    src = next((s for s in bundle.get('sources', []) if s.get('id') == claim.get('source_id')), {})
    totals = {str(t.get('publisher_team_id')): t.get('score') for t in teams}
    captured, cutoff, start = timestamp(src.get('captured_at')), timestamp(bundle.get('as_of_utc')), timestamp(game.get('start_utc'))
    if (len(totals) != 2 or any(not t.get('publisher_team_id') for t in teams) or src.get('kind') != 'final_pbp'
            or src.get('status') != 'final' or src.get('coverage') != 'complete' or src.get('teams') != totals
            or str(src.get('source_event_id')) != str(game.get('game_id')) or not captured or not cutoff or not start
            or not start <= captured <= cutoff or src.get('event_count') != len(events) or not events):
        return False
    actual_hash = hashlib.sha256(json.dumps(events, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if actual_hash != src.get('events_sha256') or events[0].get('kind') != 'start' or events[-1].get('kind') != 'end':
        return False
    if events[0].get('period') != 1 or events[0].get('scores') != {k: 0 for k in totals} or events[-1].get('scores') != totals:
        return False
    if events[-1].get('period', 0) < 4 or events[-1].get('clock_seconds') != 0:
        return False
    if not {1, 2, 3}.issubset({e.get('period') for e in events if e.get('kind') == 'period_end' and e.get('clock_seconds') == 0}):
        return False
    previous = None; seen = set()
    for e in events:
        seq, period, clock, scores = e.get('sequence'), e.get('period'), e.get('clock_seconds'), e.get('scores', {})
        if (not e.get('id') or e['id'] in seen or type(seq) is not int or type(period) is not int or period < 1
                or type(clock) not in (int, float) or not 0 <= clock <= (720 if game.get('league') == 'nba' else 900)
                or set(scores) != set(totals) or any(type(v) is not int or v < 0 for v in scores.values())):
            return False
        seen.add(e['id'])
        if previous:
            if seq <= previous['sequence'] or period < previous['period'] or (period == previous['period'] and clock > previous['clock_seconds']):
                return False
            increments = [scores[k] - previous['scores'][k] for k in totals]
            if any(x < 0 for x in increments) or sum(x > 0 for x in increments) > 1 or max(increments) > (4 if game.get('league') == 'nba' else 8):
                return False
            if any(increments) and e.get('kind') != 'score':
                return False
        previous = e
    if teams[0]['score'] == teams[1]['score']:
        return False
    winner, loser = sorted(teams, key=lambda t: t['score'], reverse=True)
    if claim.get('winner_id') != winner['id'] or claim.get('loser_id') != loser['id']:
        return False
    win, lose = winner['publisher_team_id'], loser['publisher_team_id']
    if claim.get('type') == 'scoring_run':
        runs = []; current_run = None
        for before, after in zip(events, events[1:]):
            differences = {k: after['scores'][k] - before['scores'][k] for k in totals}
            scorer = next((k for k in totals if differences[k] > 0), None)
            if scorer is None:
                continue
            if current_run and current_run['team'] == scorer:
                current_run['points'] += differences[scorer]; current_run['end'] = after
            else:
                if current_run:
                    runs.append(current_run)
                current_run = {'team': scorer, 'points': differences[scorer], 'start': after, 'end': after}
        if current_run:
            runs.append(current_run)
        runs = [r for r in runs if r['team'] == win and r['points'] >= 10
                and r['start']['period'] in (3, 4) and r['end']['period'] in (3, 4)]
        if not runs:
            return False
        best = sorted(runs, key=lambda r: (-r['points'], r['start']['sequence']))[0]
        return (claim.get('points') == best['points'] and claim.get('start_event_id') == best['start']['id']
                and claim.get('end_event_id') == best['end']['id'] and claim.get('start_period') == best['start']['period']
                and claim.get('end_period') == best['end']['period'])
    for i, event in enumerate(events):
        if event['id'] != claim.get('event_id') or not i or event['period'] != 4:
            continue
        earlier_deficit = any(e['period'] >= 3 and e['scores'][win] < e['scores'][lose] for e in events[:i])
        lead_change = events[i-1]['scores'][win] <= events[i-1]['scores'][lose] and event['scores'][win] > event['scores'][lose]
        never_behind = all(e['scores'][win] >= e['scores'][lose] for e in events[i:])
        return earlier_deficit and lead_change and never_behind
    return False


def audit(bundle, recap):
    teams = bundle.get('teams', [])
    sources = {x.get('id'): x for x in bundle.get('sources', []) if x.get('id')}
    cutoff = timestamp(bundle.get('as_of_utc'))
    start = timestamp(bundle.get('game', {}).get('start_utc'))
    game = bundle.get('game', {})
    valid = (len(teams) == 2 and all(type(t.get('score')) is int and t['score'] >= 0
             and t.get('id') and t.get('name') for t in teams) and teams[0]['id'] != teams[1]['id'])
    detail = str(game.get('status_detail') or '').lower()
    contradictory = bool(detail and not detail.startswith('final')) or any(x in detail for x in ('suspend', 'postpon', 'cancel', 'retir', 'forfeit', 'walkover'))
    final = (game.get('league') in ('nba', 'nfl') and game.get('status') == 'final' and not contradictory
             and not (game.get('league') == 'nba' and len(teams) == 2 and teams[0].get('score') == teams[1].get('score')))
    claims = recap.get('claims', [])
    safe = bool(cutoff and start and cutoff >= start and claims)
    recomputed = bool(claims and claims[0].get('type') == 'result')
    expected_paragraphs = []
    for claim in claims:
        ids = claim.get('source_ids', []) if claim.get('type') == 'result' else [claim.get('source_id')]
        if not ids:
            safe = False
        for sid in ids:
            src = sources.get(sid, {})
            captured = timestamp(src.get('captured_at'))
            if not captured or not cutoff or not start or captured < start or captured > cutoff or (src.get('source_event_id') and str(src['source_event_id']) != str(game.get('game_id'))):
                safe = False
        if claim.get('type') == 'result':
            recomputed &= valid and claim.get('teams') == [{'id': t.get('id'), 'score': t.get('score')} for t in teams]
        elif claim.get('type') == 'player_stat':
            matches = [p for p in bundle.get('players', []) if p.get('id') == claim.get('player_id')
                       and p.get('game_id') == game.get('game_id') == claim.get('game_id')
                       and p.get('team_id') == claim.get('team_id') and p.get('team_id') in {t.get('id') for t in teams}
                       and p.get('source_id') == claim.get('source_id')
                       and p.get('publisher_team_id') and any(t.get('id') == p.get('team_id') and t.get('publisher_team_id') == p.get('publisher_team_id') for t in teams)
                       and p.get('stats', {}).get(claim.get('stat')) == claim.get('value')]
            src = sources.get(claim.get('source_id'), {})
            recomputed &= len(matches) == 1 and claim.get('stat') in ('points', 'rebounds') and src.get('kind') == 'final_boxscore' and src.get('status') == 'final' and str(src.get('source_event_id')) == str(game.get('game_id')) and src.get('teams') == {str(t.get('publisher_team_id')): t.get('score') for t in teams}
        elif claim.get('type') == 'supporting_nba_line':
            src = sources.get(claim.get('source_id'), {})
            matching = [p for p in bundle.get('players', []) if p.get('id') == claim.get('player_id')
                        and p.get('game_id') == game.get('game_id') == claim.get('game_id')
                        and p.get('team_id') == claim.get('team_id') and p.get('source_id') == claim.get('source_id')
                        and p.get('stats', {}).get('points') == claim.get('points')
                        and (claim.get('rebounds') is None or p.get('stats', {}).get('rebounds') == claim.get('rebounds'))
                        and any(t.get('id') == p.get('team_id') and t.get('publisher_team_id') == p.get('publisher_team_id') and p.get('publisher_team_id') for t in teams)]
            valid_player = (len(matching) == 1 and game.get('league') == 'nba' and type(claim.get('points')) is int
                            and src.get('kind') == 'final_boxscore' and src.get('status') == 'final'
                            and str(src.get('source_event_id')) == str(game.get('game_id'))
                            and src.get('teams') == {str(t.get('publisher_team_id')): t.get('score') for t in teams})
            recomputed &= valid_player
            if valid_player:
                p = matching[0]
                if claim.get('rebounds') is not None:
                    expected_paragraphs.append(f"{p['name']} had {claim['points']} points and {claim['rebounds']} rebounds.")
                else:
                    expected_paragraphs.append(f"{p['name']} scored {claim['points']} points.")
        elif claim.get('type') == 'nfl_yards':
            src = sources.get(claim.get('source_id'), {})
            matching = [p for p in bundle.get('players', []) if p.get('id') == claim.get('player_id')
                        and p.get('game_id') == game.get('game_id') == claim.get('game_id')
                        and p.get('team_id') == claim.get('team_id') and p.get('source_id') == claim.get('source_id')
                        and p.get('stats', {}).get(claim.get('stat')) == claim.get('value')
                        and any(t.get('id') == p.get('team_id') and t.get('publisher_team_id') == p.get('publisher_team_id') and p.get('publisher_team_id') for t in teams)]
            recomputed &= (len(matching) == 1 and game.get('league') == 'nfl' and claim.get('stat') in ('rushing_yards', 'receiving_yards')
                           and type(claim.get('value')) is int and claim['value'] >= 100
                           and src.get('kind') == 'final_boxscore' and src.get('status') == 'final'
                           and str(src.get('source_event_id')) == str(game.get('game_id'))
                           and src.get('teams') == {str(t.get('publisher_team_id')): t.get('score') for t in teams})
        elif claim.get('type') in ('late_lead', 'scoring_run'):
            recomputed &= _audit_late_lead(bundle, claim)
        elif claim.get('type') == 'passing_line':
            matching = [p for p in bundle.get('players', []) if p.get('id') == claim.get('player_id')
                        and p.get('team_id') == claim.get('team_id') and p.get('game_id') == game.get('game_id') == claim.get('game_id')
                        and p.get('source_id') == claim.get('source_id') and p.get('stats', {}).get('passing_yards') == claim.get('yards')
                        and p.get('stats', {}).get('passing_touchdowns') == claim.get('touchdowns')
                        and any(t.get('id') == p.get('team_id') and t.get('publisher_team_id') == p.get('publisher_team_id') and p.get('publisher_team_id') for t in teams)]
            src = sources.get(claim.get('source_id'), {})
            valid_line = (len(matching) == 1 and game.get('league') == 'nfl' and src.get('kind') == 'final_boxscore'
                          and src.get('status') == 'final' and str(src.get('source_event_id')) == str(game.get('game_id'))
                          and src.get('teams') == {str(t.get('publisher_team_id')): t.get('score') for t in teams}
                          and type(claim.get('yards')) is int and type(claim.get('touchdowns')) is int)
            if valid_line:
                suffix = '' if claim['touchdowns'] == 1 else 's'
                expected_paragraphs.append(f"{matching[0]['name']} threw for {claim['yards']} yards and {claim['touchdowns']} touchdown{suffix}.")
            recomputed &= valid_line
        elif claim.get('type') == 'halftime_score':
            seg = bundle.get('segments', {}); periods = seg.get('period_scores', {})
            src = sources.get(claim.get('source_id'), {})
            valid_periods = (valid and seg.get('source_id') == claim.get('source_id') and src.get('kind') == 'final_boxscore'
                and src.get('status') == 'final' and str(src.get('source_event_id')) == str(game.get('game_id'))
                and src.get('teams') == {str(t.get('publisher_team_id')): t.get('score') for t in teams}
                and all(t.get('publisher_team_id') in periods and len(periods[t['publisher_team_id']]) >= 4
                        and all(type(n) is int and n >= 0 for n in periods[t['publisher_team_id']])
                        and sum(periods[t['publisher_team_id']]) == t['score'] for t in teams))
            if valid_periods:
                halves = {t['id']: sum(periods[t['publisher_team_id']][:2]) for t in teams}
                leader, trailer = sorted(teams, key=lambda t: halves[t['id']], reverse=True)
                recomputed &= (halves[leader['id']] > halves[trailer['id']] and claim.get('leader_id') == leader['id']
                               and claim.get('trailing_id') == trailer['id'] and claim.get('leader_score') == halves[leader['id']]
                               and claim.get('trailing_score') == halves[trailer['id']])
                expected_paragraphs.append(f"{leader['name']} led {halves[leader['id']]}-{halves[trailer['id']]} at halftime.")
            else:
                recomputed = False
        else:
            recomputed = False
    if sorted(recap.get('paragraphs', [])) != sorted(expected_paragraphs):
        recomputed = False
    correct = False
    if valid and final:
        a, b = teams
        if a['score'] == b['score']:
            correct = (recap.get('headline') == f"{a['name']} and {b['name']} tie {a['score']}-{b['score']}" and recap.get('lede') == f"{a['name']} and {b['name']} finished level at {a['score']}-{b['score']}.")
        else:
            winner, loser = sorted(teams, key=lambda t: t['score'], reverse=True)
            score = f"{winner['score']}-{loser['score']}"; margin = winner['score'] - loser['score']
            pc = [c for c in claims if c.get('type') == 'player_stat']
            lead = [c for c in claims if c.get('type') == 'late_lead']
            runs = [c for c in claims if c.get('type') == 'scoring_run']
            yardage = [c for c in claims if c.get('type') == 'nfl_yards']
            if len(lead) == 1 and not pc:
                correct = (recap.get('headline') == f"{winner['name']} take the lead in the fourth quarter, defeat {loser['name']}"
                           and recap.get('lede') == f"{winner['name']} moved ahead in the fourth quarter and never trailed again, defeating {loser['name']} {score}.")
            elif len(runs) == 1 and not pc:
                run = runs[0]; periods = (run.get('start_period'), run.get('end_period'))
                period_text = {(3, 3): 'in the third quarter', (4, 4): 'in the fourth quarter',
                               (3, 4): 'across the third and fourth quarters'}.get(periods)
                if period_text:
                    correct = (recap.get('headline') == f"{winner['name']} score {run['points']} straight points in win over {loser['name']}"
                               and recap.get('lede') == f"{winner['name']} scored {run['points']} straight points {period_text} in a {score} win over {loser['name']}.")
            elif len(yardage) == 1 and not pc:
                claim = yardage[0]
                people = [p for p in bundle.get('players', []) if p.get('id') == claim.get('player_id')]
                if len(people) == 1 and claim.get('team_id') == winner['id'] and claim.get('stat') in ('rushing_yards', 'receiving_yards'):
                    name = people[0]['name']; yards = claim.get('value'); rushing = claim['stat'] == 'rushing_yards'
                    verb = 'runs for' if rushing else 'has'; past = 'ran for' if rushing else 'had'
                    unit = 'rushing yards' if rushing else 'receiving yards'; headline_unit = 'yards' if rushing else unit
                    correct = (recap.get('headline') == f"{name} {verb} {yards} {headline_unit} as {winner['name']} defeat {loser['name']}"
                               and recap.get('lede') == f"{name} {past} {yards} {unit} as {winner['name']} defeated {loser['name']} {score}.")
            elif len(pc) in (1, 2):
                players = [p for p in bundle.get('players', []) if p.get('id') == pc[0].get('player_id')]
                if len(players) == 1:
                    name = players[0].get('name'); points = pc[0].get('value')
                    if len(pc) == 2 and pc[0].get('stat') == 'points' and pc[1].get('stat') == 'rebounds' and pc[1].get('player_id') == pc[0].get('player_id') and pc[1].get('team_id') == pc[0].get('team_id'):
                        rebounds = pc[1].get('value')
                        correct = (type(points) is int and points >= 10 and type(rebounds) is int and rebounds >= 10 and pc[0].get('team_id') == winner['id'] and recap.get('headline') == f"{name} posts a double-double as {winner['name']} beat {loser['name']}" and recap.get('lede') == f"{name} had {points} points and {rebounds} rebounds as {winner['name']} defeated {loser['name']} {score}, a {margin}-point margin.")
                    elif len(pc) == 1 and pc[0].get('stat') == 'points':
                        correct = (pc[0].get('team_id') == winner['id'] and recap.get('headline') == f"{name} scores {points} as {winner['name']} beat {loser['name']}" and recap.get('lede') == f"{name} scored {points} points as {winner['name']} defeated {loser['name']} {score}, a {margin}-point margin.")
            elif not pc:
                correct = (recap.get('headline') == f"{winner['name']} defeat {loser['name']}, {score}" and recap.get('lede') == f"{winner['name']} defeated {loser['name']} {score}, a {margin}-point margin.")
    text = ' '.join([recap.get('headline', ''), recap.get('lede', '')] + recap.get('paragraphs', []))
    unsupported = bool(re.search(r'\b(upset|comeback|dead last|historic|record-breaking|blowout|overtime)\b', text, re.I))
    return {'final_status': final, 'valid_scores_and_teams': valid, 'cutoff_safe_sources': safe,
            'result_and_margin_recomputed': correct, 'claims_recomputed': bool(recomputed),
            'no_unsupported_hook': not unsupported}
