"""Compare draw keys across arms for the three diagnostic seeds (BUF at NYJ).

Input: LOGDIR/<arm>.draws.json (from harness.py) and LOGDIR/<arm>.boxscores.jsonl. A draw key is the text the generator is
seeded from. Keys are compared as sets, not by position, because the arms request draws in different orders.
"""
import collections, json, os, sys

LOGDIR = sys.argv[1]
ARMS = ['A-control', 'B-field', 'C-field-pbv1']
PAIRS = [('A-control', 'B-field'), ('B-field', 'C-field-pbv1'), ('A-control', 'C-field-pbv1')]


def draws(arm):
    rows = json.load(open(os.path.join(LOGDIR, f'{arm}.draws.json')))
    return {key: value for key, value in rows}, len(rows)


def plays(arm):
    out = {}
    for line in open(os.path.join(LOGDIR, f'{arm}.boxscores.jsonl')):
        rec = json.loads(line)
        if rec.get('type') == 'game':
            out[rec['seed']] = rec['realism']['plays']
    return out


def name(key):
    if key.startswith('stream|'):
        return 'stream:' + key.split('|')[3]
    return key.split(':', 3)[3]


def main():
    data = {a: draws(a) for a in ARMS}
    play = {a: plays(a) for a in ARMS}
    for x, y in PAIRS:
        dx, nx = data[x]
        dy, ny = data[y]
        shared = set(dx) & set(dy)
        equal = sum(dx[k] == dy[k] for k in shared)
        only_x, only_y = set(dx) - set(dy), set(dy) - set(dx)
        print(f'{x} vs {y}')
        print(f'  draws {nx} vs {ny}; shared keys {len(shared)}; shared keys with equal value {equal}')
        print(f'  keys only in {x}: {len(only_x)}; top names {collections.Counter(name(k) for k in only_x).most_common(4)}')
        print(f'  keys only in {y}: {len(only_y)}; top names {collections.Counter(name(k) for k in only_y).most_common(4)}')
        for seed in sorted(set(play[x]) & set(play[y])):
            a, b = play[x][seed], play[y][seed]
            idx = next((i for i, (u, v) in enumerate(zip(a, b))
                        if json.dumps(u, sort_keys=True) != json.dumps(v, sort_keys=True)), None)
            print(f'  seed {seed}: plays {len(a)} vs {len(b)}; first divergent play {idx}')
        print()


if __name__ == '__main__':
    main()
