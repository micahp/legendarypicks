#!/usr/bin/env python3
"""Chronological evaluation of the fitted play-call table, with a PASS/FAIL report (SLC v2, research).

Folds advance forward in time: 2023 is predicted from 2022, 2024 from 2022 to 2023, and 2025 from 2022 to 2024. Each fold
fits on earlier seasons only. The criteria below are fixed before any result is produced, and the verdict is computed from
them, so it cannot be changed by reading the numbers.

Usage: python3 playcall_eval.py --raw-dir <nflverse raw dir> --artifact <SLC-PLAYCALL-ARTIFACT-FIT-2010-2024-v1.json> \
           --out-dir <folder>
"""
import argparse
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path

import playcall_table as pt

FOLDS = ((2023, (2022,)), (2024, (2022, 2023)), (2025, (2022, 2023, 2024)))

# Pre-declared criteria. A criterion passes or fails on these thresholds only.
CRITERIA = {
    'C1_joint_beats_league_and_team_rate': 'joint log loss of the table is below both the league-only table and the team-rate '
                                           'baseline in every fold',
    'C2_family_beats_playcalllayer_2025': 'run-or-pass log loss of the family table is no worse than PlayCallLayer on 2025',
    'C3_calibration_2025': 'the largest gap between predicted and observed pass rate across deciles is at most 0.03 (2025)',
    'C4_personnel_frequencies': 'total variation between the expected and the observed personnel distribution is at most 0.05 in '
                                'every fold',
    'C5_team_behaviour_2025': 'correlation of predicted and observed team pass rate across the 32 teams is at least 0.80 (2025)',
    'C6_two_team_acceptance': 'two teams with opposite historical pass rates, in the same pre-snap state, differ in predicted '
                              'pass probability by at least 0.05 and in the direction of their history',
    'C7_legality': 'every sampled call in the acceptance draws is legal: its joint call has league support of at least 5 plays',
    'C8_determinism': 'the same seed gives the same sampled calls on a second run',
    'C9_situational_sense': 'league-wide, predicted pass rate on third and eleven or more is above first and ten',
}
MAX_CALIBRATION_GAP = 0.03
MAX_PERSONNEL_TV = 0.05
MIN_TEAM_CORRELATION = 0.80
MIN_TWO_TEAM_GAP = 0.05
SAMPLE_CALLS = 4000


def pearson(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    return sxy / math.sqrt(sxx * syy) if sxx and syy else float('nan')


def total_variation(p, q):
    keys = set(p) | set(q)
    return 0.5 * sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in keys)


def mean_loss(rows, losses):
    vals = [r for r in losses if r is not None]
    return sum(vals) / len(vals) if vals else float('nan')


