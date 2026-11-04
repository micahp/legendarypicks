"""Fit and check the lineup layer's inputs from the participation release (SLC v2, research).

lineup_participation.py takes three inputs: entry weights, leave hazards and the called package. This script fits the first two
from seasons the caller names and replays a check season against what was observed.

Definitions, all from published files:
- A snap is a regular-season run, pass, kneel, spike or non-special-teams penalty play with exactly eleven offensive player
  ids in the participation release. Plays with any other
  count are counted and skipped.
- A player's group is his weekly-roster position for that team and week (FB from depth_chart_position). Linemen are OL.
- Eligible players are the team-week's weekly roster with status ACT and an offensive group.
- A player's prior share is his mean published offense_pct in this season's games before this week; with none, his previous
  season mean; with neither, zero. It never reads the game being predicted.
- A voluntary leave is a player on the field at snap t, gone at snap t+1, in a slot whose count did not change.

The check season replays each team-game's observed package sequence (slot counts by roster group). That conditions on the calls
on purpose: it tests the substitution mechanics alone. The calls come from the play-call model at integration.
"""
import argparse
import csv
import gzip
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lineup_participation as lp  # noqa: E402

RAW = Path('/root/gridiron-playbooks-research/data/raw')
BACKFILL = Path('/root/lp-snapshots/nfl-backfill-2026-10-27/raw')
GROUP_OF = {'QB': 'QB', 'RB': 'RB', 'FB': 'FB', 'TE': 'TE', 'WR': 'WR', 'OL': 'OL', 'T': 'OL', 'G': 'OL', 'C': 'OL'}
SHARE_BUCKETS = (0.3, 0.6, 0.85)  # upper edges; a share at or above 0.85 is the top bucket
STINT_BUCKETS = (1, 2, 3, 5, 8)   # upper edges; above 8 is the last bucket
OFFENSE_PLAY_TYPES = {'run', 'pass', 'qb_kneel', 'qb_spike'}  # plus a penalty no_play that is not a special-teams play


def bucket(value, edges):
    return next((i for i, edge in enumerate(edges) if value <= edge), len(edges))


def share_bucket(share):
    return next((i for i, edge in enumerate(SHARE_BUCKETS) if share < edge), len(SHARE_BUCKETS))


def rosters(season):
    """{(team, week): {gsis_id: group}} for ACT offensive players, and {gsis_id: pfr_id}."""
    frame = pd.read_parquet(BACKFILL / 'weekly_rosters' / f'roster_weekly_{season}.parquet',
                            columns=['team', 'week', 'game_type', 'status', 'position', 'depth_chart_position',
                                     'gsis_id', 'pfr_id'])
    frame = frame[(frame.game_type == 'REG') & frame.gsis_id.notna()]
    eligible, any_status, pfr = defaultdict(dict), defaultdict(dict), {}
    for row in frame.itertuples(index=False):
        group = 'FB' if row.depth_chart_position == 'FB' else GROUP_OF.get(row.position)
        if row.pfr_id:
            pfr[row.gsis_id] = row.pfr_id
        if group is None:
            continue
        any_status[(row.team, int(row.week))][row.gsis_id] = group
        if row.status == 'ACT':
            eligible[(row.team, int(row.week))][row.gsis_id] = group
    return eligible, any_status, pfr


def snap_counts(season):
    frame = pd.read_parquet(BACKFILL / 'snap_counts' / f'snap_counts_{season}.parquet',
                            columns=['game_id', 'game_type', 'week', 'pfr_player_id', 'team', 'offense_snaps', 'offense_pct'])
    return frame[frame.game_type == 'REG']


def prior_shares(season):
    """{(pfr_id, week): prior share} built from published offense_pct, this season before the week, else last season."""
    this, last = snap_counts(season), snap_counts(season - 1)
    last_mean = last[last.offense_snaps > 0].groupby('pfr_player_id').offense_pct.mean().to_dict()
    played = this[this.offense_snaps > 0].sort_values('week')
    out = {}
    weeks = sorted(this.week.unique())
    history = defaultdict(list)
    by_week = defaultdict(list)
    for row in played.itertuples(index=False):
        by_week[int(row.week)].append((row.pfr_player_id, row.offense_pct))
    for week in weeks:
        for pid, values in history.items():
            out[(pid, int(week))] = sum(values) / len(values)
        for pid, pct in by_week[int(week)]:
            history[pid].append(pct)
    return out, last_mean


