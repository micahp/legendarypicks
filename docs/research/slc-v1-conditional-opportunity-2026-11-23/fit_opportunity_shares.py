#!/usr/bin/env python3
"""Step 1 of the conditional player-opportunity experiment: who gets each target and each designed carry. Read-only.

The question: given that a team throws a targeted pass (or calls a designed run), what is the probability that player i
is the receiver (or rusher)? This is the quantity v1's share layer (share_distributions, dirichlet-multinomial v3) sets.

Opportunities: regular-season nflverse play-by-play. A target is a pass with a receiver_player_id; a designed carry is a
run with a rusher_player_id and qb_scramble != 1 (scrambles are a QB decision, not a carry allocation). Two-point tries
are left out.

Candidates: for each team, game and role, the players with at least one opportunity of that role in that game. This is the
availability proxy: the sim gets the same information from the frozen injury report. Every model is scored on the same
candidate set.

Models (each gives a weight per candidate, normalised over the candidates):
  M0  v1 baseline: max(prior-season share for this team and player, 0.01). The Dirichlet mean of v1's per-game draw.
  M1  in-season: this season's counts before the game week, plus k times the M0 weight. k is tuned on the tune season.
  M2  M1 with a cross-team prior: a player with no prior-season share on this team takes his prior-season share on the
      team he left, so a traded player does not start at the 0.01 floor.
  M3  M2 times a league-level situational factor for the player's position group: P(group | role, situation) over
      P(group | role), fitted on the seasons before the target season. Situation = field zone (1-5, 6-20, 21+) x
      down class (1-2, 3-4) x score state (trailing 9+, within 8, leading 9+).

Scores: mean log loss per opportunity, overall and within the realised receiver's position group (the latter is exactly
the quantity v1's share layer draws). 95% intervals for model differences come from a bootstrap over games, because plays
in one game are not independent. The MIN week 11 case reports each player's expected count (sum of his predicted share
over the game's opportunities) next to his actual count.

Chronology: k is chosen on the tune season (2025, priors from 2024). The test season (2026) uses priors from 2025 and only
weeks before each game's week. Nothing from the test season tunes anything.

Usage: python3 fit_opportunity_shares.py --pbp-dir DIR --db picks.dev.db --out-dir DIR
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import random
import sqlite3
import statistics
from pathlib import Path

import pandas as pd

FLOOR = 0.01  # player_shares.FLOOR at 58ef3861
K_GRID = (0, 5, 10, 20, 40, 60, 80, 120, 160, 240, 320, 480, 640, 1000, 2000)
GROUPS = {'receive': {'WR': 'WR', 'TE': 'TE', 'RB': 'RB', 'FB': 'RB'},
          'carry': {'RB': 'RB', 'FB': 'RB', 'QB': 'QB', 'WR': 'WR_TE', 'TE': 'WR_TE'}}
COLUMNS = ['season', 'week', 'season_type', 'game_id', 'play_id', 'posteam', 'play_type', 'qb_scramble',
           'receiver_player_id', 'rusher_player_id', 'two_point_attempt', 'down', 'yardline_100', 'score_differential']


def load(pbp_dir, seasons):
    frames = []
    for season in seasons:
        d = pd.read_parquet(Path(pbp_dir, f'play_by_play_{season}.parquet'), columns=COLUMNS)
        frames.append(d[(d.season_type == 'REG') & (d.two_point_attempt != 1)])
    d = pd.concat(frames)
    tgt = d[(d.play_type == 'pass') & d.receiver_player_id.notna()].assign(role='receive', player=lambda x: x.receiver_player_id)
    car = d[(d.play_type == 'run') & d.rusher_player_id.notna() & (d.qb_scramble != 1)].assign(
        role='carry', player=lambda x: x.rusher_player_id)
    o = pd.concat([tgt, car])[['season', 'week', 'game_id', 'posteam', 'role', 'player', 'down', 'yardline_100',
                               'score_differential']]
    return o.rename(columns={'posteam': 'team'}).reset_index(drop=True)


def situation(row):
    y = row.yardline_100
    zone = 'z1-5' if y <= 5 else 'z6-20' if y <= 20 else 'z21+'
    down = 'd1-2' if (row.down or 1) <= 2 else 'd3-4'
    s = row.score_differential if row.score_differential == row.score_differential else 0
    score = 'trail9+' if s <= -9 else 'lead9+' if s >= 9 else 'close'
    return f'{zone}|{down}|{score}'


def positions(db):
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    try:
        rows = con.execute("SELECT nfl_gsis_id, MIN(position) FROM players WHERE lower(league)='nfl' AND nfl_gsis_id IS NOT NULL "
                           "AND position IS NOT NULL GROUP BY nfl_gsis_id").fetchall()
    finally:
        con.close()
    return dict(rows)


def season_shares(opps, season):
    """{(role, team, player): share of the team's season opportunities} and {(role, player): (team, share)} for one season."""
    s = opps[opps.season == season]
    counts = s.groupby(['role', 'team', 'player']).size()
    totals = s.groupby(['role', 'team']).size()
    team_share = {(r, t, p): n / totals[(r, t)] for (r, t, p), n in counts.items()}
    by_player = {}
    for (r, t, p), share in team_share.items():  # a player on two teams keeps his larger share
        if share > by_player.get((r, p), (None, 0))[1]:
            by_player[(r, p)] = (t, share)
    return team_share, by_player


def situational_factors(opps, seasons, pos):
    """{(role, situation, group): P(group | role, situation) / P(group | role)} on the given seasons, with n."""
    s = opps[opps.season.isin(seasons)].copy()
    s['group'] = [GROUPS[r].get(pos.get(p), 'OTHER') for r, p in zip(s.role, s.player)]
    s['sit'] = [situation(r) for r in s.itertuples()]
    out = {}
    for role, rs in s.groupby('role'):
        overall = rs.group.value_counts(normalize=True)
        for sit, ss in rs.groupby('sit'):
            share = ss.group.value_counts()
            n = len(ss)
            for g in overall.index:
                # shrink the situational share toward the overall share with 50 pseudo-plays
                out[(role, sit, g)] = ((share.get(g, 0) + 50 * overall[g]) / (n + 50)) / overall[g]
    return out


def score(opps, season, prior_team, prior_player, pos, factors, k):
    """Per-opportunity log probability under M0..M3, in week order. Returns a list of rows."""
    s = opps[opps.season == season].sort_values(['week', 'game_id'])
    s = s.assign(sit=[situation(r) for r in s.itertuples()])
    cands = s.groupby(['game_id', 'team', 'role']).player.agg(lambda x: sorted(set(x))).to_dict()
    in_season = collections.Counter()  # (role, team, player) -> count, weeks before the current week
    rows, week = [], None
    pending = collections.Counter()
    for r in s.itertuples():
        if r.week != week:
            in_season.update(pending)
            pending, week = collections.Counter(), r.week
        cand = cands[(r.game_id, r.team, r.role)]
        w0 = {p: max(prior_team.get((r.role, r.team, p), 0.0), FLOOR) for p in cand}
        w2_prior = {}
        for p in cand:
            own = prior_team.get((r.role, r.team, p))
            moved = prior_player.get((r.role, p))
            w2_prior[p] = max(own if own is not None else (moved[1] if moved else 0.0), FLOOR)
        w1 = {p: in_season[(r.role, r.team, p)] + k['M1'] * w0[p] for p in cand}
        w2 = {p: in_season[(r.role, r.team, p)] + k['M2'] * w2_prior[p] for p in cand}
        w3 = {p: w2[p] * factors.get((r.role, r.sit, GROUPS[r.role].get(pos.get(p), 'OTHER')), 1.0) for p in cand}
        g_real = GROUPS[r.role].get(pos.get(r.player), 'OTHER')
        row = {'season': season, 'week': int(r.week), 'game_id': r.game_id, 'team': r.team, 'role': r.role,
               'player': r.player, 'n_candidates': len(cand)}
        for name, w in (('M0', w0), ('M1', w1), ('M2', w2), ('M3', w3)):
            total = sum(w.values())
            same = [p for p in cand if GROUPS[r.role].get(pos.get(p), 'OTHER') == g_real]
            row[name] = math.log(w[r.player] / total) if w[r.player] > 0 else -50.0
            row[name + '_group'] = math.log(w[r.player] / sum(w[p] for p in same)) if w[r.player] > 0 else -50.0
            row[name + '_shares'] = {p: w[p] / total for p in cand} if r.team == 'MIN' and r.week == 11 else None
        rows.append(row)
        pending[(r.role, r.team, r.player)] += 1
    return rows


def bootstrap_diff(rows, a, b, reps=1000, seed=7):
    games = collections.defaultdict(list)
    for r in rows:
        games[r['game_id']].append(r[b] - r[a])  # positive = b has higher log probability = better
    keys = sorted(games)
    rng = random.Random(seed)
    point = statistics.fmean(x for g in keys for x in games[g])
    stats = []
    for _ in range(reps):
        pick = [keys[rng.randrange(len(keys))] for _ in keys]
        vals = [x for g in pick for x in games[g]]
        stats.append(statistics.fmean(vals))
    stats.sort()
    return round(point, 4), round(stats[int(0.025 * reps)], 4), round(stats[int(0.975 * reps)], 4)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--pbp-dir', required=True)
    ap.add_argument('--db', required=True)
    ap.add_argument('--out-dir', required=True)
    args = ap.parse_args(argv)
    seasons = (2022, 2023, 2024, 2025, 2026)
    opps = load(args.pbp_dir, seasons)
    pos = positions(args.db)
    unknown = opps[~opps.player.isin(pos)].player.nunique()
    print(f'opportunities {len(opps)}; players without a position {unknown} (scored in group OTHER)')

    out = {'inputs': {f'play_by_play_{y}.parquet': hashlib.sha256(Path(args.pbp_dir, f'play_by_play_{y}.parquet').read_bytes()).hexdigest()
                      for y in seasons}, 'floor': FLOOR, 'k_grid': K_GRID}
    # tune k on 2025 (priors 2024, situational factors 2022-2024)
    pt, pp = season_shares(opps, 2024)
    fac = situational_factors(opps, (2022, 2023, 2024), pos)
    tune = {}
    for k in K_GRID:
        rows = score(opps, 2025, pt, pp, pos, fac, {'M1': k, 'M2': k})
        tune[k] = {m: statistics.fmean(r[m] for r in rows) for m in ('M1', 'M2', 'M3')}
        print('tune 2025 k', k, {m: round(v, 4) for m, v in tune[k].items()})
    best = {m: max(K_GRID, key=lambda k: tune[k][m]) for m in ('M1', 'M2')}
    out['tune_2025'] = {str(k): v for k, v in tune.items()}
    out['k_chosen'] = best
    print('chosen k', best)

    # test on 2026 (priors 2025, factors 2022-2025)
    pt, pp = season_shares(opps, 2025)
    fac = situational_factors(opps, (2022, 2023, 2024, 2025), pos)
    rows = score(opps, 2026, pt, pp, pos, fac, best)
    summary = {}
    for role in ('receive', 'carry', 'all'):
        rr = [r for r in rows if role == 'all' or r['role'] == role]
        summary[role] = {'opportunities': len(rr), 'games': len({r['game_id'] for r in rr}),
                         'mean_candidates': round(statistics.fmean(r['n_candidates'] for r in rr), 2)}
        for m in ('M0', 'M1', 'M2', 'M3'):
            summary[role][m + '_logloss'] = round(-statistics.fmean(r[m] for r in rr), 4)
            summary[role][m + '_group_logloss'] = round(-statistics.fmean(r[m + '_group'] for r in rr), 4)
        for a, b in (('M0', 'M1'), ('M1', 'M2'), ('M2', 'M3'), ('M0', 'M3')):
            summary[role][f'{b}_vs_{a}_gain'] = bootstrap_diff(rr, a, b)
            summary[role][f'{b}_vs_{a}_group_gain'] = bootstrap_diff(rr, a + '_group', b + '_group')
    by_week = {}
    for wk in sorted({r['week'] for r in rows}):
        rr = [r for r in rows if r['week'] == wk]
        by_week[wk] = {m: round(-statistics.fmean(r[m] for r in rr), 4) for m in ('M0', 'M1', 'M2', 'M3')}
    out['test_2026'] = summary
    out['test_2026_by_week'] = by_week

    # the MIN week 11 case: mean predicted share over the game's opportunities, times the game's opportunity count
    case = {}
    for role in ('receive', 'carry'):
        rr = [r for r in rows if r['team'] == 'MIN' and r['week'] == 11 and r['role'] == role]
        actual = collections.Counter(r['player'] for r in rr)
        players = sorted({p for r in rr for p in r['M0_shares']})
        case[role] = {'opportunities': len(rr), 'players': {}}
        for p in players:
            case[role]['players'][p] = {'actual': actual[p], **{m: round(sum(r[m + '_shares'][p] for r in rr), 2)
                                                               for m in ('M0', 'M1', 'M2', 'M3')}}
    out['case_MIN_week11'] = case
    Path(args.out_dir).mkdir(parents=True, exist_ok=True)
    Path(args.out_dir, 'opportunity_shares.json').write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + '\n')
    print(json.dumps(summary, indent=1))
    print('by week', by_week)
    print(json.dumps(case, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
