#!/usr/bin/env python3
"""Play-outcome endpoints for the snap-anchored cohort games (weeks 1-5 only).

Only published plays.csv fields are read. Nothing is derived: drive identifiers are not published in plays.csv,
so drive results are reported as unavailable rather than reconstructed from possession changes.
Movement evaluation is separate; these endpoints do not feed the movement metrics.
"""
import csv
from collections import Counter
from pathlib import Path

DATA = Path('/root/nfl-tracking-data/bdb2025/code-data')
MANIFEST = Path(__file__).resolve().parents[2] / 'docs/research/bdb2025-snap-anchored-cohort-v1.csv'
OUT = Path(__file__).resolve().parents[2] / 'docs/research/bdb2025-snap-cohort-play-endpoints-v1.csv'
WEEKS = (1, 2, 3, 4, 5)
ENDPOINTS = ('yardsGained', 'expectedPointsAdded', 'passResult', 'penaltyYards', 'playNullifiedByPenalty')
MISSING = ('', 'NA')


def main():
    with (DATA / 'games.csv').open(newline='', encoding='utf-8') as f:
        game_week = {r['gameId']: int(r['week']) for r in csv.DictReader(f)}
    with (DATA / 'plays.csv').open(newline='', encoding='utf-8') as f:
        plays = {(r['gameId'], r['playId']): r for r in csv.DictReader(f) if game_week.get(r['gameId']) in WEEKS}
    with MANIFEST.open(newline='', encoding='utf-8') as f:
        cohort = list(csv.DictReader(f))
    if any(int(r['week']) not in WEEKS for r in cohort):
        raise SystemExit('cohort contains a reserved week')
    if len(cohort) != len(plays) or any(game_week.get(r['gameId']) != int(r['week']) for r in cohort):
        raise SystemExit(f'cohort ({len(cohort)}) does not reconcile to weeks 1-5 of plays.csv ({len(plays)})')
    rows, per_week = [], {}
    for c in cohort:
        p = plays[(c['gameId'], c['playId'])]
        out = {'week': c['week'], 'gameId': c['gameId'], 'playId': c['playId'],
               'eligible_input': c['eligible_input'], 'exclusion_reason': c['exclusion_reason']}
        out.update({k: p[k] for k in ENDPOINTS})
        rows.append(out)
        stats = per_week.setdefault(c['week'], Counter())
        stats['plays'] += 1
        stats['eligible_input'] += c['eligible_input'] == 'True'
        for k in ENDPOINTS:
            stats[f'{k}_published'] += p[k] not in MISSING
    with OUT.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    for week in sorted(per_week):
        print(f'week {week}:', dict(per_week[week]))
    print('drive identifier columns in plays.csv:', [k for k in next(iter(plays.values())) if 'drive' in k.lower()])
    print('rows written:', len(rows), OUT)


if __name__ == '__main__':
    main()
