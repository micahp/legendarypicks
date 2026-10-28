"""Decision model v1 (NFL-DECISION-MODEL-SPEC-2026-10-27, sections 1 to 10).

A team prior trained on 2025, shrunk toward a league prior, scored on decisions (not outcomes) by role, situation and
alignment. The 2026 season is the sealed holdout. This file has two stages, run in order:

  validate2025  Loads 2025 only. Trains on Weeks 1 to 9 and validates on Weeks 10 to 18 to choose k from {5, 20, 80}.
                Refits on all of 2025 (Weeks 1 to 18), freezes the prior, and writes its hash to validate2025.json.
  test2026      Loads 2026 Weeks 1 to 7 once. Rebuilds the 2025 prior, checks its hash against the frozen one, scores the
                team prior and the league prior, and writes test2026.json. It refuses to run if test2026.json exists.

Operational definitions (fixed by this code before the 2026 run):
  - Universe: regular-season plays with play_type pass or run, not play_deleted, with a possession team, down, distance
    and yard line.
  - Pass: pass_attempt == 1. Run: rush_attempt == 1 and not a pass.
  - Team: posteam, as coded in play-by-play (LA stays LA; no NGS join is used).
  - Roles come from players.parquet position by gsis_id. FB is RB. WR, TE, RB, QB as named. Every other position is Other.
  - Charting joins to play-by-play on game_id and play_id. Charting codes '0' are uncharted (see the spec).
"""
import hashlib
import json
import os
import random
import sys
from collections import defaultdict

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

RAW = '/root/lp-snapshots/nfl-backfill-2026-10-27/raw'
RESULTS = '/tmp/claude-0/-root/4a715766-ff4b-4980-99e5-dc209eaac7d4/scratchpad/nfl-splits/results'
K_GRID = (5, 20, 80)
SEED = 20261027
REPS = 2000
CAT_ROLES = {
    'A': ['RB', 'WR', 'TE', 'Other'],
    'B': ['RB', 'QB', 'WR_TE', 'Other'],
    'C': ['guard', 'tackle', 'end'],
    'D': ['short', 'deep'],
    'E': ['left', 'middle', 'right'],
    'F': ['yes', 'no'],
    'G': ['yes', 'no'],
    'H': ['yes', 'no'],
    'I': ['yes', 'no'],
    'J': ['S', 'U', 'P'],
    'K': ['L', 'M', 'R'],
    'L': ['0', '1', '2', '3+'],
    'M': ['<=5', '6', '7', '8+'],
    'N': ['3-4', '5+'],
}
CATS = list(CAT_ROLES)
AI = list('ABCDEFGHI')
MAXR = max(len(v) for v in CAT_ROLES.values())
CHARTING = ['qb_location', 'starting_hash', 'n_offense_backfield', 'n_defense_box', 'is_play_action', 'is_motion',
            'n_blitzers', 'n_pass_rushers']


def positions():
    p = pq.read_table(f'{RAW}/players/players.parquet', columns=['gsis_id', 'position']).to_pandas()
    return dict(zip(p.gsis_id, p.position))


def role_of_receiver(pos):
    if pos in ('RB', 'FB'):
        return 'RB'
    if pos in ('WR', 'TE'):
        return pos
    return 'Other'


def role_of_rusher(pos):
    if pos == 'QB':
        return 'QB'
    if pos in ('RB', 'FB'):
        return 'RB'
    if pos in ('WR', 'TE'):
        return 'WR_TE'
    return 'Other'


def cell_of(down, ydstogo, yardline_100):
    dist = 'short' if ydstogo <= 3 else ('medium' if ydstogo <= 7 else 'long')
    zone = 'red' if yardline_100 <= 20 else 'other'
    return f'{int(down)}|{dist}|{zone}'


