#!/usr/bin/env python3
"""SLC-CEG Phase 1: inclusion and exclusion waterfall, raw play-by-play -> v2 scrimmage pool -> CEG training population.

v2's population is recomputed by running v2's own pool code (`e1_drive.classify` at 8a1d9842, imported from this tree)
on the nflverse rows, in the order v2 reads them (`e1_drive.load`: every row with week <= 18, ordered by game and play;
`e2_reference.load`: regulation_only=True, include_qb_scrambles=True for the QB-decision stack). The v2 packs read the
`nfl_pbp` table of the frozen database, not these files, so counts can differ slightly from the packs; the reasons are
v2's own.

Stages:
  S0 raw         every nflverse row, regular season and postseason
  S1 weeks       season_type REG and week <= 18 (v2 reads no postseason)
  S2 play types  play_type in run, pass, punt, field_goal and down 1-4 (kickoffs, tries, kneels, spikes, no_play rows
                 and timeouts never enter the scrimmage pool; v2 handles kickoffs and tries with other tables)
  S3 regulation  quarter 1-4 (overtime plays are not sampled; overtime draws regulation rows)
  S4 classify    v2's classify(): penalties, missing next snap, turnover touchdowns, and the rest, each counted
  v2 pool        what is left
  CEG            the Phase 1 snap population (ceg_event_tables): every snap class, regular season and postseason

Each exclusion is broken down by season, CEG play class, down, field zone, and whether the play is the last snap of a
quarter or inside the last two minutes of a half.

Usage: python3 ceg_waterfall.py --raw DIR --tables DIR --out FILE
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e1_drive as e1  # noqa: E402  (v2's pool code, 8a1d9842)

SEASONS = (2022, 2023, 2024, 2025, 2026)
KEY = ['game_id', 'play_id']


def zone(y):
    if y != y:
        return 'none'
    return 'own_1_19' if y >= 81 else 'own_20_49' if y >= 51 else 'opp_49_21' if y >= 21 else 'opp_20_6' if y >= 6 else 'opp_5_1'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--raw', required=True, type=Path)
    ap.add_argument('--tables', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    args = ap.parse_args(argv)
    labels = pd.read_parquet(args.tables / 'labels.parquet', columns=KEY + ['season', 'play_class'])
    post = pd.read_parquet(args.tables / 'post.parquet', columns=KEY + ['runoff_status'])
    ceg_cls = labels.merge(post, on=KEY, how='left').set_index(KEY)
    out = {'stages': {}, 'v2_classify_exclusions': {}, 'breakdown': {}, 'ceg_snaps': {}}
    breakdown = collections.defaultdict(collections.Counter)  # (season, reason) -> Counter of 'dim=value'
    for season in SEASONS:
        cols = list(dict.fromkeys(list(e1.COLUMNS) + ['season_type', 'half_seconds_remaining']))
        d = pd.read_parquet(args.raw / f'play_by_play_{season}.parquet', columns=cols)
        d['play_id'] = d['play_id'].astype('int64')
        st = {'S0_raw_rows': int(len(d))}
        d1 = d[d.season_type.eq('REG') & d.week.le(18)].sort_values(KEY)
        st['S1_reg_week_le_18'] = int(len(d1))
        rows = [{k: (None if v != v else v) if isinstance(v, float) else v for k, v in r.items()}
                for r in d1[list(e1.COLUMNS) + ['half_seconds_remaining']].to_dict('records')]
        by_game = collections.defaultdict(list)
        for r in rows:
            by_game[r['game_id']].append(r)
        s2 = s3 = kept = 0
        reasons = collections.Counter()
        not_play_type = collections.Counter()
        for plays in by_game.values():
            for i, row in enumerate(plays):
                if row['play_type'] not in e1.PLAY_TYPES or row['down'] is None or not 1 <= row['down'] <= 4:
                    not_play_type[str(row['play_type'])] += 1
                    continue
                s2 += 1
                if row['qtr'] is None or int(row['qtr']) > 4:
                    reasons['overtime (regulation-only pool)'] += 1
                    reason = 'overtime (regulation-only pool)'
                else:
                    s3 += 1
                    nxt = plays[i + 1] if i + 1 < len(plays) else None
                    excluded = collections.Counter()
                    hit = e1.classify(row, nxt, excluded, include_qb_scrambles=True)
                    if hit is not None:
                        kept += 1
                        continue
                    reason = next(iter(excluded))
                    reasons[reason] += 1
                key = (row['game_id'], int(row['play_id']))
                c = ceg_cls.loc[key] if key in ceg_cls.index else None
                b = breakdown[(season, reason)]
                b[f"class={c['play_class'] if c is not None else 'not_in_ceg'}"] += 1
                b[f"down={row['down']}"] += 1
                b[f"zone={zone(row['yardline_100'])}"] += 1
                if c is not None and c['runoff_status'] in ('last_snap_of_quarter', 'last_snap_of_game'):
                    b['last_snap_of_quarter_or_game'] += 1
                hs = row.get('half_seconds_remaining')
                if hs is not None and hs <= 120:
                    b['inside_last_2_minutes_of_half'] += 1
        st['S2_scrimmage_play_types_down_1_4'] = s2
        st['S2_left_out_by_play_type'] = dict(not_play_type.most_common())
        st['S3_regulation'] = s3
        st['v2_pool_rows'] = kept
        out['stages'][season] = st
        out['v2_classify_exclusions'][season] = dict(reasons.most_common())
        snaps = labels[labels.season.eq(season)]
        out['ceg_snaps'][season] = {k: int(v) for k, v in snaps.play_class.value_counts().items()}
        print(season, st['S0_raw_rows'], st['S1_reg_week_le_18'], s2, s3, kept, dict(reasons.most_common(4)), flush=True)
    out['breakdown'] = {f'{s}|{r}': dict(c.most_common()) for (s, r), c in sorted(breakdown.items())}
    args.out.write_text(json.dumps(out, indent=1, sort_keys=True) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
