#!/usr/bin/env python3
"""Participation model, option A: priors from prior seasons, current-season usage updated week by week.

Three parts, each shrunk toward a prior and each reported on its own:
1. Personnel mix. P(group | team, situation cell), shrunk from the team's recency-weighted counts toward the league mix in
   the same cell.
2. Player on-field rate. P(player on field | team, group), shrunk from the player's recency-weighted appearances toward the
   mean rate of players at the same position in the same group.
3. Usage shares. Each player's share of the team's carries and targets, shrunk from the prior toward the observed share
   in the current season through the week before the target week. This is the only current-season input for 2026, because
   no 2026 participation file is published.

Modes:
  evaluate  fit on 2022 to 2024, score 2025 with the prior seasons only (personnel and on-field) and a week-by-week usage
            update inside 2025 (usage uses 2025 play-by-play through the week before each target week).
  forecast  fit on 2022 to 2025 and report 2026 usage shares through the last week in the pinned play-by-play.

Usage: python3 participation_model.py evaluate|forecast --tables <dir> --raw-dir <dir> --report <json> [--as-of-week W]
"""
import argparse
import csv
import gzip
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

RECENCY = {2022: 0.125, 2023: 0.25, 2024: 0.5, 2025: 1.0}  # weight of each prior season, most recent heaviest
GROUP_PRIOR_PLAYS = 50.0  # pseudo-plays of the league mix in a situation cell
PLAYER_PRIOR_PLAYS = 20.0  # pseudo-plays of the position mean for a player's group rate
USAGE_PRIOR_USES = 40.0  # pseudo-uses of the prior share for a player's carry or target share
EPS = 1e-9


def cell_of(row):
    """Down, distance and field bucket. Missing values fall into an explicit 'na' cell, never a default."""
    down = row['down'] if row['down'] in ('1', '2', '3', '4') else 'na'
    togo = int(float(row['ydstogo'])) if row['ydstogo'] not in ('', None) else None
    distance = 'na' if togo is None else ('short' if togo <= 3 else 'mid' if togo <= 6 else 'long' if togo <= 9 else 'xl')
    yl = float(row['yardline_100']) if row['yardline_100'] not in ('', None) else None
    field = 'na' if yl is None else ('red' if yl <= 20 else 'mid' if yl <= 50 else 'own' if yl <= 80 else 'deep')
    return f'{down}|{distance}|{field}'


def load_scrimmage(path, seasons):
    rows = []
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as handle:
        for row in csv.DictReader(handle):
            if int(row['season']) not in seasons or row['flag_defensive_label'] != '0':
                continue  # defensive labels were excluded in build_tables.py; kept out here as a second guard
            if row.get('flag_nonstandard_offense', '0') != '0':
                continue  # no QB, or a kicker, punter or snapper on the field: a fake kick or direct snap, not a package
            row['ids'] = [x for x in row['offense_ids'].split(';') if x]
            rows.append(row)
    return rows


def load_positions(raw_dir):
    positions = {}
    with open(raw_dir / 'players.csv', encoding='utf-8', newline='') as handle:
        for row in csv.DictReader(handle):
            if row.get('gsis_id') and row.get('position'):
                positions[row['gsis_id']] = row['position']
    return positions


def load_usage(path, seasons=None):
    rows = []
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as handle:
        for row in csv.DictReader(handle):
            if seasons is None or int(row['season']) in seasons:
                rows.append(row)
    return rows


def fit_personnel(rows, seasons):
    """League mix per cell and team mix per (team, cell), both recency weighted."""
    league = defaultdict(Counter)
    team = defaultdict(Counter)
    for row in rows:
        if int(row['season']) not in seasons:
            continue
        w = RECENCY[int(row['season'])]
        cell = cell_of(row)
        league[cell][row['group']] += w
        team[(row['posteam'], cell)][row['group']] += w
    return {'league': league, 'team': team}


def personnel_prob(model, team, cell, group):
    league = model['league'][cell]
    total_league = sum(league.values())
    prior = (league[group] + 1.0) / (total_league + 1.0 * max(1, len(league)))  # add-one over observed groups
    counts = model['team'].get((team, cell), Counter())
    n = sum(counts.values())
    return (counts[group] + GROUP_PRIOR_PLAYS * prior) / (n + GROUP_PRIOR_PLAYS)


