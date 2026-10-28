"""Causal check for team tendencies: same drive starts and seeds, two offenses, S0 versus the team-tendency sampler.

Reads only plays before a 2025 cutoff (e1.load refuses the 2026 holdout). Tendencies come from 2022 to 2024 only.
Teams are chosen from prior-season first-down run rates: the most run-heavy and the most pass-heavy offense with enough
first-down plays. The defense is the team whose prior-season run rate is nearest the league median.
Under S0 the team does not enter the simulation, so the two offenses must give identical event counts. Under the
team-tendency sampler they should differ in the direction their tendencies predict.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e1_drive as e1  # noqa: E402
import team_tendency as tt  # noqa: E402

CUTOFF = (2025, 10)
TARGET_SEASON = 2025
START_NAMES = ('own25_q1_900', 'midfield_q3_900')
SCRIMMAGE = ('run', 'pass_complete', 'pass_incomplete', 'sack', 'interception', 'fumble_lost')
MIN_FIRST_DOWN_PLAYS = 200


def first_down_run_rates(prior_rows):
    runs, totals = Counter(), Counter()
    for row in prior_rows:
        if row['down'] == 1 and row['play_type'] in ('run', 'pass') and row['posteam']:
            totals[row['posteam']] += 1
            runs[row['posteam']] += row['play_type'] == 'run'
    return {team: runs[team] / totals[team] for team in totals if totals[team] >= MIN_FIRST_DOWN_PLAYS}


def drive_counts(start, seeds, pool, policy, label):
    events, drives, incomplete = Counter(), 0, 0
    for seed in seeds:
        plays, terminal = e1.simulate(start, seed, pool, f'{label}-{seed}', sampling_policy=policy)
        if plays is None:
            incomplete += 1
            continue
        drives += 1
        events.update(play['event_type'] for play in plays if play['event_type'] in SCRIMMAGE)
    scrimmage = sum(events.values())
    return {'drives': drives, 'incomplete_drives': incomplete, 'scrimmage_plays': scrimmage,
            'run_share': round(events['run'] / scrimmage, 4) if scrimmage else None,
            'events': dict(events)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=e1.DEFAULT_DB)
    ap.add_argument('--seeds', type=int, default=300)
    ap.add_argument('--out')
    args = ap.parse_args()

    rows = e1.load(args.db, eligible_before=CUTOFF)
    prior = [row for row in rows if int(row['season']) < TARGET_SEASON]
    pool, excluded = e1.build_pool(rows)
    tendencies = tt.build_from_rows(prior, TARGET_SEASON)
    sampler = tt.TendencySampler(tendencies)
    rates = first_down_run_rates(prior)
    ordered = sorted(rates, key=rates.get)
    pass_team, run_team = ordered[0], ordered[-1]
    median_team = min((t for t in ordered if t not in (pass_team, run_team)),
                      key=lambda t: abs(rates[t] - sorted(rates.values())[len(rates) // 2]))
    seeds = range(1, args.seeds + 1)
    report = {'cutoff': list(CUTOFF), 'target_season': TARGET_SEASON, 'tendency_seasons': sorted(
        {int(r['season']) for r in prior}), 'pool_plays_before_cutoff': sum(len(v) for v in pool.values()),
        'excluded_from_pool': dict(excluded), 'tendency_manifest_sha256': tendencies.manifest['sha256'],
        'defense': median_team, 'first_down_run_rate_prior_seasons': {
            pass_team: round(rates[pass_team], 4), run_team: round(rates[run_team], 4),
            median_team: round(rates[median_team], 4)},
        'seeds': args.seeds, 'results': {}}
    for name in START_NAMES:
        report['results'][name] = {}
        for team in (run_team, pass_team):
            start = dict(e1.STARTS[name], offense=team, defense=median_team)
            report['results'][name][team] = {
                'S0': drive_counts(start, seeds, pool, None, f'{name}-{team}-S0'),
                'S2_team_tendency': drive_counts(start, seeds, pool, sampler, f'{name}-{team}-S2'),
            }
    text = json.dumps(report, indent=1, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + '\n', encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
