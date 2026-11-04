#!/usr/bin/env python3
"""Cutoff-safe offensive snap share by player and role (SLC v2 step 1, research).

Snap share = a player's offensive snaps in a game / his team's offensive snaps in that game. Snaps come from the
nflverse participation labels (offense_ids, one per on-field player), regular season only, flagged defensive snaps
excluded.

Prediction. For a player-game in season s, the estimate uses only that player's earlier team games in s (weeks before
the game), counting a team game in which he was absent as a zero. It shrinks toward a prior with K = 4 pseudo-games. The
prior is his prior-season mean share over all of that team's prior-season games. If he has none, the prior is the
prior-season mean for his position group, or the overall prior-season mean when that group is unknown. A player's
position group comes from the prior season's labels only, never from the target game or season. The 2022 offensive
position labels are blank in the participation file, so 2023 has no group prior and falls back to the overall mean.

Baselines. The prior-season group mean (no player information, with the same fallback), and the prior-season share alone.

Scoring. Only player-games with at least one snap are scored. An absent player is never a target. This is the same
conditioning the P2 usage component uses.

Role table: POSTGAME DESCRIPTIVE ONLY. It ranks players by their full-season mean share and uses the season's own
labels and observations. It is never a predictive feature, prior or gate input.

Usage: python3 snap_share.py --tables <scrimmage_participation.csv.gz> --out <json>
"""
import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import participation_model as pm  # noqa: E402

K = 4  # pseudo-games, as in the P2 usage component
K2 = 8  # pseudo-games pulling a player's prior toward his position group
DEV_SEASONS = (2023, 2024)
HOLDOUT_SEASON = 2025
SEASONS = (2022, 2023, 2024, 2025)
BLANK_LABEL_NOTE = '2022 offense_positions is blank in this file, so 2023 uses the overall prior-season mean'