def snaps(season, counts):
    """Team-game snap sequences: {(game_id, team, week): [[gsis ids on the field] or None, ...]} in play order. None is a
    play whose participation row does not list eleven offensive players."""
    order = {}
    with gzip.open(RAW / f'pbp_{season}.csv.gz', 'rt', encoding='utf-8', newline='') as handle:
        for row in csv.DictReader(handle):
            offense_play = row['play_type'] in OFFENSE_PLAY_TYPES or (
                row['play_type'] == 'no_play' and row['special_teams_play'] == '0')
            if row['season_type'] == 'REG' and row['posteam'] and row['play_id'] and offense_play:
                order[(row['game_id'], int(float(row['play_id'])))] = (row['posteam'], int(row['week']))
    games = defaultdict(list)
    with (RAW / f'pbp_participation_{season}.csv').open(encoding='utf-8', newline='') as handle:
        for row in csv.DictReader(handle):
            key = (row['nflverse_game_id'], int(float(row['play_id'])))
            if key not in order:
                counts['participation_rows_not_regular_season_offense_plays'] += 1
                continue
            ids = [x for x in row['offense_players'].split(';') if x]
            team, week = order[key]
            if len(ids) != 11:
                counts[f'snaps_skipped_{len(ids)}_offense_ids'] += 1
                ids = None  # kept as a break, so the snaps either side are not read as consecutive
            games[(key[0], team, week)].append((key[1], ids))
            counts['snaps_kept'] += 1
    return {k: [ids for _pid, ids in sorted(v)] for k, v in games.items()}


class Season:
    def __init__(self, season):
        self.season = season
        self.counts = Counter()
        self.eligible, self.any_status, self.pfr = rosters(season)
        self.prior, self.last_mean = prior_shares(season)
        self.games = snaps(season, self.counts)
        self.published = {(r.game_id, r.team, r.pfr_player_id): r.offense_pct
                          for r in snap_counts(season).itertuples(index=False)}

    def group(self, team, week, gsis):
        return self.any_status.get((team, week), {}).get(gsis)

    def share(self, gsis, week):
        pfr = self.pfr.get(gsis)
        if pfr is None:
            return 0.0
        return self.prior.get((pfr, week), self.last_mean.get(pfr, 0.0))

    def slots(self, team, week, ids):
        """Slot counts of one snap by roster group, or None when a player has no offensive roster group."""
        groups = [self.group(team, week, g) for g in ids]
        if None in groups:
            return None
        need = Counter(lp.SLOT_OF[g] for g in groups)
        return {slot: need.get(slot, 0) for slot in lp.SLOTS}


