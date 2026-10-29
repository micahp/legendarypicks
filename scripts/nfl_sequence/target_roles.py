"""Decision model v1, category A (target role), as a pre-event prior inside SLC (research, not adopted).

The decision model's category A is the role of the targeted player: RB, WR, TE or Other, on pass plays. Its prior is team-specific
within a situation (down, distance bucket, yard-line bucket), shrunk toward the league's distribution in the same situation with
strength 20 (the k that the decision model chose on 2025 validation). This module re-derives category A from the database, using the
same role definition and the same shrinkage, because the frozen 2025 file's raw inputs are outside the repository. The frozen prior's
hash is reproduced separately (SLC-DECISION-MODEL-V1-REUSE-2026-10-29.md); this module does not use that file.

Only seasons before the cutoff enter the prior. A role that is not on the frozen roster is not drawn; the choice falls back to the
player shares within the target positions.
"""
import hashlib
import random
import sqlite3
from collections import Counter, defaultdict

import e0_single_play as e0

ROLES = ('RB', 'WR', 'TE', 'Other')
K = 20.0  # the decision model's chosen shrinkage weight, from its 2025 validation
FIRST_SEASON = 2016


def role_of(position):
    return position if position in ('RB', 'WR', 'TE') else 'Other'


def cell_of(down, togo, yl):
    return (int(down), e0.ydstogo_bucket(togo), e0.yardline_bucket(yl))


def load(db, cutoff_season):
    """Team and league counts of target roles per situation, from pass plays before the cutoff."""
    seasons = list(range(FIRST_SEASON, int(cutoff_season)))
    if not seasons:
        raise ValueError('no prior seasons before the cutoff')
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        marks = ','.join('?' * len(seasons))
        rows = con.execute(
            f"SELECT p.posteam, p.down, p.ydstogo, p.yardline_100, pl.position FROM nfl_pbp p "
            f"JOIN players pl ON pl.nfl_gsis_id = p.receiver_player_id AND pl.league = 'nfl' "
            f"WHERE p.season IN ({marks}) AND p.week <= 18 AND p.play_type = 'pass' AND p.posteam IS NOT NULL "
            f"AND p.down BETWEEN 1 AND 4 AND p.ydstogo IS NOT NULL AND p.yardline_100 IS NOT NULL", seasons).fetchall()
    finally:
        con.close()
    team = defaultdict(Counter)
    league = defaultdict(Counter)
    for team_code, down, togo, yl, position in rows:
        cell = cell_of(down, togo, yl)
        role = role_of(position)
        team[(team_code, cell)][role] += 1
        league[cell][role] += 1
    return {'team': dict(team), 'league': dict(league), 'seasons': seasons, 'k': K}


def distribution(table, team, down, togo, yl):
    """P(role) for this team in this situation: team counts plus k times the league's share, over their total plus k."""
    cell = cell_of(down, togo, yl)
    league = table['league'].get(cell, Counter())
    league_total = sum(league.values())
    own = table['team'].get((team, cell), Counter())
    own_total = sum(own.values())
    out = {}
    for role in ROLES:
        league_share = league[role] / league_total if league_total else 1.0 / len(ROLES)
        out[role] = (own[role] + table['k'] * league_share) / (own_total + table['k'])
    total = sum(out.values())
    return {role: share / total for role, share in out.items()}


def draw(table, team, down, togo, yl, seed_text, available=None):
    """A role for this dropback, drawn before the outcome. `available` limits the roles to those on the frozen roster."""
    shares = distribution(table, team, down, togo, yl)
    roles = [r for r in ROLES if available is None or r in available]
    if not roles:
        return None
    rng = random.Random(int.from_bytes(hashlib.sha256(seed_text.encode()).digest()[:8], 'big'))
    total = sum(shares[r] for r in roles)
    return rng.choices(roles, weights=[shares[r] / total for r in roles], k=1)[0]