def weekly_best(model, team, cell, cur):
    """Most likely group under the weekly-updated team mix. Groups are the league's groups plus any seen this season."""
    groups = set(model['league'][cell]) | set(cur)
    n_cur = sum(cur.values())
    return max(groups, key=lambda g: (cur[g] + GROUP_PRIOR_PLAYS * personnel_prob(model, team, cell, g))
               / (n_cur + GROUP_PRIOR_PLAYS))


def fit_player_rates(rows, seasons, positions, weights=None):
    """Recency-weighted on-field appearances and team plays by (player, team, group). weights: {season: weight}; RECENCY
    when None."""
    weights = RECENCY if weights is None else weights
    appearances = defaultdict(float)
    team_plays = defaultdict(float)
    for row in rows:
        if int(row['season']) not in seasons:
            continue
        w = weights[int(row['season'])]
        team_plays[(row['posteam'], row['group'])] += w
        for pid in row['ids']:
            appearances[(pid, row['posteam'], row['group'])] += w
    # Position prior: appearance-weighted mean rate across players at the same position, within the same group.
    pos_num, pos_den = defaultdict(float), defaultdict(float)
    for (pid, team, group), a in appearances.items():
        pos = positions.get(pid, 'UNK')
        plays = team_plays[(team, group)]
        pos_num[(pos, group)] += a
        pos_den[(pos, group)] += plays
    prior = {key: pos_num[key] / pos_den[key] for key in pos_num if pos_den[key] > 0}
    return {'appearances': appearances, 'team_plays': team_plays, 'position_prior': prior}


def player_rate(model, positions, pid, team, group):
    pos = positions.get(pid, 'UNK')
    prior = model['position_prior'].get((pos, group), 0.0)
    a = model['appearances'].get((pid, team, group), 0.0)
    plays = model['team_plays'].get((team, group), 0.0)
    return (a + PLAYER_PRIOR_PLAYS * prior) / (plays + PLAYER_PRIOR_PLAYS)


def usage_prior(usage_rows, seasons):
    """Recency-weighted share of team carries and targets, by player, from the prior seasons."""
    uses = {'carry': defaultdict(float), 'target': defaultdict(float)}
    totals = {'carry': defaultdict(float), 'target': defaultdict(float)}
    for row in usage_rows:
        season = int(row['season'])
        if season not in seasons:
            continue
        role = row['role']
        if role not in uses:
            continue
        w = RECENCY[season]
        uses[role][(row['posteam'], row['player_id'])] += w
        totals[role][row['posteam']] += w
    return {'uses': uses, 'totals': totals}


def usage_share(prior, role, team, pid, window_uses=None, window_totals=None):
    """Share of the team's carries or targets. Current-season uses in window_* update the prior."""
    base_uses = prior['uses'][role].get((team, pid), 0.0)
    base_total = prior['totals'][role].get(team, 0.0)
    prior_share = base_uses / base_total if base_total > 0 else 0.0
    cur = window_uses.get((team, pid), 0.0) if window_uses else 0.0
    cur_total = window_totals.get(team, 0.0) if window_totals else 0.0
    share = (cur + USAGE_PRIOR_USES * prior_share) / (cur_total + USAGE_PRIOR_USES)
    if cur == 0.0 and base_uses == 0.0:
        # A player with no prior and no current use gets a Laplace-style floor, so an unseen player is a finite cost.
        return 1.0 / (base_total + cur_total + USAGE_PRIOR_USES + 1.0)
    return share