def group_of(label):
    if label in ('RB', 'FB'):
        return 'RB'
    if label in ('WR', 'TE', 'QB'):
        return label
    if label in ('C', 'G', 'T'):
        return 'OL'
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tables', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--targets-out', type=Path, default=None, help='optional CSV of every scored player-game')
    ap.add_argument('--positions', type=Path, default=None,
                    help='optional reconstructed per-game positions (reconstruct_positions.py); replaces the on-field '
                         'labels for position groups, including 2022')
    args = ap.parse_args()

    rows = [r for r in pm.load_scrimmage(args.tables, set(SEASONS)) if r['season_type'] == 'REG']
    plays = Counter()  # (season, game, team) -> offensive plays
    snaps = Counter()  # (season, game, team, pid) -> snaps
    labels = defaultdict(Counter)  # (season, game, team, pid) -> label counts
    week_of = {}
    for row in rows:
        key = (int(row['season']), row['game_id'], row['posteam'])
        plays[key] += 1
        week_of[key] = int(row['week'])
        # Snaps come from the ID list alone. 2022 has no offense_positions, so zipping the two lists would drop every
        # 2022 snap; labels are taken separately, and only where the position list exists.
        pids = [pid for pid in row['offense_ids'].split(';') if pid]
        for pid in pids:
            snaps[(*key, pid)] += 1
        for pid, label in zip(pids, [x for x in row['offense_positions'].split(';') if x]):
            if label:
                labels[(*key, pid)][label] += 1

    if args.positions:
        labels = defaultdict(Counter)
        with open(args.positions, newline='', encoding='utf-8') as handle:
            for row in csv.DictReader(handle):
                labels[(int(row['season']), row['game_id'], row['team'], row['gsis_id'])][row['position']] += 1

    team_games = defaultdict(list)  # (season, team) -> [(week, game)]
    for key in plays:
        team_games[(key[0], key[2])].append((week_of[key], key[1]))
    for games in team_games.values():
        games.sort()
    appearances = defaultdict(set)  # (season, team) -> pids who played
    for (season, _game, team, pid) in snaps:
        appearances[(season, team)].add(pid)

    def share(season, team, game, pid):
        return snaps.get((season, game, team, pid), 0) / plays[(season, game, team)]

    # Season-level quantities: each player's mean share over all of his team's games (absences as zeros), his position
    # group from that season's labels, and the group and overall means over player-games with at least one snap.
    team_mean = {}  # (season, team, pid) -> mean share over the team's games
    group_of_player = {}  # (season, team, pid) -> group, or None when the labels are blank
    group_sum, group_n = defaultdict(float), defaultdict(int)
    overall_sum, overall_n = defaultdict(float), defaultdict(int)
    for (season, team), games in team_games.items():
        for pid in appearances[(season, team)]:
            vals = [share(season, team, g, pid) for _w, g in games]
            team_mean[(season, team, pid)] = sum(vals) / len(vals)
            counts = Counter()
            for _w, g in games:
                counts.update(labels.get((season, g, team, pid), Counter()))
            grp = group_of(counts.most_common(1)[0][0]) if counts else None
            group_of_player[(season, team, pid)] = grp
            for _w, g in games:
                if (season, g, team, pid) in snaps:
                    value = share(season, team, g, pid)
                    overall_sum[season] += value
                    overall_n[season] += 1
                    if grp:
                        group_sum[(season, grp)] += value
                        group_n[(season, grp)] += 1
    group_mean = {key: group_sum[key] / group_n[key] for key in group_sum if group_n[key]}
    overall_mean = {season: overall_sum[season] / overall_n[season] for season in overall_sum if overall_n[season]}

    # Player-level prior-season history across every team he played for. A transfer keeps his history: the same-team
    # mean is used when it exists, otherwise the game-weighted mean over his other teams that season.
    pid_games, pid_sum, pid_group_counts = defaultdict(int), defaultdict(float), defaultdict(Counter)
    for (season, team, pid), mean in team_mean.items():
        games_n = len(team_games[(season, team)])
        pid_games[(season, pid)] += games_n
        pid_sum[(season, pid)] += mean * games_n
    for (season, game, team, pid), counter in labels.items():
        if (season, game, team, pid) not in snaps:  # a label without a snap is not history
            continue
        for label, n in counter.items():
            grp = group_of(label)
            if grp:
                pid_group_counts[(season, pid)][grp] += n
    pid_mean = {key: pid_sum[key] / pid_games[key] for key in pid_sum if pid_games[key]}

    def prior_for(season, team, pid):
        """The prior for a player-game from the season before only, with its source:
        1 the same team's prior-season mean, 2 the player's prior-season mean over any team (transfers), then shrunk
        toward his prior-season position group (group mean), or the overall prior-season mean when no group is known.
        The shrinkage weight K2 = 8 games, so a player with two prior games is pulled mostly toward his group.
        Returns (prior, group-only value, group, source)."""
        prev_season = season - 1
        grp_counts = pid_group_counts.get((prev_season, pid))
        grp = grp_counts.most_common(1)[0][0] if grp_counts else None
        group_value = group_mean.get((prev_season, grp)) if grp else None
        if group_value is None:
            group_value = overall_mean.get(prev_season, 0.0)
            group_name = 'UNK'
        else:
            group_name = grp
        if (prev_season, team, pid) in team_mean:
            n_prior = len(team_games[(prev_season, team)])
            player_value, source = team_mean[(prev_season, team, pid)], 'same_team'
        elif (prev_season, pid) in pid_mean:
            n_prior = pid_games[(prev_season, pid)]
            player_value, source = pid_mean[(prev_season, pid)], 'cross_team'
        else:
            return group_value, group_value, group_name, 'group_only' if group_name != 'UNK' else 'overall'
        prior = (n_prior * player_value + K2 * group_value) / (n_prior + K2)
        return prior, group_value, group_name, source

    def prior_group_mean(season, team, pid):
        """Kept for the group-only baseline: prior-season group mean, else the overall prior-season mean."""
        _prior, group_value, group_name, _source = prior_for(season, team, pid)
        return group_value, group_name

    targets = []
    target_rows = []
    role_totals = defaultdict(lambda: [0.0, 0])
    for (season, team), games in sorted(team_games.items()):
        if season not in (*DEV_SEASONS, HOLDOUT_SEASON):
            continue
        for week, game in games:
            for pid in appearances[(season, team)]:
                if (season, game, team, pid) not in snaps:
                    continue
                hist = [share(season, team, g, pid) for w, g in games if w < week]
                prior_player, group_pred, prior_grp, prior_source = prior_for(season, team, pid)
                prior_only = prior_player
                estimate = (sum(hist) + K * prior_player) / (len(hist) + K)
                obs = share(season, team, game, pid)
                targets.append((season, obs, estimate, prior_only, group_pred, prior_grp, prior_source))
                target_rows.append((season, week, game, team, pid, round(obs, 6), round(estimate, 6),
                                    round(prior_only, 6), round(group_pred, 6), prior_grp, prior_source))
                role = group_of_player.get((season, team, pid)) or 'UNK'  # POSTGAME DESCRIPTIVE ONLY
                role_totals[(season, team, role, pid)][0] += obs
                role_totals[(season, team, role, pid)][1] += 1

    results, by_group = {}, {}
    for season in (*DEV_SEASONS, HOLDOUT_SEASON):
        sub = [t for t in targets if t[0] == season]
        if not sub:
            continue
        n = len(sub)
        mse = lambda idx: sum((t[1] - t[idx]) ** 2 for t in sub) / n  # noqa: E731
        results[str(season)] = {'targets': n, 'component_mse': round(mse(2), 6),
                                'prior_only_mse': round(mse(3), 6), 'group_mean_mse': round(mse(4), 6),
                                'improvement_over_prior_only': round(mse(3) - mse(2), 6),
                                'improvement_over_group_mean': round(mse(4) - mse(2), 6)}
        groups = defaultdict(lambda: [0.0, 0.0, 0])
        for t in sub:
            g = groups[t[5]]
            g[0] += (t[1] - t[2]) ** 2
            g[1] += (t[1] - t[4]) ** 2
            g[2] += 1
        by_group[str(season)] = {grp: {'targets': v[2], 'component_mse': round(v[0] / v[2], 6),
                                       'group_mean_mse': round(v[1] / v[2], 6)} for grp, v in sorted(groups.items())}

    role_table = {}
    for season in DEV_SEASONS:
        by_team = defaultdict(list)
        for (s, team, role, pid), (total, n) in role_totals.items():
            if s == season and n:
                by_team[(team, role)].append((total / n, pid))
        ranks = defaultdict(list)
        for (_team, role), items in by_team.items():
            for rank, (mean, _pid) in enumerate(sorted(items, reverse=True), start=1):
                ranks[f'{role}{rank}'].append(mean)
        role_table[str(season)] = {name: {'players': len(vals), 'mean_share': round(sum(vals) / len(vals), 4)}
                                   for name, vals in sorted(ranks.items()) if len(vals) >= 5}

    out = {'source': args.tables.name, 'k': K, 'dev_seasons': list(DEV_SEASONS), 'holdout': HOLDOUT_SEASON,
           'blank_label_note': BLANK_LABEL_NOTE if not args.positions else
           f'position groups from the reconstructed PFR positions ({args.positions.name}) in every season',
           'leakage_check': "the estimate for a game uses only that team's earlier games in the same season and a prior "
                            'from the season before; the position group comes from the prior season only',
           'scoring': results, 'scoring_by_prior_group': by_group,
           'prior_source_counts': {str(season): dict(Counter(t[6] for t in targets if t[0] == season))
                                   for season in sorted({t[0] for t in targets})},
           'role_table_POSTGAME_DESCRIPTIVE_ONLY': role_table}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    if args.targets_out:
        with open(args.targets_out, 'w', newline='', encoding='utf-8') as handle:
            writer = csv.writer(handle)
            writer.writerow(['season', 'week', 'game_id', 'team', 'gsis_id', 'obs_share', 'estimate', 'prior_only',
                             'group_pred', 'prior_group', 'prior_source'])
            for row in target_rows:
                writer.writerow(row)
    print(json.dumps(out['scoring'], sort_keys=True))


if __name__ == '__main__':
    main()
