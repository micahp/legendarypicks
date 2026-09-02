"""Entry point for `python -m espn_client` -- the ad-hoc "what does ESPN say
right now" probe that lived at the bottom of the pre-split module.

The 08-18 split left that block in `__init__.py`, where `-m` never fires it:
python imports the package and then looks for a `__main__` submodule. So the
probe silently stopped existing. `audit_league_stats` had the same hole and it
cost two releases, because the caller that hit it swallowed the error.

    python -m espn_client [league]
"""
import sys

from . import games, team_strength


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    league = argv[0] if argv else "mlb"
    print("== %s top-5 by quality ==" % league)
    for row in team_strength(league)[:5]:
        print("  %-4s %-8s win%%=%s diff=%s %s L10=%s" % (
            row["abbrev"], "%s-%s" % (row["wins"], row["losses"]),
            row["win_pct"], row["differential"], row["streak"], row["last10"]))
    print("== %s games today ==" % league)
    for game in games(league):
        home, away = game["home"], game["away"]
        print("  %s@%s %-4s %s-%s (%s)" % (
            away["abbrev"], home["abbrev"], game["state"],
            away["score"], home["score"], game["status"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
