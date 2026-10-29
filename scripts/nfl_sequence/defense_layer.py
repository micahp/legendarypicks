"""Pre-event defensive coverage and the coverage-conditioned outcome (SLC v1, research, not adopted).

On a dropback the defense chooses a coverage before the play. This module gives that choice a cutoff-safe prior: the defense's own
coverage shares on dropbacks in the seasons before the cutoff (participation 2016 to 2025, joined to play-by-play for the defense
team), shrunk to the league's shares with the same strength as the formation layer. A coverage that is not published stays UNKNOWN;
no defense is ever assigned it.

The outcome conditioning uses the same counts as formation: the probability of each outcome type given the coverage, shrunk to the
cell, applied as a lift on the cell's weights.
"""
import hashlib
import random
import sqlite3
from collections import Counter, defaultdict

import formation_layer as fl

PRIOR_STRENGTH = fl.PRIOR_STRENGTH
UNKNOWN = fl.UNKNOWN
PARTICIPATION_FIRST = fl.PARTICIPATION_FIRST


def load_coverage(db, seasons):
    """{(game_id, play_id): coverage label} from the participation release; UNKNOWN when unpublished."""
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        seasons = sorted(int(s) for s in seasons)
        marks = ','.join('?' * len(seasons))
        out = {}
        for game_id, play_id, coverage in con.execute(
                f"SELECT nflverse_game_id, play_id, defense_coverage_type FROM nfl_hist_participation WHERE season IN ({marks})",
                seasons):
            if play_id is not None:
                out[(game_id, int(play_id))] = coverage if coverage else UNKNOWN
    finally:
        con.close()
    return out


def priors(db, cutoff_season):
    """Coverage counts on dropbacks by defense team, and league-wide, for seasons before the cutoff."""
    if cutoff_season <= PARTICIPATION_FIRST:
        raise ValueError('no participation data before the cutoff season')
    seasons = list(range(PARTICIPATION_FIRST, int(cutoff_season)))
    coverage = load_coverage(db, seasons)
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        marks = ','.join('?' * len(seasons))
        rows = con.execute(
            f"SELECT game_id, play_id, defteam FROM nfl_pbp WHERE season IN ({marks}) AND week <= 18 AND play_type = 'pass' "
            f"AND defteam IS NOT NULL", seasons).fetchall()
    finally:
        con.close()
    team = defaultdict(Counter)
    league = Counter()
    for game_id, play_id, defteam in rows:
        label = coverage.get((game_id, int(play_id)), UNKNOWN)
        team[defteam][label] += 1
        league[label] += 1
    return {'team': dict(team), 'league': dict(league), 'strength': PRIOR_STRENGTH, 'seasons': seasons}


def distribution(table, defteam):
    """The shrunk distribution over coverage labels for this defense."""
    league = table['league']
    league_total = sum(league.values())
    own = table['team'].get(defteam, Counter())
    own_total = sum(own.values())
    strength = table['strength']
    out = {}
    for label in set(league) | set(own):
        league_share = league[label] / league_total if league_total else 0.0
        out[label] = (own[label] + strength * league_share) / (own_total + strength)
    total = sum(out.values())
    return {label: share / total for label, share in out.items()}


def choose(table, defteam, seed_text):
    """A known coverage for this dropback, drawn before the outcome. UNKNOWN is never chosen; the rest is renormalised."""
    rng = random.Random(int.from_bytes(hashlib.sha256(seed_text.encode()).digest()[:8], 'big'))
    shares = {label: share for label, share in distribution(table, defteam).items() if label != UNKNOWN and share > 0}
    labels = sorted(shares)
    total = sum(shares[label] for label in labels)
    return rng.choices(labels, weights=[shares[label] / total for label in labels], k=1)[0]


def attach(rows, coverage):
    """Set row['coverage'] on each play row (UNKNOWN when unmatched)."""
    for row in rows:
        row['coverage'] = coverage.get((row['game_id'], int(row['play_id'])), UNKNOWN)
    return rows