def load_season(season, pos):
    base = f'{RAW}/pbp/play_by_play_{season}.parquet'
    names = pq.read_schema(base).names
    want = ['game_id', 'play_id', 'season_type', 'week', 'posteam', 'play_type', 'pass_attempt', 'rush_attempt',
            'shotgun', 'run_gap', 'pass_length', 'pass_location', 'down', 'ydstogo', 'yardline_100',
            'receiver_player_id', 'rusher_player_id', 'play_deleted']
    pbp = pq.read_table(base, columns=[c for c in want if c in names]).to_pandas()
    pbp = pbp[(pbp.season_type == 'REG') & pbp.play_type.isin(['pass', 'run']) & (pbp.play_deleted.fillna(0) != 1)
              & pbp.posteam.notna() & pbp.down.notna() & pbp.ydstogo.notna() & pbp.yardline_100.notna()].copy()
    ch = pq.read_table(f'{RAW}/ftn_charting/ftn_charting_{season}.parquet',
                       columns=['nflverse_game_id', 'nflverse_play_id'] + CHARTING).to_pandas()
    ch = ch.rename(columns={'nflverse_game_id': 'game_id', 'nflverse_play_id': 'play_id'})
    pbp['play_id'] = pbp.play_id.astype('int64')
    ch['play_id'] = ch.play_id.astype('int64')
    df = pbp.merge(ch, on=['game_id', 'play_id'], how='left')
    df['season'] = season
    df['is_pass'] = df.pass_attempt.fillna(0).eq(1)
    df['is_run'] = df.rush_attempt.fillna(0).eq(1) & ~df['is_pass']
    df['rec_pos'] = df.receiver_player_id.map(pos)
    df['rush_pos'] = df.rusher_player_id.map(pos)
    df['cell'] = [cell_of(d, y, z) for d, y, z in zip(df.down, df.ydstogo, df.yardline_100)]
    df['team'] = df.posteam
    labels = [label_row(r) for r in df.itertuples(index=False)]
    lab = pd.DataFrame(labels, columns=CATS, index=df.index)
    return pd.concat([df, lab], axis=1)


def label_row(r):
    out = {c: None for c in CATS}
    is_pass, is_run = bool(r.is_pass), bool(r.is_run)
    if is_pass and isinstance(r.receiver_player_id, str) and isinstance(r.rec_pos, str):
        out['A'] = role_of_receiver(r.rec_pos)
    if is_run and isinstance(r.rush_pos, str):
        out['B'] = role_of_rusher(r.rush_pos)
        if r.rush_pos in ('RB', 'FB') and r.run_gap in ('guard', 'tackle', 'end'):
            out['C'] = r.run_gap
    if is_pass and r.pass_length in ('short', 'deep'):
        out['D'] = r.pass_length
    if is_pass and r.pass_location in ('left', 'middle', 'right'):
        out['E'] = r.pass_location
    if r.shotgun is not None and not pd.isna(r.shotgun):
        out['F'] = 'yes' if r.shotgun == 1 else 'no'
    if is_pass and not pd.isna(r.is_play_action):
        out['G'] = 'yes' if r.is_play_action == 1 else 'no'
    if not pd.isna(r.is_motion):
        out['H'] = 'yes' if r.is_motion == 1 else 'no'
    if is_pass and not pd.isna(r.n_blitzers):
        out['I'] = 'yes' if r.n_blitzers >= 1 else 'no'
    if isinstance(r.qb_location, str) and r.qb_location != '0':
        out['J'] = r.qb_location
    if isinstance(r.starting_hash, str) and r.starting_hash != '0':
        out['K'] = r.starting_hash
    if not pd.isna(r.n_offense_backfield):
        n = int(r.n_offense_backfield)
        out['L'] = '3+' if n >= 3 else str(n)
    if not pd.isna(r.n_defense_box) and int(r.n_defense_box) != 0:
        n = int(r.n_defense_box)
        out['M'] = '<=5' if n <= 5 else ('8+' if n >= 8 else str(n))
    if is_pass and not pd.isna(r.n_pass_rushers) and r.n_pass_rushers >= 3:
        out['N'] = '3-4' if r.n_pass_rushers <= 4 else '5+'
    return out


def zero_counts(c):
    n = len(CAT_ROLES[c])
    return lambda: np.zeros(n)


def fit(df):
    """League and team counts per category, cell and role."""
    league = {c: defaultdict(zero_counts(c)) for c in CATS}
    team = {c: defaultdict(zero_counts(c)) for c in CATS}
    for c in CATS:
        roles = CAT_ROLES[c]
        sub = df[df[c].notna()]
        for cell, t, lab in zip(sub.cell, sub.team, sub[c]):
            i = roles.index(lab)
            league[c][cell][i] += 1
            team[c][(t, cell)][i] += 1
    return league, team


def league_vec(league, c, cell):
    n = len(CAT_ROLES[c])
    counts = league[c].get(cell)
    if counts is None or counts.sum() == 0:
        return np.full(n, 1.0 / n)
    return counts / counts.sum()


def prior_vec(league, team, c, t, cell, k):
    pl = league_vec(league, c, cell)
    if k is None:
        return pl
    counts = team[c].get((t, cell))
    nt = 0.0 if counts is None else counts.sum()
    if nt == 0:
        return pl
    return (counts + k * pl) / (nt + k)


