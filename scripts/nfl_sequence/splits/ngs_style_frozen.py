"""Frozen constants for the NGS team-style layer of the decision model (spec v2).

Team-week values for regular-season Weeks 1 to 18 come from the nflverse Next Gen Stats releases. The constants (means,
standard deviations, and tertile cut points) are fitted on the 2016 to 2024 seasons only. No 2025 or 2026 value is used.

Measures per team and week, all weighted within the team-week:
  time to throw            avg_time_to_throw (passing, weighted by attempts)
  aggressiveness           aggressiveness (passing, weighted by attempts)
  eight-plus defenders     percent_attempts_gte_eight_defenders (rushing, weighted by rush attempts)
  receiver separation      avg_separation (receiving, weighted by targets)

Composite: the equal-weight mean of the four measures, each standardised with the 2016 to 2024 mean and standard
deviation. Tertile cut points are the 1/3 and 2/3 quantiles of the composite over the 2016 to 2024 team-weeks.

Usage: python3 ngs_style_frozen.py   (prints the constants, writes results/ngs_style_frozen.json in the scratchpad)
"""
import json
import os

import numpy as np
import pyarrow.parquet as pq

D = '/root/lp-snapshots/nfl-backfill-2026-10-27/raw/nextgen_stats'
OUT = '/tmp/claude-0/-root/4a715766-ff4b-4980-99e5-dc209eaac7d4/scratchpad/nfl-splits/results'
FIT_SEASONS = range(2016, 2025)
MEASURES = ('time_to_throw', 'aggressiveness', 'eight_plus', 'separation')


def load(name, cols):
    frame = pq.read_table(f'{D}/{name}', columns=cols).to_pandas()
    frame = frame[(frame.season_type == 'REG') & (frame.week >= 1) & (frame.week <= 18)]
    return frame[frame.season.isin(list(FIT_SEASONS))]


def weighted(frame, value, weight, out):
    frame = frame.dropna(subset=[value, weight])
    frame = frame.assign(w=frame[value] * frame[weight])
    g = frame.groupby(['season', 'week', 'team_abbr'])
    s = g.w.sum() / g[weight].sum()
    return s.rename(out)


def team_weeks():
    passing = load('ngs_passing.parquet', ['season', 'season_type', 'week', 'team_abbr', 'avg_time_to_throw',
                                           'aggressiveness', 'attempts'])
    receiving = load('ngs_receiving.parquet', ['season', 'season_type', 'week', 'team_abbr', 'avg_separation',
                                               'targets'])
    rushing = load('ngs_rushing.parquet', ['season', 'season_type', 'week', 'team_abbr',
                                           'percent_attempts_gte_eight_defenders', 'rush_attempts'])
    parts = [
        weighted(passing, 'avg_time_to_throw', 'attempts', 'time_to_throw'),
        weighted(passing, 'aggressiveness', 'attempts', 'aggressiveness'),
        weighted(rushing, 'percent_attempts_gte_eight_defenders', 'rush_attempts', 'eight_plus'),
        weighted(receiving, 'avg_separation', 'targets', 'separation'),
    ]
    frame = parts[0].to_frame()
    for p in parts[1:]:
        frame = frame.join(p, how='inner')
    return frame.reset_index()


def main():
    tw = team_weeks()
    print('team-weeks with all four measures, 2016 to 2024:', len(tw))
    frozen = {'fit_seasons': [FIT_SEASONS.start, FIT_SEASONS.stop - 1], 'team_weeks': int(len(tw)), 'measures': {}}
    z = []
    for m in MEASURES:
        mu, sd = float(tw[m].mean()), float(tw[m].std(ddof=1))
        frozen['measures'][m] = {'mean': mu, 'sd': sd}
        z.append((tw[m] - mu) / sd)
    composite = sum(z) / len(z)
    q1, q2 = np.percentile(composite, [100 / 3, 200 / 3])
    frozen['composite_cut_points'] = {'low_mid': float(q1), 'mid_high': float(q2)}
    print(json.dumps(frozen, indent=1))
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, 'ngs_style_frozen.json'), 'w') as handle:
        json.dump(frozen, handle, indent=1)


if __name__ == '__main__':
    main()
