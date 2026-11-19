"""Week 10 three-arm evaluation, computed from the batch box scores and the frozen week 10 actuals (read-only DB).

Arms: A-control (no field, no PBV1), B-field (participation field), C-field-pbv1 (field plus PBV1 coupling).
Inputs: DATA/<game>/runs/<arm>/*.boxscores.jsonl. Writes OUT/*.json and OUT/traces/*.jsonl.gz.
"""
import collections, glob, gzip, json, math, os, sqlite3, sys

DATA, OUT, DB = sys.argv[1], sys.argv[2], sys.argv[3]
ARMS = ['A-control', 'B-field', 'C-field-pbv1']
TRACE_SEEDS = (300001, 300002, 300003)
NORM = {'WSH': 'WAS', 'LAR': 'LA'}  # boundary: nflverse codes everywhere (the DB schedule uses WSH and LAR)


def norm(team):
    return NORM.get(team, team)


def load_games(game, arm):
    recs = []
    for path in sorted(glob.glob(os.path.join(DATA, game, 'runs', arm, '*.boxscores.jsonl'))):
        for line in open(path):
            r = json.loads(line)
            if r.get('type') == 'game':
                recs.append(r)
    return recs


def final_points(rec):
    pts = {k: sum(v.values()) for k, v in rec['points_by_period'].items()}
    return {norm(k): v for k, v in pts.items()}


def players_of(rec):
    """{gsis: {'team', 'carries', 'targets', 'rec', 'rush_yds', 'rec_yds'}} for one simulated game."""
    out = {}
    for p in rec['players']:
        out[p['stable_player_id']] = {
            'team': norm(p['team']), 'name': p['name'], 'pos': p['position'],
            'carries': p['rushing']['att'], 'targets': p['receiving']['tgt'], 'rec': p['receiving']['rec'],
            'rush_yds': p['rushing']['yds'], 'rec_yds': p['receiving']['yds'],
            'pass_att': p['passing']['att'], 'snaps': p.get('snaps') or 0}
    return out


def actual_games():
    """Actual week 10 player lines and team totals from the frozen DB, keyed by game and GSIS id."""
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    cur = con.cursor()
    finals = {}
    for gid, home, away, hs, as_ in cur.execute(
            "select game_id, home_team, away_team, home_score, away_score from nfl_schedule "
            "where season=2026 and game_type='REG' and game_id like '2026_10_%'"):
        finals[gid] = {'home': norm(home), 'away': norm(away), 'home_points': hs, 'away_points': as_}
    players = collections.defaultdict(dict)
    for gid, key, team, stats in cur.execute(
            "select game_id, source_player_key, team, stats from player_game_logs "
            "where season=2026 and league='nfl' and game_id like '2026_10_%' and game_type='REG'"):
        s = json.loads(stats) if stats else {}
        players[gid][key] = {
            'team': norm(team), 'carries': s.get('carries', 0) or 0, 'targets': s.get('targets', 0) or 0,
            'rec': s.get('rec', 0) or 0, 'rush_yds': s.get('rush_yds', 0) or 0, 'rec_yds': s.get('rec_yds', 0) or 0,
            'pass_att': s.get('att', 0) or 0, 'off_pct': s.get('off_pct') or 0.0}
    con.close()
    return finals, players


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def main():
    os.makedirs(OUT, exist_ok=True)
    games = sorted(os.path.basename(d) for d in glob.glob(os.path.join(DATA, '2026_10_*')))
    if len(games) != 14:
        print("games found", len(games))
    finals, actual_players = actual_games()
    result = {'games': games, 'arms': ARMS, 'seeds_per_game': 20, 'per_game': {}, 'coverage': {}}
    recs = {(g, a): load_games(g, a) for g in games for a in ARMS}
    for g in games:
        for a in ARMS:
            n = len(recs[(g, a)])
            result['coverage'][f'{g}|{a}'] = n
    result['coverage_total'] = {a: sum(result['coverage'][f'{g}|{a}'] for g in games) for a in ARMS}
    # Team-game actuals from the logs: passing attempts (QB att), carries and targets.
    tot = {a: collections.Counter() for a in ARMS}
    for g in games:
        act = finals[g]
        ap = actual_players[g]
        per = {}
        for team in (act['home'], act['away']):
            rows = [p for p in ap.values() if p['team'] == team]
            per[team] = {'pass_att': sum(p['pass_att'] for p in rows), 'rush_att': sum(p['carries'] for p in rows),
                         'targets': sum(p['targets'] for p in rows)}
        result['per_game'].setdefault(g, {})['actual'] = {
            'home': act['home'], 'away': act['away'], 'home_points': act['home_points'],
            'away_points': act['away_points'], 'team_totals': per}
        for a in ARMS:
            rs = recs[(g, a)]
            if not rs:
                continue
            home_pts, away_pts, wins, margins, totals = [], [], 0, [], []
            team_att = collections.defaultdict(lambda: collections.Counter())
            for r in rs:
                pts = final_points(r)
                home = norm(r['home_team'])
                away = norm(r['away_team'])
                hp, ap_ = pts[home], pts[away]
                home_pts.append(hp)
                away_pts.append(ap_)
                wins += hp > ap_
                margins.append(hp - ap_)
                totals.append(hp + ap_)
                for t in r['teams']:
                    team = norm(t['team']) if 'team' in t else (home if t['home_away'] == 'home' else away)
                    st = t['stats']
                    team_att[team]['pass_att'] += st.get('pass_attempts', 0) or 0
                    team_att[team]['rush_att'] += st.get('rush_attempts', 0) or 0
                    team_att[team]['targets'] += st.get('targets', 0) or 0
            n = len(rs)
            p_home = wins / n
            outcome = 1.0 if act['home_points'] > act['away_points'] else 0.0
            pc = min(max(p_home, 1e-6), 1 - 1e-6)
            result['per_game'][g][a] = {
                'seeds': n, 'p_home_win': round(p_home, 4), 'actual_home_win': int(outcome),
                'brier': round((p_home - outcome) ** 2, 4),
                'log_loss': round(-(outcome * math.log(pc) + (1 - outcome) * math.log(1 - pc)), 4),
                'mean_home_points': round(mean(home_pts), 2), 'mean_away_points': round(mean(away_pts), 2),
                'mean_margin': round(mean(margins), 2),
                'actual_margin': act['home_points'] - act['away_points'],
                'margin_error': round(abs(mean(margins) - (act['home_points'] - act['away_points'])), 2),
                'total_error': round(abs(mean(totals) - (act['home_points'] + act['away_points'])), 2),
                'team_attempts_per_game': {t: {k: round(v / n, 2) for k, v in c.items()} for t, c in team_att.items()},
            }
    result['per_game_actual_team'] = {g: result['per_game'][g]['actual']['team_totals'] for g in games}
    json.dump(result, open(os.path.join(OUT, 'games.json'), 'w'), indent=1, sort_keys=True)
    result_alloc = allocation(games, recs, actual_players)
    json.dump(result_alloc, open(os.path.join(OUT, 'allocation.json'), 'w'), indent=1, sort_keys=True)
    json.dump(paired(games, recs), open(os.path.join(OUT, 'paired.json'), 'w'), indent=1, sort_keys=True)
    json.dump(lineup_checks(games, recs), open(os.path.join(OUT, 'lineup_checks.json'), 'w'), indent=1, sort_keys=True)
    json.dump(traces(games, recs), open(os.path.join(OUT, 'first_divergence.json'), 'w'), indent=1, sort_keys=True, default=str)
    print('written', OUT)


