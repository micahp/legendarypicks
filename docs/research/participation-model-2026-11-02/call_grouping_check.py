#!/usr/bin/env python3
"""Does the drawn grouping go with the call? A check of call-conditioned grouping transitions (research).

For every 2025 snap the grouping is drawn from a lineup table fitted on 2022 to 2024, given the team, the situation cell
(participation_field.supported_cell) and the observed previous grouping. The v4 table also gets the snap's observed call
(run or dropback), as the engine passes it; the v3 table ignores it. Per drawn grouping, the share of dropbacks is compared
with the observed share in that grouping. Also reported: the mean log probability of the observed grouping.

Usage: python3 call_grouping_check.py --tables <scrimmage_participation.csv.gz with qb_dropback> --v3 <field> --v4 <field>
           --season 2025 --out <json> [--seeds 3]
"""
import argparse
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / 'scripts' / 'nfl_sequence'))
import lineup_fit  # noqa: E402
import participation_field as pf  # noqa: E402
import participation_model as pm  # noqa: E402

MIN_GROUP_SNAPS = 200  # groupings with fewer observed snaps are pooled as 'other' in the table


def snaps(tables, season):
    games = defaultdict(list)
    for row in pm.load_scrimmage(tables, {season}):
        call = lineup_fit.intent_of(row)
        if call is None:
            raise ValueError('the table has no qb_dropback column; rebuild it with build_tables.py')
        games[(row['game_id'], row['posteam'])].append((int(row['play_id']), row['group'], pm.cell_of(row), call))
    return {key: [item[1:] for item in sorted(items)] for key, items in games.items()}


def run(field, games, seeds, use_call):
    drawn = defaultdict(Counter)  # grouping -> call -> count
    log_prob, scored, skipped = 0.0, 0, Counter()
    for seed in range(seeds):
        rng = random.Random(seed)
        for (_game, team), seq in sorted(games.items()):
            prev = pf.START
            for group, cell, call in seq:
                used = field.supported_cell(cell)
                if used is None:
                    skipped['no_supported_cell'] += 1
                    prev = group
                    continue
                probs = field.group_probs(team, used, prev, call if use_call else None)
                groups = sorted(probs)
                pick = rng.choices(groups, weights=[probs[g] for g in groups], k=1)[0]
                drawn[pick][call] += 1
                if seed == 0:
                    p = probs.get(group, 0.0)
                    if p > 0:
                        log_prob += math.log(p)
                        scored += 1
                    else:
                        skipped['observed_grouping_not_in_table'] += 1
                prev = group  # the observed previous grouping, so each snap is scored on the same history
    return drawn, log_prob / scored, scored, dict(skipped)


def table(drawn, observed):
    big = {g for g, c in observed.items() if sum(c.values()) >= MIN_GROUP_SNAPS}
    def pooled(counts):
        out = defaultdict(Counter)
        for g, c in counts.items():
            out[g if g in big else 'other'].update(c)
        return out
    obs, sim = pooled(observed), pooled(drawn)
    obs_n = sum(sum(c.values()) for c in obs.values())
    rows, weighted_error = [], 0.0
    for g in sorted(obs, key=lambda g: -sum(obs[g].values())):
        n_obs = sum(obs[g].values())
        n_sim = sum(sim[g].values())
        rate_obs = obs[g]['dropback'] / n_obs
        rate_sim = sim[g]['dropback'] / n_sim if n_sim else None
        rows.append({'grouping': g, 'observed_snaps': n_obs, 'observed_dropback_rate': round(rate_obs, 4),
                     'simulated_snaps': n_sim, 'simulated_dropback_rate': round(rate_sim, 4) if rate_sim is not None else None})
        if rate_sim is not None:
            weighted_error += n_obs / obs_n * abs(rate_sim - rate_obs)
    return rows, weighted_error


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tables', type=Path, required=True)
    ap.add_argument('--v3', type=Path, required=True)
    ap.add_argument('--v4', type=Path, required=True)
    ap.add_argument('--season', type=int, default=2025)
    ap.add_argument('--seeds', type=int, default=3)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    games = snaps(args.tables, args.season)
    observed = defaultdict(Counter)
    for seq in games.values():
        for group, _cell, call in seq:
            observed[group][call] += 1
    report = {'season': args.season, 'seeds': args.seeds, 'team_games': len(games),
              'snaps': sum(len(s) for s in games.values())}
    for name, path, use_call in (('v3_unconditioned', args.v3, False), ('v4_given_call', args.v4, True)):
        field = pf.Field(json.loads(path.read_text()), pf.sha256_file(path))
        if any(s != args.season - 1 - i for i, s in enumerate(sorted(field.seasons, reverse=True))) or \
                max(field.seasons) >= args.season:
            raise ValueError(f'{path} is fitted on {field.seasons}; the check needs seasons before {args.season}')
        drawn, mean_log_prob, scored, skipped = run(field, games, args.seeds, use_call)
        rows, error = table(drawn, observed)
        report[name] = {'table': path.name, 'table_sha256': field.sha256, 'fit_seasons': field.seasons,
                        'mean_log_prob_observed_grouping': round(mean_log_prob, 5), 'scored_snaps': scored,
                        'skipped': skipped, 'weighted_abs_dropback_rate_error': round(error, 5),
                        'by_grouping': rows, 'field_status': dict(field.status)}
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True))
    for name in ('v3_unconditioned', 'v4_given_call'):
        r = report[name]
        print(name, 'mean log prob', r['mean_log_prob_observed_grouping'], 'weighted dropback-rate error',
              r['weighted_abs_dropback_rate_error'])
    print(f"{'grouping':12s} {'obs n':>7s} {'obs':>6s} {'v3':>6s} {'v4':>6s}")
    v3 = {r['grouping']: r for r in report['v3_unconditioned']['by_grouping']}
    for r in report['v4_given_call']['by_grouping']:
        print(f"{r['grouping']:12s} {r['observed_snaps']:7d} {r['observed_dropback_rate']:6.3f} "
              f"{v3[r['grouping']]['simulated_dropback_rate']:6.3f} {r['simulated_dropback_rate']:6.3f}")


if __name__ == '__main__':
    main()
