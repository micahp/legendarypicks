"""Team score-state splits for play calling: how each team's dropback rate changes with the score (SLC v1, research, not adopted).

The play-call artifact fits one effect per score bucket for the league and one effect per team by down. It has no team-specific
score-state effect. This module adds one: for each team, the log-odds shift of its dropback rate in each score bucket, from the
prior seasons only, relative to its own overall rate. Subtracting the team's own overall rate is what keeps this from repeating the
team-by-down main effect already in the artifact: the shift is the team's deviation in a score state, not its general pass rate.

Shrinkage: a team's rate in a bucket is pulled toward the league's rate in that bucket with strength PRIOR_STRENGTH, and the team's
overall rate is pulled toward the league's overall rate the same way. A team or bucket with no prior-season plays gets a zero shift.
"""
import math

import playcall_model as pm

PRIOR_STRENGTH = 25.0


def _logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def priors(frame, cutoff_season):
    """{'shift': {(team_code, bucket_index): log-odds shift}} from the frame's seasons before the cutoff."""
    a = frame.a
    seasons = a['season']
    keep = seasons < int(cutoff_season)
    team_index = a['team'][keep]
    bucket = a['score'][keep]
    y = a['y'][keep].astype(float)
    n_buckets = len(pm.SCORE_BUCKETS)
    league_bucket_n = [0.0] * n_buckets
    league_bucket_y = [0.0] * n_buckets
    for b, yy in zip(bucket, y):
        league_bucket_n[int(b)] += 1
        league_bucket_y[int(b)] += yy
    league_all = sum(league_bucket_y) / max(1.0, sum(league_bucket_n))
    league_rate = [(league_bucket_y[b] + PRIOR_STRENGTH * league_all) / (league_bucket_n[b] + PRIOR_STRENGTH)
                   for b in range(n_buckets)]
    team_n = {}
    team_y = {}
    for t, b, yy in zip(team_index, bucket, y):
        key = (int(t), int(b))
        team_n[key] = team_n.get(key, 0.0) + 1
        team_y[key] = team_y.get(key, 0.0) + yy
    shift = {}
    teams = sorted({k[0] for k in team_n})
    for t in teams:
        n_all = sum(team_n.get((t, b), 0.0) for b in range(n_buckets))
        y_all = sum(team_y.get((t, b), 0.0) for b in range(n_buckets))
        overall = (y_all + PRIOR_STRENGTH * league_all) / (n_all + PRIOR_STRENGTH)
        for b in range(n_buckets):
            n_tb = team_n.get((t, b), 0.0)
            y_tb = team_y.get((t, b), 0.0)
            rate = (y_tb + PRIOR_STRENGTH * league_rate[b]) / (n_tb + PRIOR_STRENGTH)
            shift[(t, b)] = _logit(rate) - _logit(overall)
    return {'shift': shift, 'buckets': n_buckets, 'seasons': sorted({int(s) for s in seasons[keep]})}


def shift_for(table, team_index, bucket):
    """The log-odds shift for one team in one score bucket; zero when the team is unknown."""
    if team_index is None:
        return 0.0
    return table['shift'].get((int(team_index), int(bucket)), 0.0)


def adjust(p, delta):
    """Apply a log-odds shift to a dropback probability."""
    return 1.0 / (1.0 + math.exp(-(_logit(p) + delta)))