def allocation(games, recs, actual_players):
    """Carries and targets per player-game: simulated means against the actual week 10 lines. Starters are the players
    whose actual offensive snap share was at least half. Players missing from either side count as zero on that side."""
    out = {}
    for a in ARMS:
        rows = []
        for g in games:
            ap = actual_players[g]
            sims = collections.defaultdict(lambda: collections.Counter())
            seeds = recs[(g, a)]
            for r in seeds:
                for gsis, p in players_of(r).items():
                    for k in ('carries', 'targets', 'rec', 'rush_yds', 'rec_yds'):
                        sims[gsis][k] += p[k]
            n = max(len(seeds), 1)
            for gsis in set(sims) | set(ap):
                s = {k: sims[gsis][k] / n for k in ('carries', 'targets', 'rec', 'rush_yds', 'rec_yds')} if gsis in sims \
                    else {k: 0.0 for k in ('carries', 'targets', 'rec', 'rush_yds', 'rec_yds')}
                actual = ap.get(gsis)
                act = {k: actual[k] for k in ('carries', 'targets', 'rec', 'rush_yds', 'rec_yds')} if actual else \
                    {k: 0 for k in ('carries', 'targets', 'rec', 'rush_yds', 'rec_yds')}
                starter = bool(actual and actual['off_pct'] >= 0.5)
                rows.append({'game': g, 'gsis': gsis, 'starter': starter, 'in_sim': gsis in sims, 'in_actual': actual is not None,
                             'sim': s, 'act': act})
        def summarize(sel):
            if not sel:
                return None
            ce = [abs(r['sim']['carries'] - r['act']['carries']) for r in sel]
            te = [abs(r['sim']['targets'] - r['act']['targets']) for r in sel]
            tot_c = sum(r['act']['carries'] for r in sel)
            tot_t = sum(r['act']['targets'] for r in sel)
            return {'player_games': len(sel),
                    'carry_mae': round(mean(ce), 3), 'target_mae': round(mean(te), 3),
                    'carry_error_share': round(sum(ce) / tot_c, 3) if tot_c else None,
                    'target_error_share': round(sum(te) / tot_t, 3) if tot_t else None,
                    'sim_carries': round(sum(r['sim']['carries'] for r in sel), 2), 'act_carries': tot_c,
                    'sim_targets': round(sum(r['sim']['targets'] for r in sel), 2), 'act_targets': tot_t}
        out[a] = {'all': summarize(rows), 'starters': summarize([r for r in rows if r['starter']]),
                  'backups': summarize([r for r in rows if not r['starter'] and r['in_actual'] and (r['act']['carries'] or r['act']['targets'] or r['sim']['carries'] or r['sim']['targets'])]),
                  'sim_players_missing_from_actual': sum(1 for r in rows if r['in_sim'] and not r['in_actual']),
                  'actual_players_missing_from_sim': sum(1 for r in rows if r['in_actual'] and not r['in_sim'])}
    return out