def evaluate(args, raw, tables):
    train = {2022, 2023, 2024}
    test = {2025}
    scrim = load_scrimmage(tables / 'scrimmage_participation.csv.gz', train | test)
    positions = load_positions(raw)
    usage = load_usage(tables / 'usage_plays.csv.gz')
    personnel = fit_personnel(scrim, train)
    rates = fit_player_rates(scrim, train, positions)
    uprior = usage_prior(usage, train)

    # 1. Personnel: log loss of the observed group on each 2025 play, team mix versus league mix in the same cell.
    # The 2025 weeks are scored in order. The weekly variant adds the earlier 2025 weeks to the team counts. It is the
    # counterfactual value of a current-season participation feed, which 2026 does not have.
    ll_team = ll_league = ll_weekly = 0.0
    hits_team = hits_league = hits_weekly = n_play = 0
    season_rows = sorted((r for r in scrim if int(r['season']) in test), key=lambda r: int(r['week']))
    current = defaultdict(Counter)
    for week in sorted({int(r['week']) for r in season_rows}):
        week_rows = [r for r in season_rows if int(r['week']) == week]
        for row in week_rows:
            cell, team, group = cell_of(row), row['posteam'], row['group']
            p_team = personnel_prob(personnel, team, cell, group)
            league = personnel['league'][cell]
            p_league = (league[group] + 1.0) / (sum(league.values()) + 1.0 * max(1, len(league)))
            cur = current[(team, cell)]
            n_cur = sum(cur.values())
            prior_mix = personnel_prob(personnel, team, cell, group)
            p_weekly = (cur[group] + GROUP_PRIOR_PLAYS * prior_mix) / (n_cur + GROUP_PRIOR_PLAYS)
            ll_team += -math.log(max(p_team, EPS))
            ll_league += -math.log(max(p_league, EPS))
            ll_weekly += -math.log(max(p_weekly, EPS))
            n_play += 1
            best_team = max(personnel['team'].get((team, cell), Counter({group: 0})).items(), key=lambda kv: kv[1])[0]
            best_league = max(league.items(), key=lambda kv: kv[1])[0] if league else None
            best_weekly = weekly_best(personnel, team, cell, cur)
            hits_team += int(best_team == group)
            hits_league += int(best_league == group)
            hits_weekly += int(best_weekly == group)
        for row in week_rows:  # the week is scored before it is added
            current[(row['posteam'], cell_of(row))][row['group']] += 1.0
    personnel_metrics = {
        'plays': n_play,
        'log_loss_team_mix_prior_only': round(ll_team / n_play, 5),
        'log_loss_league_mix': round(ll_league / n_play, 5),
        'log_loss_team_mix_with_2025_weeks_counterfactual': round(ll_weekly / n_play, 5),
        'top_group_accuracy_team_mix_prior_only': round(hits_team / n_play, 4),
        'top_group_accuracy_league_mix': round(hits_league / n_play, 4),
        'top_group_accuracy_with_2025_weeks_counterfactual': round(hits_weekly / n_play, 4),
        'note': ('the counterfactual uses 2025 participation through the prior week, which the 2026 season does not have; '
                 'it bounds what a current-season personnel feed could add'),
    }

    # 2. On-field: every player seen for the team and group in 2022 to 2024 is a candidate on each 2025 play. The outcome is
    # whether he was on the field. Scored with Brier and log loss, against the position mean as the baseline.
    candidates = defaultdict(set)
    for (pid, team, group), a in rates['appearances'].items():
        if a > 0:
            candidates[(team, group)].add(pid)
    brier_model = brier_base = ll_model = ll_base = 0.0
    n_pairs = positives = 0
    for row in scrim:
        if int(row['season']) not in test:
            continue
        team, group = row['posteam'], row['group']
        on_field = set(row['ids'])
        for pid in candidates.get((team, group), ()):
            y = 1.0 if pid in on_field else 0.0
            p = min(max(player_rate(rates, positions, pid, team, group), EPS), 1 - EPS)
            p0 = min(max(rates['position_prior'].get((positions.get(pid, 'UNK'), group), 0.0), EPS), 1 - EPS)
            brier_model += (p - y) ** 2
            brier_base += (p0 - y) ** 2
            ll_model += -(y * math.log(p) + (1 - y) * math.log(1 - p))
            ll_base += -(y * math.log(p0) + (1 - y) * math.log(1 - p0))
            n_pairs += 1
            positives += int(y)
    player_metrics = {
        'candidate_player_plays': n_pairs, 'on_field_share': round(positives / n_pairs, 4),
        'brier_player_rate': round(brier_model / n_pairs, 5), 'brier_position_mean': round(brier_base / n_pairs, 5),
        'log_loss_player_rate': round(ll_model / n_pairs, 5), 'log_loss_position_mean': round(ll_base / n_pairs, 5),
        'candidates': 'players with at least one 2022 to 2024 appearance for the same team and group',
    }

    # 3. Usage: multinomial log loss of each observed carry and target in 2025, prior only versus week-by-week update.
    by_week = defaultdict(list)
    for row in usage:
        if int(row['season']) == 2025 and row['role'] in ('carry', 'target'):
            by_week[int(row['week'])].append(row)
    results = {}
    for role in ('carry', 'target'):
        ll_prior = ll_update = 0.0
        n_use = 0
        cur_uses = defaultdict(float)
        cur_totals = defaultdict(float)
        for week in sorted(by_week):
            week_rows = [r for r in by_week[week] if r['role'] == role]
            for r in week_rows:
                team, pid = r['posteam'], r['player_id']
                p0 = usage_share(uprior, role, team, pid)
                p1 = usage_share(uprior, role, team, pid, cur_uses, cur_totals)
                ll_prior += -math.log(max(p0, EPS))
                ll_update += -math.log(max(p1, EPS))
                n_use += 1
            for r in week_rows:  # the week's uses enter the update only after the week is scored
                cur_uses[(r['posteam'], r['player_id'])] += 1.0
                cur_totals[r['posteam']] += 1.0
        results[role] = {'uses': n_use, 'log_loss_prior_only': round(ll_prior / n_use, 5),
                         'log_loss_weekly_update': round(ll_update / n_use, 5)}
    return {'mode': 'evaluate', 'train_seasons': sorted(train), 'test_season': 2025,
            'personnel': personnel_metrics, 'on_field': player_metrics, 'usage': results}