def fit(seasons):
    """Leave hazards by (slot, prior-share bucket, stint bucket) and the entry-weight exponent and floor."""
    leaves, at_risk = Counter(), Counter()
    entries = []  # (slot, chosen prior share, [candidate prior shares])
    counts = Counter()
    observed = Counter()
    for season in seasons:
        data = Season(season)
        counts.update({f'{season}:{k}': v for k, v in data.counts.items()})
        for (game_id, team, week), plays in data.games.items():
            stint = {}
            prev, prev_slots = None, None
            eligible = data.eligible.get((team, week), {})
            for ids in plays:
                slots = None if ids is None else data.slots(team, week, ids)
                if ids is not None and slots is None:
                    counts['snaps_with_a_player_outside_offensive_roster_groups'] += 1
                if slots is None:
                    prev, prev_slots, stint = None, None, {}
                    continue
                if prev is not None:
                    gone, came = set(prev) - set(ids), set(ids) - set(prev)
                    skill = lambda xs: {g for g in xs if data.group(team, week, g) != 'OL'}  # noqa: E731
                    observed['transitions'] += 1
                    observed['same_skill_lineup'] += skill(prev) == skill(ids)
                    observed['entries'] += len(came)
                    for g in prev:
                        slot = lp.SLOT_OF[data.group(team, week, g)]
                        if prev_slots[slot] != slots[slot]:
                            continue
                        key = (slot, share_bucket(data.share(g, week)), bucket(stint[g], STINT_BUCKETS))
                        at_risk[key] += 1
                        leaves[key] += g in gone
                    for g in came:
                        slot = lp.SLOT_OF[data.group(team, week, g)]
                        bench = [b for b, grp in eligible.items() if lp.SLOT_OF[grp] == slot and b not in prev]
                        if g not in bench:
                            counts['entries_by_a_player_not_on_the_act_roster'] += 1
                            continue
                        entries.append((data.share(g, week), [data.share(b, week) for b in bench]))
                stint = {g: stint.get(g, 0) + 1 if prev is not None and g in prev else 1 for g in ids}
                prev, prev_slots = ids, slots
            observed['team_games'] += 1
    best = None
    for alpha in (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0):
        for floor in (0.005, 0.02, 0.05, 0.1, 0.2, 0.4, 0.8, 1.6, 3.2):
            ll = 0.0
            for chosen, bench in entries:
                weights = [(s + floor) ** alpha for s in bench]
                ll += math.log((chosen + floor) ** alpha / sum(weights))
            if best is None or ll > best[0]:
                best = (ll, alpha, floor)
    uniform = sum(-math.log(len(bench)) for _c, bench in entries)
    hazards = {f'{s}|{b}|{t}': {'leaves': leaves[(s, b, t)], 'at_risk': n,
                                 'hazard': (leaves[(s, b, t)] + 0.5) / (n + 1.0)}
               for (s, b, t), n in sorted(at_risk.items())}
    return {
        'seasons': seasons, 'counts': dict(counts),
        'observed': {**observed, 'same_skill_lineup_rate': observed['same_skill_lineup'] / observed['transitions'],
                     'entries_per_team_game': observed['entries'] / observed['team_games']},
        'entry_weight': {'alpha': best[1], 'floor': best[2], 'log_likelihood': best[0],
                         'uniform_log_likelihood': uniform, 'entries': len(entries)},
        'share_buckets': SHARE_BUCKETS, 'stint_buckets': STINT_BUCKETS, 'leave_hazard': hazards,
    }


def offense_for(data, team, week, model, seed, mode):
    eligible = data.eligible.get((team, week), {})
    alpha, floor = model['entry_weight']['alpha'], model['entry_weight']['floor']
    weight = {g: (data.share(g, week) + floor) ** alpha for g in eligible}
    hazards = model['leave_hazard']

    def hazard(g, group, stint):
        if mode == 'independent':
            return 1.0
        if mode == 'static':
            return 0.0
        key = f'{lp.SLOT_OF[group]}|{share_bucket(data.share(g, week))}|{bucket(stint, STINT_BUCKETS)}'
        return hazards[key]['hazard'] if key in hazards else 0.0
    return lp.Offense(eligible, random.Random(seed), entry_weight=weight, leave_hazard=hazard, floor_weight=floor ** alpha)


