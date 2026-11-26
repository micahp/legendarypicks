"""Summarise one batch's game outputs per model: games, valid full games, mean score, home win rate."""
import glob, json, os, statistics, sys

out_root = sys.argv[1]
summary = {}
for box in sorted(glob.glob(os.path.join(out_root, 'runs', '*', '*.boxscores.jsonl'))):
    model = box.split(os.sep)[-2]
    home, away, margins = [], [], []
    for line in open(box):
        r = json.loads(line)
        if r.get('type') != 'game':
            continue
        pts = {t['home_away']: t['stats']['points'] for t in r['teams']}
        home.append(pts.get('home')); away.append(pts.get('away'))
        margins.append(pts.get('home') - pts.get('away'))
    seed_json = glob.glob(os.path.join(out_root, 'runs', model, '*.json'))
    valid = None
    for f in seed_json:
        if '.inputs.' in f or f.endswith('.boxscores.json'):
            continue
        try:
            d = json.load(open(f))
            s = d.get('summary') or d['output']['summary']
            valid = s.get('valid_full_games'), s.get('requested_games')
        except Exception:
            pass
    n = len(home)
    summary[model] = {
        'games_done': n,
        'valid_full_games': valid[0] if valid else None,
        'requested': valid[1] if valid else None,
        'home_mean': round(statistics.mean(home), 2) if n else None,
        'away_mean': round(statistics.mean(away), 2) if n else None,
        'home_win_rate': round(sum(1 for m in margins if m > 0) / n, 3) if n else None,
        'mean_margin_home': round(statistics.mean(margins), 2) if n else None,
    }
print(json.dumps(summary, indent=1))
