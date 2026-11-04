#!/usr/bin/env python3
"""Which borrowing rule should a thin situation cell use? An out-of-sample comparison (research).

A cell with fewer than participation_field.MIN_CELL_PLAYS league plays in the fitted table borrows another cell's grouping
transitions. Three rules, each keeping the team, the previous grouping and the call:

  A  same down and field bucket, nearest distance with enough plays (participation_field.supported_cell, the current rule)
  B  same distance and field bucket, nearest down with enough plays
  C  every cell of the same down pooled

Score: mean log probability of the observed grouping on the check season's snaps whose own cell is thin in the table,
with a game-clustered bootstrap interval for each difference from A. The table is fitted on seasons before the check season.

Usage: python3 fallback_rule_check.py --tables <scrimmage table with qb_dropback> --field <v4 field fitted before the
           check season> --season 2025 --out <json>
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
import call_grouping_check as cgc  # noqa: E402
import participation_field as pf  # noqa: E402

DOWNS = ('1', '2', '3', '4')


def plays(field, cell):
    return sum(field.marginal_by_cell.get(cell, {}).values())


def rule_b(field, cell):
    down, distance, zone = cell.split('|')
    if down not in DOWNS:
        return None
    for other in sorted(DOWNS, key=lambda d: (abs(int(d) - int(down)), int(d))):
        candidate = f'{other}|{distance}|{zone}'
        if plays(field, candidate) >= pf.MIN_CELL_PLAYS:
            return candidate
    return None


def pooled_probs(field, team, down, prev, call):
    """Rule C: the league and team transitions summed over every cell of the down, shrunk as group_probs does."""
    marginal, league, team_counts = Counter(), Counter(), Counter()
    for (cell, c), counts in field.marginal_by_cell_call.items():
        if cell.startswith(f'{down}|') and c == call:
            marginal.update(counts)
    for (cell, c, p), counts in field.league_by_call.items():
        if cell.startswith(f'{down}|') and c == call and p == prev:
            league.update(counts)
    for (t, cell, c, p), counts in field.team_by_call.items():
        if t == team and cell.startswith(f'{down}|') and c == call and p == prev:
            team_counts.update(counts)
    return field._shrunk(marginal, league, team_counts) if marginal else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tables', type=Path, required=True)
    ap.add_argument('--field', type=Path, required=True)
    ap.add_argument('--season', type=int, default=2025)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    field = pf.Field(json.loads(args.field.read_text()), pf.sha256_file(args.field))
    if not field.conditions_on_call or max(field.seasons) >= args.season:
        raise ValueError(f'{args.field} must be a v4 table fitted on seasons before {args.season}; it has {field.seasons}')
    games = cgc.snaps(args.tables, args.season)
    by_game = defaultdict(lambda: defaultdict(list))  # game -> rule -> log probs
    counts = Counter()
    for (game, team), seq in sorted(games.items()):
        prev = pf.START
        for group, cell, call in seq:
            counts['snaps'] += 1
            if plays(field, cell) >= pf.MIN_CELL_PLAYS:
                prev = group
                continue
            counts['thin_cell_snaps'] += 1
            counts[f'thin:{cell}'] += 1
            options = {'A': field.group_probs(team, field.supported_cell(cell), prev, call)
                       if field.supported_cell(cell) else {},
                       'B': field.group_probs(team, rule_b(field, cell), prev, call) if rule_b(field, cell) else {},
                       'C': pooled_probs(field, team, cell.split('|')[0], prev, call)}
            if any(not probs or probs.get(group, 0.0) <= 0 for probs in options.values()):
                counts['unscorable_under_some_rule'] += 1
                prev = group
                continue
            for rule, probs in options.items():
                by_game[(game, team)][rule].append(math.log(probs[group]))
            prev = group
    keys = sorted(by_game)
    n = sum(len(by_game[k]['A']) for k in keys)
    report = {'season': args.season, 'table': args.field.name, 'table_sha256': field.sha256, 'fit_seasons': field.seasons,
              'min_cell_plays': pf.MIN_CELL_PLAYS, 'counts': dict(counts), 'scored_snaps': n, 'team_games': len(keys)}
    mean = {rule: sum(sum(by_game[k][rule]) for k in keys) / n for rule in 'ABC'}
    report['mean_log_prob'] = {rule: round(v, 5) for rule, v in mean.items()}
    rng = random.Random(20261104)
    for rule in 'BC':
        diffs = []
        for _ in range(2000):
            pick = [rng.choice(keys) for _ in keys]
            num = sum(sum(by_game[k][rule]) - sum(by_game[k]['A']) for k in pick)
            den = sum(len(by_game[k]['A']) for k in pick)
            diffs.append(num / den)
        diffs.sort()
        report[f'{rule}_minus_A'] = {'mean': round(mean[rule] - mean['A'], 5),
                                     'ci95': [round(diffs[49], 5), round(diffs[1949], 5)]}
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True))
    print(json.dumps({k: report[k] for k in ('scored_snaps', 'team_games', 'mean_log_prob', 'B_minus_A', 'C_minus_A')}))
    print('thin snaps', counts['thin_cell_snaps'], 'of', counts['snaps'], 'unscorable', counts['unscorable_under_some_rule'])


if __name__ == '__main__':
    main()
