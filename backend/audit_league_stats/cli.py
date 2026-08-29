"""cli — league stats audit cli layer."""
import argparse
import os
import sqlite3

from .checks import (PASS, FAIL, UNVERIFIED, Result, check_injury_population, check_identity_crosswalk, check_leaders_reach_logs, check_position_content, check_published_identity, check_qualifier_unit, check_required_stats, check_single_vocabulary)  # noqa: E402
from .identity import _identity_name_key  # noqa: E402

# One dirname per directory this file sits below `backend/`. The split moved
# it into a package, so this needs TWO -- with one it resolved to
# `backend/<package>/data/`, which does not exist, and sqlite3.connect
# CREATES the file rather than failing. The job would run against an empty
# database and report success.
DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "picks.db"
)

# Every league we serve a stats surface for. Sourced from docs/LEAGUE-STAT-GAPS.md
# -- which is the measurement, not a wish list. `required` is what a page of this
# league is not honest without.
MANIFEST = {
    "mlb": {
        "stat_types": {
            "batting": {
                # PA is the qualifier's own unit (3.1 x team games). Without the
                # column there is no way to ask the published question at all.
                # `mlb_hits`, not `hits` -- `hits` is an NHL body check. A base
                # hit and a body check are different things sharing a word, and
                # this table is one wide table across four leagues.
                "required": ["games", "avg", "hr", "pa", "mlb_hits", "runs", "rbi"],
                # NO coverage floor declared, deliberately, and the reason is
                # the finding. `pa` sits on 684 of 1451 batting rows (47%),
                # which looks like a hole and is not: all 767 without it are
                # `source='statcast'` marginal players (3-10 games) that MLB's
                # season endpoint does not publish a line for at all. PA is on
                # 100% of the population MLB actually publishes. A floor here
                # would measure the wrong denominator and block releases over
                # correct data -- the open question is which population these
                # 767 rows belong in, not whether the stat is missing.
                "qualifier": {"unit": "pa", "published": "3.1 PA x team games (502/162)"},
            },
            "pitching": {
                "required": ["games", "k_pct", "innings", "era", "whip"],
                "qualifier": {"unit": "innings", "published": "1.0 IP x team games (162/162)"},
            },
        },
        "position_content": {
            # Two classes, measured 2026-08-05: every MLB position's log
            # carries the same ESPN box-score line -- batters (PA/H/R/RBI/HR/
            # BB/K/2B/3B/TB) and pitchers (batters_faced/hits_allowed/outs/
            # BB/K), which are different jobs. A catcher and a shortstop need
            # no different keys; a pitcher's log never carries a batting line
            # (0 of 500 P logs have PA), so P declares the pitching line.
            # 100% coverage measured over 500 sampled logs per class; floor
            # 0.8 trips only on a collapse.
            "1B": {"keys": [["PA"], ["H"], ["R"], ["RBI"], ["HR"]], "coverage": 0.8},
            "2B": {"keys": [["PA"], ["H"], ["R"], ["RBI"], ["HR"]], "coverage": 0.8},
            "3B": {"keys": [["PA"], ["H"], ["R"], ["RBI"], ["HR"]], "coverage": 0.8},
            "C": {"keys": [["PA"], ["H"], ["R"], ["RBI"], ["HR"]], "coverage": 0.8},
            "CF": {"keys": [["PA"], ["H"], ["R"], ["RBI"], ["HR"]], "coverage": 0.8},
            "DH": {"keys": [["PA"], ["H"], ["R"], ["RBI"], ["HR"]], "coverage": 0.8},
            "LF": {"keys": [["PA"], ["H"], ["R"], ["RBI"], ["HR"]], "coverage": 0.8},
            "OF": {"keys": [["PA"], ["H"], ["R"], ["RBI"], ["HR"]], "coverage": 0.8},
            "P": {"keys": [["batters_faced"], ["hits_allowed"], ["outs"]],
                  "coverage": 0.8},
            "RF": {"keys": [["PA"], ["H"], ["R"], ["RBI"], ["HR"]], "coverage": 0.8},
            "SS": {"keys": [["PA"], ["H"], ["R"], ["RBI"], ["HR"]], "coverage": 0.8},
            "TWP": {"keys": [["PA"], ["H"], ["R"], ["RBI"], ["HR"]], "coverage": 0.8},
        },
        # `position` was excluded here with the note "MLB positions are 100% NULL
        # -- check C covers it". That stopped being true on 2026-08-04 when
        # roster_sync applied for MLB for the first time and filled every active
        # player's position, so the column is now worth asking about.
        # `position_group` is asserted the same way: MLB publishes the group
        # level (Outfielder/Infielder/...) alongside the abbreviation, and a
        # column that is written should be measured, not trusted.
        "single_vocabulary": ["position", "position_group", "team"],
    },
    "nba": {
        "stat_types": {
            "season": {
                "required": ["games", "pts", "reb", "ast", "stl", "blk",
                             "fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "minutes"],
                "qualifier": {"unit": "games", "published": "58 games; FG% 300 FGM, 3P% 82 3PM, FT% 125 FTM"},
            },
        },
        "position_content": {
            # One class, measured 2026-08-05: every NBA position's log carries
            # the same box-score line from ESPN (PTS/REB/AST/STL/BLK/FGM/FGA/
            # FTM/FTA/3PM/MIN/TO) -- a point guard and a center need no
            # different keys. 100% coverage measured over 500 sampled logs;
            # floor 0.8 trips only on a collapse.
            "C": {"keys": [["PTS"], ["REB"], ["AST"], ["MIN"], ["FGM"]], "coverage": 0.8},
            "F": {"keys": [["PTS"], ["REB"], ["AST"], ["MIN"], ["FGM"]], "coverage": 0.8},
            "G": {"keys": [["PTS"], ["REB"], ["AST"], ["MIN"], ["FGM"]], "coverage": 0.8},
            "PF": {"keys": [["PTS"], ["REB"], ["AST"], ["MIN"], ["FGM"]], "coverage": 0.8},
            "PG": {"keys": [["PTS"], ["REB"], ["AST"], ["MIN"], ["FGM"]], "coverage": 0.8},
            "SF": {"keys": [["PTS"], ["REB"], ["AST"], ["MIN"], ["FGM"]], "coverage": 0.8},
            "SG": {"keys": [["PTS"], ["REB"], ["AST"], ["MIN"], ["FGM"]], "coverage": 0.8},
        },
        # `position_group` carries the parent level (PF -> F, SG -> G) beside
        # the leaf in `position`, the same split MLB has; see
        # migrate_league_position_groups.py.
        "single_vocabulary": ["position", "position_group", "team"],
    },
    "nhl": {
        "stat_types": {
            # Key must match the stored stat_type (season). The qualifier
            # documents BOTH published rules: skater totals have no games
            # floor (Art Ross = most points), goalie rate stats require the
            # well-documented 1/3-of-schedule qualifier (0.3125 x 82 = 25.6 ->
            # minimum 25 games played, published by Hockey-Reference
            # rate_stat_req.html and visible on its goalie pages).
            "season": {
                "required": ["games", "goals", "assists", "points_nhl", "shots",
                             "plus_minus", "toi",
                             # These four describe the goalie report
                             # (nhle.com publishes them separately). They were
                             # red on purpose until 2026-08-04, when the
                             # columns were added and `ingest_nhl_season_stats`
                             # filled them -- which had been publishing all of
                             # it the whole time.
                             "saves", "shots_against", "save_pct", "gaa"],
                "qualifier": {"unit": "games",
                              "published": "skaters: none (raw totals, Art Ross "
                                           "is most points); goalies: 25 games "
                                           "played (0.3125 x 82) per "
                                           "Hockey-Reference rate_stat_req.html"},
            },
        },
        # The check that would have caught the goalie hole. A goalie whose log
        # holds only skater keys has not been observed goaltending.
        # Three player types, three different jobs, so three different
        # statements of what a log has to record. A goalie whose log holds only
        # skater keys has not been observed goaltending -- and a defenceman
        # measured only on goals is being judged as a forward who is bad at it.
        "position_content": {
            # coverage: the share of sampled logs that must record the stat.
            # The keys below are published per game, so a defenceman whose log
            # never records blockedShots or hits is a log that did not observe
            # him -- red until the log ingest reads the boxscore, see handoff.
            "G": {"keys": [["saves"], ["shotsAgainst", "shots_against"]],
                  "coverage": 0.8},
            "D": {"keys": [["shots"], ["plusMinus", "plus_minus"],
                             ["blockedShots", "blocked_shots"], ["hits"]],
                  "coverage": 0.8},
            "C": {"keys": [["goals"], ["assists"], ["shots"]],
                  "coverage": 0.8},
        },
        "single_vocabulary": ["position", "team"],
    },
    "nfl": {
        "stat_types": {
            "season": {
                "required": ["games", "pass_yds_g", "pass_td", "interceptions",
                             "carries_g", "rush_yds_g", "receptions", "rec_yds_g",
                             "targets", "fantasy_ppr_g",
                             # In every game log, in no column.
                             "rush_td", "rec_td"],
                "qualifier": {"unit": "attempts",
                              "published": "passer rating 14 att x team games; per-game stats ~50% of games"},
            },
        },
        # Alternatives, because the raw log key and the served key differ:
        # `_NFL_KEY_NORMALIZE` renames `rushing_yards` to `rush_yds` on the way
        # out, and asserting only our spelling made this check fail over a
        # rename rather than over missing data. The question is whether the
        # position records rushing yards, not whose word for it is in the JSON.
        "position_content": {
            "QB": {"keys": [["pass_yds", "passing_yards"],
                             ["pass_td", "passing_tds"]], "coverage": 0.8},
            "RB": {"keys": [["carries"], ["rush_yds", "rushing_yards"]],
                    "coverage": 0.8},
            "WR": {"keys": [["targets"], ["rec_yds", "receiving_yards"]],
                    "coverage": 0.8},
            "PK": {"keys": [["fg_made"], ["fg_att"]], "coverage": 0.8},
        },
        # The draft pool's injury fields. On 2026-08-04 prod served 4,508 pool
        # players with injury_status on 0 of them for ~18 hours -- keys present,
        # always null, no error, no empty state. The floor (0.35) sits far
        # below the measured 2026-08-05 population (dev 2,616/4,508, prod
        # 2,617/4,509; last_news_date 1,994) so it trips only on a collapse.
        "injury_population": {"floor": 0.35},
        # `position_group` carries the parent level (FB -> RB, LB -> DEF)
        # beside the leaf in `position`, the same split MLB has; see
        # migrate_league_position_groups.py.
        "single_vocabulary": ["position", "position_group", "team"],
    },
    "ufc": {
        # UFC is fighters + rankings, not a season-stats surface. It holds no
        # player_stats rows (the leaderboard checks A/D/E have nothing to
        # serve), fighters carry no position -- they have divisions, stored in
        # ufc_rankings -- and game logs are per-fight.
        "stat_types": {},
        "position_content": {
            # One class: fighters have no position column, so the declaration
            # is a single all-logs class -- a fight log must record the
            # outcome and the clock. Measured 2026-08-05: result/method on
            # 119/119 logs, round and fight_time_seconds on 118/119.
            "FIGHTER": {"keys": [["result"], ["method"], ["round"],
                                 ["fight_time_seconds"]], "coverage": 0.8,
                        "all_logs": True},
        },
        "single_vocabulary": [],
    },
    "wc": {
        # World Cup 2026 is over and the league is dormant until 2030
        # (AGENTS.md). The tournament's game logs remain in
        # player_game_logs; there are no player_stats rows and no pages
        # serving them.
        "stat_types": {},
        "position_content": {
            # One class: WC footballers carry no position in players (ESPN's
            # soccer feed does not emit one into our table), so the
            # declaration is a single all-logs class -- a footballer's log
            # must record the scoring line. Measured 2026-08-05: goals/
            # assists/shots/sot on 334/334 logs.
            "PLAYER": {"keys": [["goals"], ["assists"], ["shots"], ["sot"]],
                       "coverage": 0.8, "all_logs": True},
        },
        "single_vocabulary": [],
    },
    "atp": {
        # ATP/WTA currently expose tournament draws, match pages, and props.
        # They do not expose a season-totals leaderboard and publish no rows in
        # player_stats. Saying that here is materially different from omitting
        # the league: every audit run now records that the surface was asked
        # about and deliberately has no stat_types to measure.
        "stat_types": {},
        "position_content": {},
        "single_vocabulary": [],
    },
    "wta": {
        "stat_types": {},
        "position_content": {},
        "single_vocabulary": [],
    },
    "mls": {
        "stat_types": {
            "season": {
                # The four keys ingest_soccer_logs._TARGET_STATS maps and
                # writes (zero-filled) for every line. `games` is deliberately
                # absent: the log is one row per game, so a games count is
                # derived, not a key the ingest writes -- and declaring a
                # column nothing writes would fail on a lie.
                "required": ["goals", "assists", "shots", "sot"],
                "qualifier": {"unit": "games",
                              "published": "NONE PUBLISHED that this project "
                              "could verify -- soccer publishes no playing-time "
                              "qualifier"},
            },
        },
        # Soccer's split is GK vs outfield, and the ingest cannot tell them
        # apart today: _TARGET_STATS maps goals/assists/shots/sot for every
        # line and drops saves/minutes, so a GK whose stat row carries only
        # saves and minutes is not written at all. Saves is red on purpose
        # until the ingest maps them -- the same shape as the NHL goalie hole.
        "position_content": {
            "GK": [["saves"], ["minutesPlayed", "minutes"]],
            "D": [["goals"], ["assists"]],
            "M": [["goals"], ["assists"]],
            "F": [["goals"], ["assists"]],
        },
        # `position_group` declared 2026-08-17. ESPN publishes the soccer position
        # hierarchy -- CD/LB/RB/SW all carry D as their parent, AM/CM/DM carry M -- and
        # C/vocabulary[position] was failing because both levels shared one column, so a
        # filter on D silently missed every centre-back stored as CD. The group column
        # now carries the published parent name (Defender/Midfielder/Forward/Goalkeeper),
        # filled by backfill_position_group.py from the fetched vocabulary, never inferred.
        # The rule was verified before it was used: re-deriving the rows that ALREADY had
        # a group reproduced 1,256 of 1,256 with zero disagreements.
        "single_vocabulary": ["position", "position_group", "team"],
    },
    "ncaaf": {
        "stat_types": {
            "season": {
                # The nine keys ingest_ncaaf_logs._STAT_MAP/_KEY_MAP write:
                # passing att/pass_yds/pass_td/intc, rushing rush_yds/rush_td,
                # receiving rec/rec_yds/rec_td. Same `games` caveat as mls:
                # one log row per game, so no games column is written to
                # declare.
                "required": ["att", "pass_yds", "pass_td", "intc",
                             "rush_yds", "rush_td", "rec", "rec_yds", "rec_td"],
                "qualifier": {"unit": "games",
                              "published": "NONE PUBLISHED that this project "
                              "could verify -- college football publishes no "
                              "playing-time qualifier"},
            },
        },
        # Offense + defense, matching what the ingests actually write. The
        # ESPN-summary ingest mapped offense only (QB/RB/WR/TE); the CFBD
        # re-source (2026-08-07) also maps the defensive and interceptions
        # categories (tackles/tackles_solo/sacks/tfl/pd/qbhur/def_td,
        # def_int/def_int_yds/def_int_td) into the stats JSON line, so
        # defensive positions are declared too.
        "position_content": {
            "QB": [["att"], ["pass_yds"], ["pass_td"]],
            "RB": [["rush_yds"], ["rush_td"]],
            "WR": [["rec_yds"], ["rec_td"]],
            "TE": [["rec_yds"], ["rec_td"]],
            "DL": [["tackles"], ["sacks"], ["tfl"]],
            "DE": [["tackles"], ["sacks"], ["tfl"]],
            "DT": [["tackles"], ["sacks"], ["tfl"]],
            "LB": [["tackles"], ["tackles_solo"], ["sacks"]],
            # CFBD publishes the interceptions category only when an INT was
            # recorded (measured 2026-08-10: 198 of 366 game blocks carry it),
            # so a DB log without def_int is an honest zero, not a missing
            # observation. tackles/pd keep the 80% floor; def_int gets a low
            # floor that still trips on a total collapse (0% interceptions).
            # Measured 2026-08-10: CB 6.6%, DB 6.5%, S 7.6% -- on a population
            # where 27% of active ncaaf players carried NO position at all, so
            # thousands of defensive backs were absent from every sample.
            # Re-measured 2026-08-16 after backfill_ncaaf_positions_cfbd.py
            # labelled 5,360 of them from CFBD's published roster:
            # CB 30/500 (6.0%), DB 24/500 (4.8%), S 26/500 (5.2%).
            # The rate did not degrade -- the sample became representative, and
            # a 5% floor set 1.4 points above a 6.5% reading had no headroom for
            # any of the three. def_int is an EVENT rate (most DBs record zero
            # interceptions in a game), not a recording rate, so the floor's job
            # is only to trip on a total collapse. 0.025 is half the lowest
            # current reading and still fails at 0%.
            "DB": {"keys": [["tackles"], ["pd"], ["def_int"]],
                   "coverage": 0.8, "key_coverage": {"def_int": 0.025}},
            "CB": {"keys": [["tackles"], ["pd"], ["def_int"]],
                   "coverage": 0.8, "key_coverage": {"def_int": 0.025}},
            "S": {"keys": [["tackles"], ["pd"], ["def_int"]],
                  "coverage": 0.8, "key_coverage": {"def_int": 0.025}},
        },
        # `position_group` declared 2026-08-17, same reason as mls. ESPN publishes the
        # football hierarchy -- CB/S under DB, C under OL, NT under DT, FB under RB -- and
        # both levels shared one column, so a DB filter missed every corner stored as CB.
        # The group column carries the published root name (Offense/Defense/Special Teams),
        # filled by backfill_position_group.py from the fetched vocabulary. Verified before
        # use: re-deriving the rows that already had a group reproduced 21,489 of 21,489.
        "single_vocabulary": ["position", "position_group", "team"],
    },
}

CHECKS = (check_required_stats, check_position_content, check_single_vocabulary,
          check_leaders_reach_logs, check_qualifier_unit, check_identity_crosswalk,
          check_published_identity, check_injury_population)

def audit(con, leagues=None) -> Result:
    out = Result()
    known = set(MANIFEST)
    served = {
        r[0] for r in con.execute(
            "SELECT DISTINCT league FROM player_stats WHERE league IS NOT NULL")
    }
    for league in sorted(served - known):
        # A league on a stats surface with nobody's manifest behind it. Reported,
        # never silently skipped.
        out.add(UNVERIFIED, league, "manifest",
                "serves player_stats but has no MANIFEST entry -- add one before "
                "trusting any page of it")
    for league in sorted(known if leagues is None else set(leagues) & known):
        for check in CHECKS:
            check(con, league, MANIFEST[league], out)
    return out

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DB)
    parser.add_argument("--league", action="append")
    parser.add_argument("--quiet", action="store_true", help="only non-passing")
    args = parser.parse_args(argv)

    if not os.path.exists(args.db):
        # Absence of the file is absence of evidence, and evidence unavailable is
        # a failure, not a skip.
        print("FAIL audit (no such database: %s)" % args.db)
        return 1
    con = sqlite3.connect(args.db)
    try:
        out = audit(con, args.league)
    finally:
        con.close()

    for state, league, check, detail in out.rows:
        if args.quiet and state == PASS:
            continue
        print("%-10s %-5s %-28s %s" % (state, league, check, detail))
    failures = out.failures
    print("\n%d check(s) failed or unverified, %d passed"
          % (len(failures), len(out.rows) - len(failures)))
    return len(failures)
