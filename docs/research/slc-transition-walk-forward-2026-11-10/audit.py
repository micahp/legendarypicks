"""Week-frozen transition scoring; no simulated games or same-week training."""
import collections
import hashlib
import importlib.util
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('previous_audit', HERE.parent / 'slc-transition-strength-diagnostic-2026-11-10' / 'audit.py')
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)
ts = old.ts


def read_rows(year):
    table = old.pq.read_table(old.ROOT / f'play_by_play_{year}.parquet', columns=list(old.e1.COLUMNS))
    rows = [{k: old.pyval(v) for k, v in row.items()} for row in table.to_pylist()]
    rows.sort(key=lambda row: (row['game_id'] or '', row['play_id'] or -1))
    return rows


def run():
    train = collections.defaultdict(list)
    hashes = {}
    for year in range(2022, 2027):
        path = old.ROOT / f'play_by_play_{year}.parquet'
        h = hashlib.sha256()
        with path.open('rb') as f:
            for block in iter(lambda: f.read(1024 * 1024), b''): h.update(block)
        hashes[str(year)] = h.hexdigest()
    for year in range(2022, 2025):
        pool, _ = old.season_pool(year)
        old.merge(train, pool)
        print('loaded', year, flush=True)
    results = {'source_sha256': hashes, 'evaluations': {}, 'method': 'Prior-season league cells and team profiles; update from strictly earlier weeks only. Current-only uses n0=1e-9 as an approximation and falls back to league ratios when current evidence is absent; all arms retain league smoothing of 50 plays. Week 1 uses the historical prior for all team-strength arms. Historical parquet acquisition time and historical revisions are not verified.'}
    for year in (2025, 2026):
        hist = ts.build_from_pool(train, year, cutoff=(year, 1))
        neutral = ts.TransitionStrength({'offense': {}, 'defense': {}}, hist.league_shares, hist.manifest)
        base = collections.defaultdict(collections.Counter)
        for cell, samples in train.items():
            for ev, row, _, _ in samples:
                it = old.intent(ev)
                if it: base[(cell, it)][ts.transition_key(ev, row)] += 1
        rows = read_rows(year)
        weeks = sorted({int(r['week']) for r in rows if r['week'] is not None})
        earlier = []
        game_teams = {}
        year_out = {}
        for week in weeks:
            current = [r for r in rows if r['week'] == week]
            game_counts = collections.Counter(team for teams in game_teams.values() for team in teams)
            models = {'historical': hist}
            if earlier:
                for label, n0 in [('current_only_approx', 1e-9), ('blend_n0_2', 2), ('blend_n0_4', 4), ('blend_n0_8', 8)]:
                    models[label] = ts.adapt(neutral if label == 'current_only_approx' else hist, earlier, n0=n0, team_games=game_counts)
            else:
                models.update({label: hist for label in ('current_only_approx','blend_n0_2','blend_n0_4','blend_n0_8')})
            pool, _, unknown, _ = ts._clean_pool_from_rows(current)
            totals = {name: [0, 0., 0.] for name in ('league', *models)}
            contexts = {}
            for cell, samples in pool.items():
                for event, row, _, _ in samples:
                    it = old.intent(event)
                    if not it: continue
                    ctx = (cell, it, row['posteam'], row['defteam'])
                    if ctx not in contexts:
                        counts = base.get((cell, it), {})
                        if not counts:
                            contexts[ctx] = None
                            continue
                        weights = {'league': dict(counts)}
                        for name, model in models.items():
                            weights[name] = {}
                            for key, count in counts.items():
                                w = float(count)
                                for side, team in (('offense', ctx[2]), ('defense', ctx[3])):
                                    try: w *= model.ratio_key(side, team, cell, key)
                                    except ValueError: pass
                                weights[name][key] = w
                        contexts[ctx] = {name: {k: v / sum(ws.values()) for k, v in ws.items()} for name, ws in weights.items()}
                    distributions = contexts[ctx]
                    if distributions is None: continue
                    actual = ts.transition_key(event, row)
                    for name, dist in distributions.items():
                        p = dist.get(actual, 0.)
                        t = totals[name]
                        t[0] += 1
                        t[1] -= math.log(max(p, 1e-15))
                        t[2] += sum((v - (k == actual)) ** 2 for k, v in dist.items()) + (actual not in dist)
            year_out[str(week)] = {'scores': {name: {'n': n, 'log_loss': loss/n if n else None, 'brier': brier/n if n else None} for name, (n, loss, brier) in totals.items()}, 'prior_games': len(game_teams), 'unknown_penalty_rows': unknown}
            print(json.dumps({'year': year, 'week': week, 'scores': year_out[str(week)]['scores']}), flush=True)
            earlier.extend(current)
            for row in current:
                if row['posteam'] and row['defteam']:
                    game_teams[row['game_id']] = (row['posteam'], row['defteam'])
        results['evaluations'][str(year)] = year_out
        if year == 2025:
            pool, _, _, _ = ts._clean_pool_from_rows(rows)
            old.merge(train, pool)
        del rows, earlier, pool
        (HERE / 'results.json').write_text(json.dumps(results, indent=2, sort_keys=True) + '\n')

if __name__ == '__main__': run()