def paired(games, recs):
    """Per arm pair and game: seeds where the final score, the player lines or the play sequence differ."""
    pairs = [('A-control', 'B-field'), ('B-field', 'C-field-pbv1'), ('A-control', 'C-field-pbv1')]
    out = {}
    for x, y in pairs:
        score = players = plays = seeds_n = 0
        per = {}
        for g in games:
            rx, ry = recs[(g, x)], recs[(g, y)]
            byseed_x = {r['seed']: r for r in rx}
            byseed_y = {r['seed']: r for r in ry}
            shared = sorted(set(byseed_x) & set(byseed_y))
            ds = dp = dpl = 0
            for s in shared:
                a_, b_ = byseed_x[s], byseed_y[s]
                if final_points(a_) != final_points(b_):
                    ds += 1
                if players_of(a_) != players_of(b_):
                    dp += 1
                pa = [json.dumps(p, sort_keys=True) for p in a_['realism']['plays']]
                pb = [json.dumps(p, sort_keys=True) for p in b_['realism']['plays']]
                if pa != pb:
                    dpl += 1
            per[g] = {'seeds': len(shared), 'score_differs': ds, 'players_differ': dp, 'plays_differ': dpl}
            score += ds; players += dp; plays += dpl; seeds_n += len(shared)
        out[f'{x} vs {y}'] = {'paired_seeds': seeds_n, 'score_differs': score, 'players_differ': players,
                              'plays_differ': plays, 'per_game': per}
    return out


def lineup_checks(games, recs):
    """Lineup validity for the two arms that run a lineup: short snaps, cell fallbacks, package counts and any player who
    carried or was targeted without an on-field snap in that game."""
    out = {}
    for a in ARMS[1:]:
        groups = collections.Counter()
        status = collections.Counter()
        violations = 0
        checked = 0
        short = 0
        qb_carries = 0
        for g in games:
            for r in recs[(g, a)]:
                lineup = (r.get('realism') or {}).get('lineup') or {}
                for team, info in lineup.items():
                    team = norm(team)
                    groups.update(info.get('groups', {}))
                    status.update(info.get('field_status', {}))
                    short += info.get('short_snaps', 0) or 0
                    snaps = info.get('player_snaps', {})
                    for gsis, p in players_of(r).items():
                        if p['team'] != team:
                            continue
                        if p['pos'] == 'QB':  # the passer is never in the skill lineup; his carries are counted apart
                            qb_carries += p['carries']
                            continue
                        if p['carries'] or p['targets'] or p['rec']:
                            checked += 1
                            if not snaps.get(gsis):
                                violations += 1
        out[a] = {'package_groups_total': dict(sorted(groups.items())), 'field_status_total': dict(status),
                  'short_snaps': short, 'player_games_with_touch': checked,
                  'touches_without_on_field_snap': violations, 'qb_carries_outside_lineup': qb_carries}
    return out


def traces(games, recs):
    """Full play traces for the shared diagnostic seeds, and the first play where two arms diverge."""
    os.makedirs(os.path.join(OUT, 'traces'), exist_ok=True)
    first = {}
    pairs = [('A-control', 'B-field'), ('B-field', 'C-field-pbv1')]
    for a in ARMS:
        with gzip.open(os.path.join(OUT, 'traces', f'{a}.jsonl.gz'), 'wt') as f:
            for g in games:
                for r in recs[(g, a)]:
                    if r['seed'] in TRACE_SEEDS:
                        f.write(json.dumps({'game': g, 'arm': a, 'seed': r['seed'], 'plays': r['realism']['plays']}) + '\n')
    for x, y in pairs:
        rows = []
        for g in games:
            bx = {r['seed']: r for r in recs[(g, x)]}
            by = {r['seed']: r for r in recs[(g, y)]}
            for s in TRACE_SEEDS:
                if s not in bx or s not in by:
                    continue
                pa, pb = bx[s]['realism']['plays'], by[s]['realism']['plays']
                idx = next((i for i, (u, v) in enumerate(zip(pa, pb)) if json.dumps(u, sort_keys=True) != json.dumps(v, sort_keys=True)), None)
                if idx is None and len(pa) != len(pb):
                    idx = min(len(pa), len(pb))
                rows.append({'game': g, 'seed': s, 'first_divergent_play': idx,
                             'x_play': pa[idx] if idx is not None and idx < len(pa) else None,
                             'y_play': pb[idx] if idx is not None and idx < len(pb) else None})
        first[f'{x} vs {y}'] = rows
    return first


if __name__ == '__main__':
    main()
