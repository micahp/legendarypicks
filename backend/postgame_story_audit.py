"""Independently recompute every supported postgame claim and its wording."""
import datetime as dt
import re


def timestamp(value):
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


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
                valid_line &= recap.get('paragraphs') == [f"{matching[0]['name']} threw for {claim['yards']} yards and {claim['touchdowns']} touchdown{suffix}."]
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
                recomputed &= recap.get('paragraphs') == [f"{leader['name']} led {halves[leader['id']]}-{halves[trailer['id']]} at halftime."]
            else:
                recomputed = False
        else:
            recomputed = False
    if not any(c.get('type') in ('halftime_score', 'passing_line') for c in claims) and recap.get('paragraphs'):
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
            if len(pc) in (1, 2):
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