def forecast(args, raw, tables):
    seasons = {2022, 2023, 2024, 2025}
    scrim = load_scrimmage(tables / 'scrimmage_participation.csv.gz', seasons)
    positions = load_positions(raw)
    usage = load_usage(tables / 'usage_plays.csv.gz')
    uprior = usage_prior(usage, seasons)
    cur = [r for r in usage if int(r['season']) == 2026 and int(r['week']) < args.as_of_week]
    cur_uses = defaultdict(float)
    cur_totals = defaultdict(float)
    for r in cur:
        if r['role'] in ('carry', 'target'):
            cur_uses[(r['role'], r['posteam'], r['player_id'])] += 1.0
            cur_totals[(r['role'], r['posteam'])] += 1.0
    weeks = sorted({int(r['week']) for r in usage if int(r['season']) == 2026})
    shares = {}
    for role in ('carry', 'target'):
        u = {(t, p): v for (rr, t, p), v in cur_uses.items() if rr == role}
        tt = {t: v for (rr, t), v in cur_totals.items() if rr == role}
        keys = set(uprior['uses'][role]) | set(u)  # rookies with 2026 uses but no prior uses are included
        shares[role] = {}
        for (t, p) in sorted(keys):
            shares[role].setdefault(t, {})[p] = round(usage_share(uprior, role, t, p, u, tt), 5)
    return {'mode': 'forecast', 'prior_seasons': sorted(seasons), 'as_of_week': args.as_of_week,
            'usage_weeks_observed_2026': weeks[:1] and [weeks[0], weeks[-1]] or [],
            'personnel_team_prior_seasons': 'recency-weighted 2022 to 2025 (2026 participation not published)',
            'carry_share_by_team_player': shares['carry'], 'target_share_by_team_player': shares['target']}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=('evaluate', 'forecast'))
    ap.add_argument('--tables', type=Path, required=True)
    ap.add_argument('--raw-dir', type=Path, required=True)
    ap.add_argument('--report', type=Path, required=True)
    ap.add_argument('--as-of-week', type=int, default=99)
    args = ap.parse_args()
    fn = evaluate if args.mode == 'evaluate' else forecast
    out = fn(args, args.raw_dir, args.tables)
    out['inputs'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in (args.tables / 'scrimmage_participation.csv.gz', args.tables / 'usage_plays.csv.gz',
                               args.raw_dir / 'players.csv')}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(out, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in out.items() if k in ('personnel', 'on_field', 'usage')}, indent=2, sort_keys=True)
          if args.mode == 'evaluate' else f'forecast written: {args.report}')


if __name__ == '__main__':
    main()