def accumulate(df, league, team, k):
    """Per game and per (team, category): n plays, summed predicted role probabilities, observed role counts."""
    out = defaultdict(dict)
    for g, t, cell, *labs in zip(df.game_id, df.team, df.cell, *[df[c] for c in CATS]):
        for c, lab in zip(CATS, labs):
            if lab is None or (isinstance(lab, float) and np.isnan(lab)):
                continue
            roles = CAT_ROLES[c]
            p = prior_vec(league, team, c, t, cell, k)
            slot = out[g].setdefault((t, c), [0, np.zeros(MAXR), np.zeros(MAXR)])
            slot[0] += 1
            slot[1][:len(roles)] += p
            slot[2][roles.index(lab)] += 1
    return out


def dense(acc, games, keys):
    """Matrices with one row per game: n per key, predicted sums and observed counts per key and role."""
    idx = {k: i for i, k in enumerate(keys)}
    N = np.zeros((len(games), len(keys)))
    P = np.zeros((len(games), len(keys), MAXR))
    O = np.zeros((len(games), len(keys), MAXR))
    for gi, g in enumerate(games):
        for key, (n, p, o) in acc.get(g, {}).items():
            j = idx[key]
            N[gi, j] = n
            P[gi, j] = p
            O[gi, j] = o
    return N, P, O


def headline(n, p, o, cat_of_key):
    """n: (K,), p, o: (K, MAXR) totals. Returns (headline over A to N, headline over A to I, per-category scores)."""
    with np.errstate(divide='ignore', invalid='ignore'):
        share_p = p / n[:, None]
        share_o = o / n[:, None]
        tvd = 0.5 * np.abs(share_p - share_o).sum(axis=1)
    valid = n > 0
    num = np.bincount(cat_of_key[valid], weights=(n * tvd)[valid], minlength=len(CATS))
    den = np.bincount(cat_of_key[valid], weights=n[valid], minlength=len(CATS))
    scores = num / np.where(den > 0, den, np.nan)
    ai = [CATS.index(c) for c in AI]
    return float(np.nanmean(scores)), float(np.nanmean(scores[ai])), scores


def bootstrap_diff(Nt, Pt, Ot, Nl, Pl, Ol, cat_of_key, keys):
    rng = random.Random(SEED)
    G = Nt.shape[0]
    diffs_all, diffs_ai, team_all, league_all = [], [], [], []
    K = len(keys)
    for _ in range(REPS):
        sample = [rng.randrange(G) for _ in range(G)]
        cnt = np.bincount(sample, minlength=G).astype(float)
        nt = cnt @ Nt
        pt = (cnt @ Pt.reshape(G, -1)).reshape(K, MAXR)
        ot = (cnt @ Ot.reshape(G, -1)).reshape(K, MAXR)
        nl = cnt @ Nl
        pl = (cnt @ Pl.reshape(G, -1)).reshape(K, MAXR)
        ol = (cnt @ Ol.reshape(G, -1)).reshape(K, MAXR)
        ht, hti, _ = headline(nt, pt, ot, cat_of_key)
        hl, hli, _ = headline(nl, pl, ol, cat_of_key)
        team_all.append(ht)
        league_all.append(hl)
        diffs_all.append(ht - hl)
        diffs_ai.append(hti - hli)
    def ci(v):
        v = sorted(v)
        return [v[int(0.025 * REPS)], v[int(0.975 * REPS)]]
    return {'team_minus_league_all': ci(diffs_all), 'team_minus_league_AI': ci(diffs_ai),
            'team_all': ci(team_all), 'league_all': ci(league_all)}


def key_index(acc_maps):
    keys = set()
    for acc in acc_maps:
        for g in acc:
            keys.update(acc[g].keys())
    keys = sorted(keys)
    cat_of_key = np.array([CATS.index(c) for _, c in keys])
    return keys, cat_of_key