def evaluate_fold(season, train_seasons, recs, layer):
    train = [r for r in recs if r['season'] in train_seasons]
    test = [r for r in recs if r['season'] == season]
    table = pt.fit(train)
    offense = [r for r in test if r['P'] != 'SPECIAL']
    out = {'season': season, 'train_seasons': list(train_seasons), 'test_calls': len(test),
           'offense_calls': len(offense), 'special_calls': len(test) - len(offense),
           'has_formation': table.has_formation}
    for model in ('table', 'league', 'rate'):
        steps = defaultdict(list)
        fallbacks = defaultdict(list)
        joint_no_f, joint_all = [], []
        for r in offense:
            s = pt.score_record(table, r, model)
            for step, value in s['loss'].items():
                steps[step].append(value)
            for step, value in s['fallback'].items():
                fallbacks[step].append(value)
            joint_all.append(sum(s['loss'].values()))
            joint_no_f.append(sum(v for k, v in s['loss'].items() if k != 'F'))
        out[model] = {
            'joint_no_formation': round(mean_loss(offense, joint_no_f), 6),
            'steps': {k: round(mean_loss(offense, v), 6) for k, v in steps.items()},
            'fallback_rate': {k: round(sum(v) / len(v), 6) for k, v in fallbacks.items()},
        }
        if table.has_formation:
            out[model]['joint_with_formation'] = round(mean_loss(offense, joint_all), 6)
    # family only, against PlayCallLayer on the same calls
    fam_table, fam_league, fam_layer, paired_table = [], [], [], []
    pass_probs = []
    layer_skipped = 0
    for r in offense:
        if r['R'] not in ('run', 'pass'):
            continue
        s_t = pt.score_record(table, r, 'family_only')
        s_l = pt.score_record(table, r, 'family_only_league')
        fam_table.append(s_t['loss']['R'])
        fam_league.append(s_l['loss']['R'])
        pass_probs.append((s_t['pass_prob'], 1.0 if r['R'] == 'pass' else 0.0, r['team']))
        if layer is not None:
            try:
                p = layer.p_dropback(int(float(r['raw_down'])), float(r['raw_togo']), float(r['raw_yl']),
                                     float(r['raw_score']), int(float(r['raw_qtr'])), float(r['raw_qsec']), r['team'])
            except ValueError:
                layer_skipped += 1  # a blank down, distance, field or clock: PlayCallLayer has no input for it
                continue
            p = min(max(p, 1e-6), 1 - 1e-6)
            fam_layer.append(-math.log(p if r['R'] == 'pass' else 1 - p))
            paired_table.append(s_t['loss']['R'])  # the table, on the same calls PlayCallLayer scored
    out['family'] = {'table_team_aware': round(mean_loss(fam_table, fam_table), 6),
                     'league_only': round(mean_loss(fam_league, fam_league), 6)}
    if fam_layer:
        out['family']['playcalllayer'] = round(mean_loss(fam_layer, fam_layer), 6)
        out['family']['calls_compared_with_playcalllayer'] = len(fam_layer)
        out['family']['playcalllayer_skipped_blank_input'] = layer_skipped
        out['family']['table_team_aware_on_same_calls'] = round(mean_loss(fam_layer, paired_table), 6)
    # calibration of the family pass probability, in deciles
    ordered = sorted(pass_probs)
    deciles = []
    n = len(ordered)
    for d in range(10):
        chunk = ordered[d * n // 10:(d + 1) * n // 10]
        if chunk:
            deciles.append({'mean_predicted': round(sum(p for p, _o, _t in chunk) / len(chunk), 4),
                            'observed': round(sum(o for _p, o, _t in chunk) / len(chunk), 4), 'n': len(chunk)})
    out['calibration_deciles'] = deciles
    out['calibration_max_gap'] = round(max(abs(x['mean_predicted'] - x['observed']) for x in deciles), 4) if deciles else None
    # expected personnel distribution against the observed one, over every call in the season
    expected = defaultdict(float)
    for r in test:
        p_dist, _f = table.dist('P', 'P', pt.model_features(table, r, True))
        for k, v in p_dist.items():
            expected[k] += v / len(test)
    observed = Counter(r['P'] for r in test)
    observed_p = {k: v / len(test) for k, v in observed.items()}
    out['personnel_total_variation'] = round(total_variation(dict(expected), observed_p), 6)
    # team pass rates, expected against observed
    team_pred, team_obs = defaultdict(list), defaultdict(list)
    for p, o, team in pass_probs:
        team_pred[team].append(p)
        team_obs[team].append(o)
    teams = sorted(team_pred)
    pred = [sum(team_pred[t]) / len(team_pred[t]) for t in teams]
    obs = [sum(team_obs[t]) / len(team_obs[t]) for t in teams]
    out['team_pass_rate_correlation'] = round(pearson(pred, obs), 4) if len(teams) > 2 else None
    out['team_pass_rate'] = {t: {'predicted': round(p, 4), 'observed': round(o, 4)}
                             for t, p, o in zip(teams, pred, obs)}
    return out, table


def acceptance(table, recs, train_seasons):
    """Two teams with opposite histories, in one pre-snap state, and a legality and determinism check on sampled calls."""
    history = defaultdict(lambda: [0, 0])
    for r in recs:
        if r['season'] in train_seasons and r['R'] in ('run', 'pass'):
            history[r['team']][0] += 1
            history[r['team']][1] += int(r['R'] == 'pass')
    ranked = sorted((rate / n, team) for team, (n, rate) in
                    ((t, (v[0], v[1])) for t, v in history.items()) if n >= 300)
    lo_team, hi_team = ranked[0][1], ranked[-1][1]
    situation = {'down': '1', 'dist': '10', 'field': '36-50', 'score': '0', 'time': 'q1'}
    support = pt.Support([r for r in recs if r['season'] in train_seasons])
    result = {'situation': situation, 'pass_rate_history': {
        lo_team: round(ranked[0][0], 4), hi_team: round(ranked[-1][0], 4)}, 'teams': {}}
    for team in (lo_team, hi_team):
        rng = random.Random(f'accept|{team}|1')
        calls = [pt.sample_call(table, team, situation, rng, 'table', support) for _ in range(SAMPLE_CALLS)]
        offense = [c for c in calls if c['P'] != 'SPECIAL']
        legal = sum(1 for c in offense if pt.is_legal(support, c))
        result['teams'][team] = {
            'sampled_calls': len(calls), 'offense_calls': len(offense),
            'sample_pass_rate': round(sum(1 for c in offense if c['R'] == 'pass') / max(len(offense), 1), 4),
            'legal_share': round(legal / max(len(offense), 1), 6),
            'personnel_mix': {k: round(v / len(offense), 4) for k, v in Counter(c['P'] for c in offense).most_common(6)},
        }
    result['pass_rate_gap'] = round(result['teams'][hi_team]['sample_pass_rate']
                                    - result['teams'][lo_team]['sample_pass_rate'], 4)
    result['lo_team'], result['hi_team'] = lo_team, hi_team
    # determinism: the same seed gives the same first 200 calls
    a = [pt.sample_call(table, hi_team, situation, random.Random('det|1'), 'table', support) for _ in range(200)]
    b = [pt.sample_call(table, hi_team, situation, random.Random('det|1'), 'table', support) for _ in range(200)]
    result['deterministic'] = a == b
    return result


def situational_sense(table, support):
    """League-wide predicted pass share on third and eleven or more, and first and ten, drawn from the league table."""
    out = {}
    for label, sit in (('1st_and_10', {'down': '1', 'dist': '10'}), ('3rd_and_11plus', {'down': '3', 'dist': '11+'})):
        rng = random.Random(f'sense|{label}')
        full = {'field': '36-50', 'score': '0', 'time': 'q2', **sit}
        passes = 0
        for _ in range(SAMPLE_CALLS):
            c = pt.sample_call(table, pt.NA, full, rng, 'league', support)
            passes += int(c.get('R') == 'pass')
        out[label] = round(passes / SAMPLE_CALLS, 4)
    return out


def judge(folds, accept, sense, determinism_ok):
    results = {}
    results['C1_joint_beats_league_and_team_rate'] = all(
        f['table']['joint_no_formation'] < f['league']['joint_no_formation']
        and f['table']['joint_no_formation'] < f['rate']['joint_no_formation'] for f in folds)
    f25 = folds[-1]
    results['C2_family_beats_playcalllayer_2025'] = (
        'playcalllayer' in f25['family']
        and f25['family']['table_team_aware_on_same_calls'] <= f25['family']['playcalllayer'])
    results['C3_calibration_2025'] = f25['calibration_max_gap'] is not None and f25['calibration_max_gap'] <= MAX_CALIBRATION_GAP
    results['C4_personnel_frequencies'] = all(f['personnel_total_variation'] <= MAX_PERSONNEL_TV for f in folds)
    corr = f25['team_pass_rate_correlation']
    results['C5_team_behaviour_2025'] = corr is not None and corr >= MIN_TEAM_CORRELATION
    lo, hi = accept['lo_team'], accept['hi_team']
    gap_ok = accept['teams'][hi]['sample_pass_rate'] - accept['teams'][lo]['sample_pass_rate'] >= MIN_TWO_TEAM_GAP
    results['C6_two_team_acceptance'] = gap_ok and accept['pass_rate_history'][hi] > accept['pass_rate_history'][lo]
    results['C7_legality'] = all(accept['teams'][t]['legal_share'] == 1.0 for t in (lo, hi))
    results['C8_determinism'] = determinism_ok and accept['deterministic']
    results['C9_situational_sense'] = sense['3rd_and_11plus'] > sense['1st_and_10']
    return {k: ('PASS' if v else 'FAIL') for k, v in results.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--raw-dir', type=Path, required=True)
    ap.add_argument('--artifact', type=Path, required=True)
    ap.add_argument('--out-dir', type=Path, required=True)
    args = ap.parse_args()
    import slc_playcall
    layer = slc_playcall.PlayCallLayer.load(args.artifact)
    recs, excluded = pt.records(args.raw_dir, [2022, 2023, 2024, 2025])
    folds = []
    for season, train_seasons in FOLDS:
        fold, _table = evaluate_fold(season, train_seasons, recs, layer if season == 2025 else None)
        folds.append(fold)
    train_all = (2022, 2023, 2024)
    table = pt.fit([r for r in recs if r['season'] in train_all])
    accept = acceptance(table, recs, train_all)
    support = pt.Support([r for r in recs if r['season'] in train_all])
    sense = situational_sense(table, support)
    first = [pt.sample_call(table, 'DET', {'down': '2', 'dist': '7-9', 'field': '21-35', 'score': '-3..-1', 'time': 'q3'},
                            random.Random('repro|1'), 'table') for _ in range(50)]
    second = [pt.sample_call(table, 'DET', {'down': '2', 'dist': '7-9', 'field': '21-35', 'score': '-3..-1', 'time': 'q3'},
                             random.Random('repro|1'), 'table') for _ in range(50)]
    verdict = judge(folds, accept, sense, first == second)
    result = {'folds': folds, 'acceptance': accept, 'situational_sense': sense,
              'excluded_by_reason': dict(excluded), 'criteria': CRITERIA, 'thresholds': {
                  'MAX_CALIBRATION_GAP': MAX_CALIBRATION_GAP, 'MAX_PERSONNEL_TV': MAX_PERSONNEL_TV,
                  'MIN_TEAM_CORRELATION': MIN_TEAM_CORRELATION, 'MIN_TWO_TEAM_GAP': MIN_TWO_TEAM_GAP,
                  'K': pt.K, 'MIN_SUPPORT': pt.MIN_SUPPORT, 'SAMPLE_CALLS': SAMPLE_CALLS},
              'verdict': verdict, 'overall': 'PASS' if all(v == 'PASS' for v in verdict.values()) else 'FAIL'}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / 'playcall_eval.json').write_text(json.dumps(result, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'overall': result['overall'], 'verdict': verdict}, sort_keys=True))


if __name__ == '__main__':
    main()
