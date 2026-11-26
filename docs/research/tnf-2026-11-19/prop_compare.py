"""Player prop comparison for one game: simulated over probability vs the posted market, per prop line.

Reads a batch's boxscore JSONL (one game record per seed) and the props table of a frozen database. For each
(player, market, line, source) with both sides priced, the market's over probability is the implied probability of
the over with the vig removed (normalised against the under). The model's is the share of seeds with a stat above the
line. Edge = model minus market. Stats are summed from the players' passing, rushing and receiving lines.

Usage: prop_compare.py BOXSCORES.jsonl FROZEN.db GAME_ID OUT.json
"""
import json
import sqlite3
import sys
from collections import defaultdict

# market -> function of one player's per-seed stat dict
STAT = {
    'receiving_yards': lambda p: p['receiving']['yds'],
    'receptions': lambda p: p['receiving']['rec'],
    'targets': lambda p: p['receiving']['tgt'],
    'passing_yards': lambda p: p['passing']['yds'],
    'passing_touchdowns': lambda p: p['passing']['td'],
    'pass_attempts': lambda p: p['passing']['att'],
    'pass_completions': lambda p: p['passing']['comp'],
    'interceptions_thrown': lambda p: p['passing']['int'],
    'rushing_yards': lambda p: p['rushing']['yds'],
    'rush_attempts': lambda p: p['rushing']['att'],
    'rushing_receiving_yards': lambda p: p['rushing']['yds'] + p['receiving']['yds'],
    'passing_rushing_yards': lambda p: p['passing']['yds'] + p['rushing']['yds'],
    'rushing_receiving_touchdowns': lambda p: p['rushing']['td'] + p['receiving']['td'],
}


def implied(american):
    return 100.0 / (american + 100.0) if american > 0 else -american / (-american + 100.0)


def fair_over(over, under):
    if over is None or under is None or (over == -137 and under == -137):  # pick'em placeholder: no price
        return None
    po, pu = implied(over), implied(under)
    return po / (po + pu)


def main():
    box_path, db_path, game_id, out_path = sys.argv[1:5]
    samples = defaultdict(lambda: defaultdict(list))   # lp_player_id -> market -> [value per seed]
    appear = defaultdict(int)                           # seeds in which the player was in the simulated game
    names = {}
    seeds = 0
    for line in open(box_path):
        rec = json.loads(line)
        if rec.get('type') != 'game':
            continue
        seeds += 1
        seen = set()
        for p in rec['players']:
            pid = p.get('lp_player_id')
            if pid is None:
                continue
            names[pid] = p['name']
            seen.add(pid)
            appear[pid] += 1
            for market, fn in STAT.items():
                samples[pid][market].append(fn(p))
        for pid in list(samples):
            if pid not in seen:          # did not play this seed: zero for every stat
                for market in STAT:
                    samples[pid][market].append(0)
    con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    gid = con.execute("select id from prop_games where league='nfl' and date=? and home=? and away=?",
                      ('2026-11-19', 'HOU', 'IND')).fetchone()
    if gid is None:
        raise SystemExit('no TNF prop game row in the database')
    gid = gid[0]
    rows = con.execute("""select player_id, market, line, side, source, odds, odds_captured_at from props
                          where game_id=? and market in ({})""".format(','.join('?' * len(STAT))),
                       (gid, *STAT)).fetchall()
    best = {}
    for pid, market, line, side, source, odds, at in rows:
        key = (pid, market, line, source)
        cur = best.setdefault(key, {})
        if side not in cur or (at or '') > (cur[side][1] or ''):
            cur[side] = (odds, at)
    results = []
    not_in_sim = set()
    for (pid, market, line, source), sides in sorted(best.items()):
        if 'over' not in sides or 'under' not in sides or pid not in samples:
            continue
        if appear[pid] == 0:  # never in a simulated game: the model has no view of this player
            not_in_sim.add(pid)
            continue
        market_p = fair_over(sides['over'][0], sides['under'][0])
        if market_p is None:
            continue
        vals = samples[pid][market]
        model_p = sum(1 for v in vals if v > line) / len(vals)
        results.append({'player': names.get(pid, str(pid)), 'lp_player_id': pid, 'market': market, 'line': line,
                        'source': source, 'over_odds': sides['over'][0], 'under_odds': sides['under'][0],
                        'market_p_over': round(market_p, 4), 'model_p_over': round(model_p, 4),
                        'edge': round(model_p - market_p, 4), 'seeds': len(vals), 'seeds_in_game': appear[pid]})
    results.sort(key=lambda r: -abs(r['edge']))
    out = {'game_id': 'TNF 2026-11-19 HOU vs IND', 'seeds': seeds, 'lines_compared': len(results),
           'method': 'model_p_over = share of seeds with stat > line; market_p_over = vig-free implied over',
           'skipped_markets': sorted({m for (_, m, _, _) in best} - set(STAT)),
           'players_priced_but_never_simulated': sorted(names.get(p, str(p)) for p in not_in_sim) if False else len(not_in_sim),
           'rows': results}
    json.dump(out, open(out_path, 'w'), indent=1)
    print('seeds', seeds, 'lines compared', len(results))


if __name__ == '__main__':
    main()
