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

Role. A role is the position label plus its rank among that label on the team, by the season's mean share (1 is the
most-used). The role table is descriptive, from the development seasons only, and uses the season's own labels, so it
is not a prediction input.

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
        for pid, label in zip(row['offense_ids'].split(';'), row['offense_positions'].split(';')):
            if pid:
                snaps[(*key, pid)] += 1
                if label:
                    labels[(*key, pid)][label] += 1

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

    def prior_group_mean(season, team, pid):
        """The group prior from the season before: the player's group that season, else the overall prior-season mean."""
        grp = group_of_player.get((season - 1, team, pid))
        if grp and (season - 1, grp) in group_mean:
            return group_mean[(season - 1, grp)], grp
        return overall_mean.get(season - 1, 0.0), 'UNK'

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
                prev = (season - 1, team, pid)
                group_pred, prior_grp = prior_group_mean(season, team, pid)
                prior_player = team_mean[prev] if prev in team_mean else group_pred
                prior_only = prior_player
                estimate = (sum(hist) + K * prior_player) / (len(hist) + K)
                obs = share(season, team, game, pid)
                targets.append((season, obs, estimate, prior_only, group_pred, prior_grp))
                target_rows.append((season, week, game, team, pid, round(obs, 6), round(estimate, 6),
                                    round(prior_only, 6), round(group_pred, 6), prior_grp))
                role = group_of_player.get((season, team, pid)) or 'UNK'
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
           'blank_label_note': BLANK_LABEL_NOTE,
           'leakage_check': "the estimate for a game uses only that team's earlier games in the same season and a prior "
                            'from the season before; the position group comes from the prior season only',
           'scoring': results, 'scoring_by_prior_group': by_group, 'role_table_dev_descriptive': role_table}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    if args.targets_out:
        with open(args.targets_out, 'w', newline='', encoding='utf-8') as handle:
            writer = csv.writer(handle)
            writer.writerow(['season', 'week', 'game_id', 'team', 'gsis_id', 'obs_share', 'estimate', 'prior_only',
                             'group_pred', 'prior_group'])
            for row in target_rows:
                writer.writerow(row)
    print(json.dumps(out['scoring'], sort_keys=True))


if __name__ == '__main__':
    main()
