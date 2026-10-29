"""The sealed holdout. Every path that can read a season checks it here before touching data.

2026 is the holdout season. Two kinds of read may touch it:

- a read with an explicit pregame cutoff (a game, or a week before one), which returns only rows observed before that cutoff.
  The 2026 Weeks 1-7 benchmark and the Week 8 prospective forecasts are evaluated this way, under the user's direction of
  2026-10-28;
- nothing else. A fit, a tuning step, or an unbounded read that includes 2026 is refused. A model that predicts 2026 is fitted on
  seasons before 2026 only: the play-call artifact for a 2026 evaluation is fitted through 2025.

`refuse_if_holdout` is the unbounded guard. `refuse_unless_cutoff` is the guard for reads that carry a cutoff. Neither
replaces the cutoff's own checks (schedule versions observed by the cutoff, depth-chart times, kickoff ordering).
"""

HOLDOUT_SEASON = 2026


def refuse_if_holdout(season, what):
    if int(season) >= HOLDOUT_SEASON:
        raise ValueError(f'{what}: season {season} is the sealed {HOLDOUT_SEASON} holdout; an unbounded read or fit is '
                         'refused. A read with an explicit pregame cutoff is allowed')


def refuse_unless_cutoff(season, what, cutoff):
    """A season at or after the holdout is readable only with an explicit cutoff."""
    if int(season) >= HOLDOUT_SEASON and cutoff is None:
        raise ValueError(f'{what}: season {season} is the sealed {HOLDOUT_SEASON} holdout and needs an explicit pregame cutoff')