def check(season, model, seeds, modes=('fitted', 'independent', 'static')):
    """Replay every team-game's observed packages. Per mode: same-skill-lineup rate, entries per team-game, and the per
    player-game absolute error of simulated snap share against published offense_pct, kept per game for a clustered interval."""
    data = Season(season)
    result = {m: {'transitions': 0, 'same_skill': 0, 'entries': 0, 'games': 0, 'abs_error_by_game': {}} for m in modes}
    observed = Counter()
    counts = Counter(data.counts)
    for (game_id, team, week), plays in sorted(data.games.items()):
        counts['replay_snaps_without_eleven_ids_dropped'] += sum(ids is None for ids in plays)
        plays = [ids for ids in plays if ids is not None]
        if not any((game_id, team, data.pfr.get(g)) in data.published for g in data.eligible.get((team, week), {})):
            counts['team_games_skipped_no_published_snap_rows_joined'] += 1
            continue
        sequence = [data.slots(team, week, ids) for ids in plays]
        if any(s is None for s in sequence):
            counts['team_games_skipped_player_outside_offensive_roster_groups'] += 1
            continue
        eligible = data.eligible.get((team, week), {})
        published = {g: data.published.get((game_id, team, data.pfr.get(g)), 0.0) for g in eligible}
        prev = None
        for ids in plays:
            if prev is not None:
                skill = lambda xs: {g for g in xs if data.group(team, week, g) != 'OL'}  # noqa: E731
                observed['transitions'] += 1
                observed['same_skill'] += skill(prev) == skill(ids)
                observed['entries'] += len(set(ids) - set(prev))
            prev = ids
        observed['games'] += 1
        for mode in modes:
            errors, ok = [], True
            for seed in range(seeds):
                off = offense_for(data, team, week, model, seed, mode)
                last = None
                try:
                    for need in sequence:
                        entered, _left = off.advance_counts(need)
                        if last is not None:
                            skill = {g for g in off.on_field if off.roster[g] != 'OL'}
                            result[mode]['transitions'] += 1
                            result[mode]['same_skill'] += skill == last
                            result[mode]['entries'] += len(entered)
                        last = {g for g in off.on_field if off.roster[g] != 'OL'}
                except lp.ShortRoster:
                    ok = False
                    break
                errors.append(sum(abs(off.ledger.snap_share(g) - published[g]) for g in eligible) / len(eligible))
            if not ok:
                counts[f'{mode}:team_games_short_roster'] += 1
                continue
            result[mode]['games'] += seeds
            result[mode]['abs_error_by_game'][f'{game_id}|{team}'] = sum(errors) / len(errors)
    summary = {'season': season, 'seeds_per_team_game': seeds, 'counts': dict(counts),
               'observed': {'same_skill_lineup_rate': observed['same_skill'] / observed['transitions'],
                            'entries_per_team_game': observed['entries'] / observed['games'],
                            'team_games': observed['games']}}
    for mode, r in result.items():
        errs = r['abs_error_by_game']
        summary[mode] = {'same_skill_lineup_rate': r['same_skill'] / r['transitions'],
                         'entries_per_team_game': r['entries'] / r['games'],
                         'snap_share_mae': sum(errs.values()) / len(errs), 'team_games': len(errs)}
    rng = random.Random(20261104)
    for base in modes[1:]:
        common = sorted(set(result['fitted']['abs_error_by_game']) & set(result[base]['abs_error_by_game']))
        diff = [result['fitted']['abs_error_by_game'][k] - result[base]['abs_error_by_game'][k] for k in common]
        boots = sorted(sum(rng.choice(diff) for _ in diff) / len(diff) for _ in range(2000))
        summary[f'fitted_minus_{base}'] = {'mean': sum(diff) / len(diff), 'ci95': [boots[49], boots[1949]],
                                          'team_games': len(common)}
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--fit', default='2022,2023,2024', help='comma-separated fit seasons')
    parser.add_argument('--check', type=int, help='season to replay against the fitted model')
    parser.add_argument('--seeds', type=int, default=5)
    parser.add_argument('--model', help='write the fitted model here, or read it when --check is given alone')
    parser.add_argument('--out', help='write the check summary here')
    args = parser.parse_args()
    if args.check is None:
        model = fit([int(s) for s in args.fit.split(',')])
        Path(args.model).write_text(json.dumps(model, indent=1, sort_keys=True))
        print(json.dumps({k: model[k] for k in ('counts', 'observed', 'entry_weight')}, indent=1))
        return
    model = json.loads(Path(args.model).read_text())
    summary = check(args.check, model, args.seeds)
    Path(args.out).write_text(json.dumps(summary, indent=1, sort_keys=True))
    print(json.dumps(summary, indent=1))


if __name__ == '__main__':
    main()
