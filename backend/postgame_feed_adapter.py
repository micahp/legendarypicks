"""Produce traceable, offline cards from independently audited claims."""
from postgame_story_engine import VERSION
from postgame_story_audit import audit


def build_feed(bundle, recap):
    if recap.get('gate') not in ('eligible', 'eligible_score_only') or not all(audit(bundle, recap).values()) or not all(recap.get('audit', {}).values()):
        return []
    game = bundle['game']; teams = bundle['teams']; ids = [s['id'] for s in bundle['sources']]
    base = {'league': game['league'], 'game_id': game['game_id'], 'team_ids': [t['id'] for t in teams], 'daypart': 'postgame', 'asset_refs': [],
            'fact_ids': ids, 'source_ids': ids, 'generated_at_utc': bundle['as_of_utc'],
            'as_of_utc': bundle['as_of_utc'], 'generator_version': VERSION, 'audit_status': recap['gate'],
            'render_context': 'homepage'}
    scores = {t['id']: t['score'] for t in teams}
    posts = []

    def add(kind, headline, body, numerics, graphic=None, source_ids=None):
        posts.append({**base, 'source_ids': source_ids or ids, 'fact_ids': source_ids or ids,
                      'post_id': f"{game['league']}:{game['game_id']}:{kind}:v1", 'kind': kind,
                      'headline': headline, 'body': body, 'numerics': numerics, 'graphic_spec': graphic})

    add('final_score', 'Final score', f"{teams[0]['name']} {teams[0]['score']}, {teams[1]['name']} {teams[1]['score']}.", scores)
    add('chart', 'Final score comparison', 'Points in one completed game.', scores,
        {'type': 'bars', 'unit': 'points', 'sample': 'one completed game', 'source_ids': ids, 'as_of_utc': bundle['as_of_utc']})
    if recap['gate'] == 'eligible':
        add('game_recap', recap['headline'], ' '.join([recap['lede']] + recap['paragraphs']), scores)
        posts[-1]['game_url'] = f"/game/{game['league']}/{game['game_id']}"
    if teams[0]['score'] != teams[1]['score']:
        winner = max(teams, key=lambda t: t['score']); margin = abs(teams[0]['score'] - teams[1]['score'])
        add('stat_nugget', f"{winner['name']} win by {margin}", f"The final margin was {margin} points.", {'margin_points': margin})
    pc = [c for c in recap.get('claims', []) if c.get('type') == 'player_stat']
    if pc:
        player = next(p for p in bundle['players'] if p['id'] == pc[0]['player_id'])
        stats = {c['stat']: c['value'] for c in pc}
        body = f"{player['name']} scored {stats['points']} points."
        if 'rebounds' in stats:
            body = f"{player['name']} finished with {stats['points']} points and {stats['rebounds']} rebounds."
        add('player_spotlight', player['name'], body, stats, source_ids=[pc[0]['source_id']])
    supporting = next((c for c in recap.get('claims', []) if c.get('type') == 'supporting_nba_line'), None)
    if supporting:
        player = next(p for p in bundle['players'] if p['id'] == supporting['player_id'])
        stats = {'points': supporting['points']}
        body = f"{player['name']} scored {supporting['points']} points."
        if supporting.get('rebounds') is not None:
            stats['rebounds'] = supporting['rebounds']
            body = f"{player['name']} had {supporting['points']} points and {supporting['rebounds']} rebounds."
        add('player_spotlight', player['name'], body, stats, source_ids=[supporting['source_id']])
    passing = next((c for c in recap.get('claims', []) if c.get('type') == 'passing_line'), None)
    yardage = next((c for c in recap.get('claims', []) if c.get('type') == 'nfl_yards'), None)
    if yardage:
        player = next(p for p in bundle['players'] if p['id'] == yardage['player_id'])
        label = 'rushing yards' if yardage['stat'] == 'rushing_yards' else 'receiving yards'
        add('player_spotlight', player['name'], f"{player['name']} had {yardage['value']} {label}.",
            {yardage['stat']: yardage['value']}, source_ids=[yardage['source_id']])
    elif passing:
        player = next(p for p in bundle['players'] if p['id'] == passing['player_id'])
        add('player_spotlight', player['name'], recap['paragraphs'][0],
            {'passing_yards': passing['yards'], 'passing_touchdowns': passing['touchdowns']},
            source_ids=[passing['source_id']])
    return posts


def rank_feed(posts, favorite_teams=(), as_of_utc=None):
    """Greedy deterministic diversity ranking; no hidden profile or eligibility override."""
    from postgame_story_audit import timestamp
    now = timestamp(as_of_utc)
    if not now:
        raise ValueError('ranking requires an explicit as-of time')
    remaining = []
    seen = set()
    for post in posts:
        captured = timestamp(post.get('as_of_utc'))
        if (post.get('audit_status') not in ('eligible', 'eligible_score_only') or not captured
                or captured > now or post.get('post_id') in seen):
            continue
        seen.add(post['post_id']); remaining.append(post)
    ranked = []; game_counts = {}; kind_counts = {}
    while remaining:
        options = []
        for post in remaining:
            age_hours = max(0, (now - timestamp(post['as_of_utc'])).total_seconds() / 3600)
            factors = {'recency': max(0, 15 - int(age_hours // 12)),
                       'favorite_team_match': 15 if set(post.get('team_ids', ())) & set(favorite_teams) else 0,
                       'event_impact': {'game_recap': 14, 'player_spotlight': 12, 'final_score': 10, 'stat_nugget': 8, 'chart': 5}.get(post['kind'], 0),
                       'supporting_facts_quality': 10 if post['audit_status'] == 'eligible' else 5,
                       'format_diversity': max(0, 12 - 4 * kind_counts.get(post['kind'], 0)),
                       'duplicate_penalty': -25 * game_counts.get((post['league'], post['game_id']), 0)}
            options.append((sum(factors.values()), post['post_id'], post, factors))
        options.sort(key=lambda x: (-x[0], x[1]))
        score, _, post, factors = options[0]
        ranked.append({**post, 'rank_version': 'postgame-feed-rank-v1', 'rank_score': score, 'rank_components': factors})
        game_key = (post['league'], post['game_id'])
        game_counts[game_key] = game_counts.get(game_key, 0) + 1
        kind_counts[post['kind']] = kind_counts.get(post['kind'], 0) + 1
        remaining.remove(post)
    return ranked
