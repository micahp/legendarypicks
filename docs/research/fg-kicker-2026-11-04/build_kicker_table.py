#!/usr/bin/env python3
"""Build the kicker table the engine's --playcall-fg-kicker flag loads (research, amendment 6).

Kicker ability is fitted on the field-goal attempts of 1999 to --through-season (play-by-play, which agrees with the
published kicker stats on all 4,862 kicker-weeks of 2016 to 2025): each kicker's logit offset against the league curve,
the posterior mode with the parameters kicker_fg_check.py selected (sigma 0.3, recency 0.5), as of the first week of the
next season, and his career longest make (the published fg_long). Kicker identity comes from the published weekly roster
of --assign-season: the team's one active K each week (status ACT). Only identity is read from that season, no outcome.

Usage: python3 build_kicker_table.py --raw <nflverse backfill raw dir> --through-season 2025 --assign-season 2026 --out <json>
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kicker_fg_check as kc  # noqa: E402

SIGMA, RECENCY = 0.3, 0.5  # selected on 2016 to 2021 (kicker_fg_check.json)


def assignments(raw, season):
    import pyarrow.parquet as pq
    t = pq.read_table(Path(raw) / 'weekly_rosters' / f'roster_weekly_{season}.parquet',
                      columns=['season', 'week', 'team', 'position', 'status', 'gsis_id']).to_pydict()
    active, practice, teams = defaultdict(set), defaultdict(set), set()
    for i in range(len(t['position'])):
        key = (int(t['season'][i]), int(t['week'][i]), t['team'][i])
        teams.add(key)
        if t['position'][i] == 'K' and t['status'][i] == 'ACT':
            active[key].add(t['gsis_id'][i])
        elif t['position'][i] == 'K' and t['status'][i] == 'DEV':
            practice[key].add(t['gsis_id'][i])
    several = {k: sorted(v) for k, v in active.items() if len(v) != 1}
    if several:
        raise ValueError(f'team-weeks with more than one active kicker: {several}')
    # A team-week with no active K kicked with a practice-squad K elevated for the game: the weekly roster can be captured
    # after the elevation reverted (2026 week 8, MIA: Zane Gonzalez is DEV in the 2026-10-27 file and ACT in the
    # 2026-11-04 republication). Exactly one practice-squad K is required; anything else refuses.
    elevated = {}
    for key in sorted(teams - set(active)):
        if len(practice[key]) != 1:
            raise ValueError(f'{key} has no active kicker and {len(practice[key])} practice-squad kickers')
        elevated[key] = set(practice[key])
        print(f'no active K for {key}: using practice-squad K {sorted(practice[key])[0]}')
    print(f'{len(elevated)} team-weeks take an elevated practice-squad kicker')
    return sorted((s, w, team, next(iter(v))) for (s, w, team), v in {**active, **elevated}.items())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--raw', type=Path, required=True)
    ap.add_argument('--through-season', type=int, required=True)
    ap.add_argument('--assign-season', type=int, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    if args.assign_season <= args.through_season:
        raise ValueError('the assignment season must come after every fitted season')
    attempts = [r for r in kc.load_attempts(args.raw)[0] if r['season'] <= args.through_season]
    published = {k: v for k, v in kc.load_published(args.raw).items() if k[1] <= args.through_season}
    history = kc.career_long(published)
    first = kc.league_curve(attempts, kc.FIRST + 1, 1)
    curves = {}
    by_kicker = defaultdict(list)
    for r in attempts:  # each kick judged against its own week's league curve, as in the check
        week = (r['season'], r['week'])
        if week not in curves:
            curves[week] = first if r['season'] == kc.FIRST else kc.league_curve(attempts, *week)
        curve = curves[week]
        by_kicker[r['kicker_player_id']].append(
            (r['season'], kc.logit(kc.p_league(curve, r['kick_distance'])), r['field_goal_result'] == 'made'))
    target = args.through_season + 1
    kickers = {pid: {'offset': round(kc.kicker_offset(h, SIGMA, RECENCY, target), 6), 'attempts': len(h),
                     'career_long': kc.long_before(history, pid, target, 1)}
               for pid, h in sorted(by_kicker.items())}
    assigned = assignments(args.raw, args.assign_season)
    table = {'schema': 'kicker-fg-v1', 'fit_seasons': list(range(kc.FIRST, args.through_season + 1)),
             'sigma': SIGMA, 'recency': RECENCY, 'kickers': kickers, 'assignments': assigned,
             'assign_season': args.assign_season,
             'assigned_without_history': sorted({pid for _s, _w, _t, pid in assigned if pid not in kickers})}
    args.out.write_text(json.dumps(table, sort_keys=True, separators=(',', ':')))
    print(f'{len(kickers)} kickers fitted; {len(assigned)} team-weeks assigned; '
          f'{len(table["assigned_without_history"])} assigned kickers with no earlier kick')


if __name__ == '__main__':
    main()