def prior_hash(league, team):
    payload = {
        'league': {c: {cell: v.round(12).tolist() for cell, v in sorted(league[c].items())} for c in CATS},
        'team': {c: {f'{t}|{cell}': v.round(12).tolist() for (t, cell), v in sorted(team[c].items())} for c in CATS},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def validate2025():
    os.makedirs(RESULTS, exist_ok=True)
    pos = positions()
    df = load_season(2025, pos)
    train = df[df.week.between(1, 9)]
    val = df[df.week.between(10, 18)]
    print(f'2025 universe: {len(df)} plays; train weeks 1-9 {len(train)}; validation weeks 10-18 {len(val)}')
    rows = {}
    for k in list(K_GRID) + [None]:
        league, team = fit(train)
        acc = accumulate(val, league, team, k)
        games = sorted(acc)
        keys, cat_of_key = key_index([acc])
        N, P, O = dense(acc, games, keys)
        h_all, h_ai, scores = headline(N.sum(axis=0), P.sum(axis=0), O.sum(axis=0), cat_of_key)
        rows['league' if k is None else f'k={k}'] = {'headline_all': h_all, 'headline_AI': h_ai,
                                                      'category_scores': dict(zip(CATS, [float(s) for s in scores]))}
        print(f"  {'league' if k is None else 'k=' + str(k):8s} headline A-N {h_all:.4f}  A-I {h_ai:.4f}")
    team_keys = [k for k in rows if k != 'league']
    chosen = min(team_keys, key=lambda kk: (rows[kk]['headline_all'], int(kk.split('=')[1])))
    k_star = int(chosen.split('=')[1])
    print(f'chosen k = {k_star} (lowest validation headline A-N; ties to the smaller k)')
    league, team = fit(df)
    h = prior_hash(league, team)
    out = {'stage': 'validate2025', 'validation': rows, 'chosen_k': k_star, 'frozen_prior_sha256': h,
           'train_weeks': [1, 9], 'validation_weeks': [10, 18], 'fit_weeks': [1, 18],
           'universe_2025': int(len(df)), 'category_defined_2025': {c: int(df[c].notna().sum()) for c in CATS}}
    with open(os.path.join(RESULTS, 'validate2025.json'), 'w') as handle:
        json.dump(out, handle, indent=1)
    print(f'frozen prior sha256 {h[:16]}... written to validate2025.json')


def test2026():
    path = os.path.join(RESULTS, 'test2026.json')
    if os.path.exists(path):
        sys.exit('test2026.json exists: the 2026 test has already been run once. It is not rerun.')
    frozen = json.load(open(os.path.join(RESULTS, 'validate2025.json')))
    pos = positions()
    fit_df = load_season(2025, pos)
    league, team = fit(fit_df)
    if prior_hash(league, team) != frozen['frozen_prior_sha256']:
        sys.exit('the rebuilt 2025 prior does not match the frozen hash. Stopping.')
    k = frozen['chosen_k']
    test = load_season(2026, pos)
    test = test[test.week.between(1, 7)]
    acc_t = accumulate(test, league, team, k)
    acc_l = accumulate(test, league, team, None)
    games = sorted(set(acc_t) | set(acc_l))
    keys, cat_of_key = key_index([acc_t, acc_l])
    Nt, Pt, Ot = dense(acc_t, games, keys)
    Nl, Pl, Ol = dense(acc_l, games, keys)
    ht, hti, st = headline(Nt.sum(0), Pt.sum(0), Ot.sum(0), cat_of_key)
    hl, hli, sl = headline(Nl.sum(0), Pl.sum(0), Ol.sum(0), cat_of_key)
    boot = bootstrap_diff(Nt, Pt, Ot, Nl, Pl, Ol, cat_of_key, keys)
    defined = {c: int(test[c].notna().sum()) for c in CATS}
    out = {
        'stage': 'test2026', 'k': k, 'frozen_prior_sha256': frozen['frozen_prior_sha256'],
        'test_weeks': [1, 7], 'games': len(games), 'plays_universe': int(len(test)),
        'category_defined': defined,
        'team_prior': {'headline_all': ht, 'headline_AI': hti, 'category_scores': dict(zip(CATS, map(float, st)))},
        'league_prior': {'headline_all': hl, 'headline_AI': hli, 'category_scores': dict(zip(CATS, map(float, sl)))},
        'bootstrap_95': boot, 'bootstrap_reps': REPS, 'seed': SEED,
    }
    with open(path, 'w') as handle:
        json.dump(out, handle, indent=1)
    print(json.dumps({k2: out[k2] for k2 in ('k', 'games', 'plays_universe', 'team_prior', 'league_prior',
                                             'bootstrap_95')}, indent=1))


if __name__ == '__main__':
    stage = sys.argv[1] if len(sys.argv) > 1 else ''
    if stage == 'validate2025':
        validate2025()
    elif stage == 'test2026':
        test2026()
    else:
        sys.exit('usage: decision_model.py validate2025 | test2026')
