#!/usr/bin/env python3
"""Does each league actually hold what its pages claim? One runner, every ingest.

Why this exists
---------------
Every gap found on 2026-08-04 was invisible to the checks we already had. Row
counts were healthy. The API returned 200. Gates were green. And:

  * 78 of 90 NHL goalies had game logs, and not one save. A goalie's log carried
    `goals, assists, pim, toi` -- skater keys. 64 logged games for Vejmelka, zero
    saves. **The rows looked like coverage.**
  * `rush_td` and `rec_td` sat in every NFL game log and in no `player_stats`
    column, so the leaderboard could not sort by the most-used fantasy stat.
  * `players.position` held TWO vocabularies for NBA -- coarse `G/F/C` from the
    ESPN ingest, granular `PG/SG/SF/PF` from the hoopR one -- over nearly
    disjoint populations, which is why 472 of 525 leaders clicked through to an
    empty page.
  * The MLB batting qualifier was `games >= 30` where the published rule is
    3.1 plate appearances per team game, and `PA` was not a column.

None of those are count problems, so no count would ever have caught them. They
are all the same shape: **a thing was present and was not what it claimed to
be.** This asks the claim, per league, and every check is written so that
missing evidence FAILS rather than skips.

Checks
------
A  required stats exist AND are populated       -- the column, not just the row
B  a position's logs carry that position's keys -- goalies must record saves
C  one vocabulary per categorical column        -- two ingests, two spellings
D  the leaderboard's population has game logs   -- a leader you can click into
E  the qualifier is denominated in the published unit
F  every publisher can reach the league's players -- one row per person
G  an external id points at the person named on the row
H  the NFL pool's injury fields are populated   -- a board with nobody listed injured

Adding a league
---------------
Add an entry to `MANIFEST`. That is the whole integration -- the runner iterates
it. A league with no entry is reported as UNVERIFIED, never as passing, because
"nobody wrote a manifest" and "the data is fine" must not look the same.

Usage
-----
    python audit_league_stats.py --db data/picks.db
    python audit_league_stats.py --db data/picks.db --league nhl
    python audit_league_stats.py --db data/picks.db --quiet   # only failures
Exit code is the number of failing checks, so it drops straight into a gate.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import unicodedata

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
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
                "qualifier": {"unit": "pa", "published": "3.1 PA x team games (502/162)"},
            },
            "pitching": {
                "required": ["games", "k_pct", "innings", "era", "whip"],
                "qualifier": {"unit": "innings", "published": "1.0 IP x team games (162/162)"},
            },
        },
        "position_content": {},
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
        "position_content": {},
        "single_vocabulary": ["position", "team"],
    },
    "nhl": {
        "stat_types": {
            "season": {
                "required": ["games", "goals", "assists", "points_nhl", "shots",
                             "plus_minus", "toi",
                             # Hockey has three player types, and the seven
                             # columns above describe one of them. These four
                             # were red on purpose until 2026-08-04, when the
                             # columns were added and `ingest_nhl_season_stats`
                             # filled them from nhle.com's goalie report --
                             # which had been publishing all of it the whole
                             # time.
                             "saves", "shots_against", "save_pct", "gaa"],
                "qualifier": {"unit": "games",
                              "published": "NONE PUBLISHED that this project could verify -- 40+ GP is convention"},
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
        "single_vocabulary": ["position", "team"],
    },
    "ufc": {
        # UFC is fighters + rankings, not a season-stats surface. It holds no
        # player_stats rows (the leaderboard checks A/D/E have nothing to
        # serve), fighters carry no position -- they have divisions, stored in
        # ufc_rankings -- and game logs are per-fight. Nothing to declare,
        # said out loud rather than omitted: a league the audit cannot see is
        # a league nobody measured.
        "stat_types": {},
        "position_content": {},
        "single_vocabulary": [],
    },
    "wc": {
        # World Cup 2026 is over and the league is dormant until 2030
        # (AGENTS.md). The tournament's 3,222 game logs remain in
        # player_game_logs; there are no player_stats rows and no pages
        # serving them -- nothing to declare for the stats checks, said out
        # loud rather than omitted.
        "stat_types": {},
        "position_content": {},
        "single_vocabulary": [],
    },
}

_POSITION_CONTENT_FLOOR = 0.8


PASS, FAIL, UNVERIFIED = "PASS", "FAIL", "UNVERIFIED"

# Written by fetch_position_vocabulary.py and committed. The audit must run
# offline, and a vocabulary read at audit time could not be reviewed in a diff.
_VOCABULARY_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "position-vocabulary.json")
_VOCABULARY_CACHE = {}


# Written by fetch_identity_names.py and committed, for the same reason as the
# vocabulary above: the audit runs offline and an identity map read at audit
# time could not be reviewed in a diff.
_IDENTITY_NAMES_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "published-identity-names.json")
_IDENTITY_NAMES_CACHE = {}


def _identity_name_key(name):
    """Compare two spellings of a name without tolerating two different people.

    Publishers disagree on decoration, never on who someone is. MLB writes
    'Jeremy Peña' and 'Nasim Nuñez' where this database holds ASCII, and a
    literal comparison called 25 of those a corrupt id -- noise that would have
    buried the 224 real ones. So fold accents, case, punctuation and generational
    suffixes, and nothing else. 'Kyle Harrison' and 'Edmundo Sosa' must stay
    different, because on prod they shared an mlbam_id and they are not the same
    man.
    """
    folded = unicodedata.normalize("NFKD", name or "")
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = re.sub(r"[^a-z ]", "", folded.lower())
    folded = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", folded)
    # Drop a bare middle initial. MLB publishes BOTH Max Muncys as 'Max Muncy'
    # (571970 LAD and 691777 ATH), so this database disambiguates one of them
    # locally as 'Max P. Muncy' -- correct data that a literal comparison calls
    # a corrupt id. An initial carries no identity the surname does not already
    # carry; two different people never differ by it alone.
    folded = re.sub(r"\b[a-z]\b", "", folded)
    return " ".join(folded.split())


def _published_identity_names(league):
    """{id_column, names} as the publisher publishes them, or None if never fetched."""
    if not _IDENTITY_NAMES_CACHE:
        try:
            with open(_IDENTITY_NAMES_PATH) as f:
                _IDENTITY_NAMES_CACHE["data"] = json.load(f)
        except (OSError, json.JSONDecodeError):
            _IDENTITY_NAMES_CACHE["data"] = None
    artifact = _IDENTITY_NAMES_CACHE.get("data")
    if not artifact:
        return None
    entry = artifact.get("leagues", {}).get(league)
    if not entry or not entry.get("names"):
        return None
    return {"id_column": entry.get("id_column"), "names": entry["names"]}


def _observed_positions(con, league, active_only=False):
    """The distinct position codes in use for a league.

    Fantasy constructs (team defences, TQB, coaches) are excluded once
    `entity_type` exists: a D/ST plays no position, and its former
    `position='DEF'` must not read as a second vocabulary fighting the real
    defensive positions.
    """
    scope = " AND active=1" if active_only and "active" in _columns(con, "players") else ""
    if "entity_type" in _columns(con, "players"):
        scope += " AND COALESCE(entity_type, 'player') = 'player'"
    return {
        r[0] for r in con.execute(
            f"SELECT position FROM players WHERE league=?{scope} "
            "AND position IS NOT NULL AND TRIM(position) != '' GROUP BY 1", (league,))
    }


def _declares_group_column(con, league, spec):
    """True when the league declares a populated group column for `position`.

    MLB's `position_group` carries the parent type (Outfielder/Infielder/...)
    beside the abbreviation in `position`, so a published parent value (OF)
    coexisting with its children (LF/CF/RF) is addressable -- anyone wanting
    the group filters position_group -- rather than a vocabulary clash. It
    must be BOTH in the league's spec AND actually carrying values: an empty
    column would hide the very split the overlap check exists to catch.
    """
    column = "position_group"
    if column not in (spec.get("single_vocabulary") or []):
        return False
    if column not in _columns(con, "players"):
        return False
    filled = con.execute(
        f"SELECT COUNT(*) FROM players WHERE league=? AND {column} IS NOT NULL "
        f"AND TRIM({column}) != ''", (league,)).fetchone()[0]
    return filled > 0


def _position_vocabulary(league):
    """{positions, ancestry, source} as published, or None if never fetched.

    None is answered honestly as UNVERIFIED rather than falling back to a guess:
    the guess is what this replaced.
    """
    if not _VOCABULARY_CACHE:
        try:
            with open(_VOCABULARY_PATH) as f:
                _VOCABULARY_CACHE["data"] = json.load(f)
        except (OSError, json.JSONDecodeError):
            _VOCABULARY_CACHE["data"] = None
    artifact = _VOCABULARY_CACHE.get("data")
    if not artifact:
        return None
    entry = artifact.get("leagues", {}).get(league)
    if not entry:
        return None
    return {
        "positions": entry.get("positions", {}),
        "ancestry": entry.get("ancestry", {}),
        "source": artifact.get("_provenance", {}).get("source", "ESPN"),
    }


class Result:
    def __init__(self):
        self.rows = []

    def add(self, state, league, check, detail):
        self.rows.append((state, league, check, detail))

    @property
    def failures(self):
        # UNVERIFIED counts as a failure. Evidence unavailable is not a pass and
        # is not a skip -- that is the rule this whole file exists to enforce.
        return [r for r in self.rows if r[0] != PASS]


def _columns(con, table):
    try:
        return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    except sqlite3.OperationalError:
        return set()


def check_required_stats(con, league, spec, out):
    """A. The column exists AND carries values for this league."""
    columns = _columns(con, "player_stats")
    if not columns:
        out.add(FAIL, league, "A/required-stats", "player_stats is unreadable")
        return
    for stat_type, cfg in spec["stat_types"].items():
        missing, empty = [], []
        for column in cfg["required"]:
            if column not in columns:
                missing.append(column)
                continue
            filled = con.execute(
                f"SELECT COUNT({column}) FROM player_stats "
                "WHERE league=? AND stat_type=?", (league, stat_type)
            ).fetchone()[0]
            if not filled:
                empty.append(column)
        if missing or empty:
            parts = []
            if missing:
                parts.append("no such column: " + ", ".join(missing))
            if empty:
                parts.append("column exists but 0 rows populated: " + ", ".join(empty))
            out.add(FAIL, league, f"A/required-stats[{stat_type}]", "; ".join(parts))
        else:
            out.add(PASS, league, f"A/required-stats[{stat_type}]",
                    "%d required stats present and populated" % len(cfg["required"]))


def check_position_content(con, league, spec, out):
    """B. A position's game logs carry that position's defining keys.

    The goalie check. Presence of rows says a player was observed; it does not
    say he was observed doing his job.

    Measures COVERAGE, not presence: a stat recorded in 1 of 500 sampled logs
    is a 0.2% observation, not a pass. Each position declares its floor in the
    MANIFEST (dict form); legacy list entries default to `_POSITION_CONTENT_FLOOR`.
    This check read PASS for NHL at 30% coverage on 2026-08-05 because the old
    logic only failed a stat that never appeared at all.
    """
    wanted = spec.get("position_content") or {}
    if not wanted:
        out.add(UNVERIFIED, league, "B/position-content",
                "no position_content declared -- nobody has said what this "
                "league's positions must record")
        return
    for position, entry in sorted(wanted.items()):
        if isinstance(entry, dict):
            keys = entry["keys"]
            floor = float(entry.get("coverage", _POSITION_CONTENT_FLOOR))
        else:
            keys = entry
            floor = _POSITION_CONTENT_FLOOR
        rows = con.execute(
            """SELECT l.stats FROM player_game_logs l
               JOIN players p ON p.id = l.player_id
               WHERE l.league=? AND UPPER(TRIM(p.position))=? LIMIT 500""",
            (league, position.upper()),
        ).fetchall()
        if not rows:
            out.add(UNVERIFIED, league, f"B/position-content[{position}]",
                    "no game logs at all for this position -- cannot confirm "
                    "its stats are recorded")
            continue
        sampled = len(rows)
        # Each entry is a list of acceptable spellings for ONE stat; a log
        # records the stat when any spelling carries a non-null value.
        filled = [0] * len(keys)
        for row in rows:
            try:
                payload = json.loads(row[0])
            except (TypeError, ValueError):
                continue
            for i, alts in enumerate(keys):
                if any(payload.get(k) is not None for k in alts):
                    filled[i] += 1
        counts = ["%s %d/%d (%.0f%%)" % (alts[0], filled[i], sampled,
                                          100.0 * filled[i] / sampled)
                  for i, alts in enumerate(keys)]
        low = [c for i, c in enumerate(counts) if filled[i] < floor * sampled]
        if low:
            out.add(FAIL, league, f"B/position-content[{position}]",
                    "%d logs sampled, below the %.0f%% floor: %s"
                    % (sampled, 100 * floor, "; ".join(low)))
        else:
            out.add(PASS, league, f"B/position-content[{position}]",
                    "%d logs sampled, all recorded at >=%.0f%%: %s"
                    % (sampled, 100 * floor, ", ".join(counts)))


def check_single_vocabulary(con, league, spec, out):
    """C. One categorical column, one vocabulary.

    Two ingests writing `G/F/C` and `PG/SG/SF/PF` into the same column is not a
    style difference -- it partitions the league into populations that never
    join, and a join that misses does not raise.
    """
    for column in spec.get("single_vocabulary") or []:
        vocabulary_note = ""
        if column not in _columns(con, "players"):
            out.add(FAIL, league, f"C/vocabulary[{column}]",
                    f"players.{column} does not exist")
            continue
        values = [
            (r[0], r[1]) for r in con.execute(
                f"SELECT {column}, COUNT(*) FROM players WHERE league=? "
                f"AND {column} IS NOT NULL AND TRIM({column}) != '' "
                f"GROUP BY 1 ORDER BY 2 DESC", (league,))
        ]
        total = sum(n for _, n in values)
        # A fantasy construct (team defence, TQB, coach) plays no position --
        # `position` NULL is the honest answer, so those rows are not blanks.
        entity_scope = ""
        if column == "position" and "entity_type" in _columns(con, "players"):
            entity_scope = " AND COALESCE(entity_type, 'player') = 'player'"
        blank = con.execute(
            f"SELECT COUNT(*) FROM players WHERE league=? "
            f"AND ({column} IS NULL OR TRIM({column})=''){entity_scope}", (league,)
        ).fetchone()[0]
        if not total:
            out.add(FAIL, league, f"C/vocabulary[{column}]",
                    f"every row blank ({blank} players)")
            continue
        if column == "position":
            # This used to read "one character is coarse, two is granular, both
            # present means two ingests are fighting". That is a string-length
            # proxy for a semantic property and it is wrong in three of four
            # leagues -- hockey's C/D/G/LW/RW is ONE vocabulary, and football's
            # S/G/C/P belong to the same vocabulary as WR/LB/CB. It failed
            # leagues that were fine while asking nothing about the leagues that
            # were not.
            #
            # ESPN publishes the hierarchy: every position carries `leaf` and a
            # `parent`, so the real question is answerable instead of guessed.
            # Two vocabularies are in play when a position AND one of its own
            # descendants are both in use -- `G` alongside `PG` -- because those
            # rows describe the same player population at two levels and never
            # join. Two codes of different lengths are not evidence of anything.
            #
            # One exception, learned the hard way: a league that declares a
            # populated group column (MLB's `position_group`) can legitimately
            # hold a published parent (OF) beside its children (LF/CF/RF) -- the
            # levels ARE distinguished, by that column. Without it, the old
            # defect stands and still fails.
            # Scoped to active players for the same reason the blank check below
            # is: a position is a CURRENT roster spot, and a retired player
            # carrying a dead code is league history, not a defect. Inactive-only
            # violations are reported, never dropped -- NHL's `L`/`R` and NFL's
            # `HC`/`K`/`SAF`/`TQB` live entirely there.
            vocabulary = _position_vocabulary(league)
            observed = _observed_positions(con, league, active_only=True)
            historical = _observed_positions(con, league) - observed
            if vocabulary:
                ancestry = vocabulary["ancestry"]
                overlaps = sorted(
                    (child, parent)
                    for child in observed
                    for parent in ancestry.get(child, [])
                    if parent in observed
                )
                unknown = sorted(observed - set(vocabulary["positions"]))
                stale = sorted(historical - set(vocabulary["positions"]))
                # Named in every message so a clean active roster can never be
                # mistaken for "no dead codes anywhere in the table".
                trailer = f"; inactive rows also hold {stale}" if stale else ""
                if overlaps and not _declares_group_column(con, league, spec):
                    out.add(FAIL, league, f"C/vocabulary[{column}]",
                            "two levels of one vocabulary in the same column: %s "
                            "-- each pair is a position and its own parent, which "
                            "describe the same players and do not join%s"
                            % (", ".join(f"{c} under {p}" for c, p in overlaps),
                               trailer))
                    continue
                if overlaps:
                    # The league declares a populated group column, so the
                    # parent/child split is addressable: position_group carries
                    # the parent. A published parent beside its children is
                    # then a fact, not a defect -- and the failure the gate
                    # exists to catch is the league with NO way to ask the
                    # group question.
                    vocabulary_note = ("; parent/child levels coexist -- the "
                                       "group column carries the parent"
                                       + trailer)
                if unknown:
                    out.add(FAIL, league, f"C/vocabulary[{column}]",
                            "not in the vocabulary %s publishes: %s%s"
                            % (vocabulary["source"], unknown, trailer))
                    continue
                # Clean: fall through to the blank check rather than passing
                # here, so a tidy vocabulary cannot vouch for a column that is
                # half empty. The stale note rides along on whatever it reports.
                vocabulary_note = trailer
            else:
                out.add(UNVERIFIED, league, f"C/vocabulary[{column}]",
                        "no published vocabulary on disk -- run "
                        "fetch_position_vocabulary.py; refusing to judge "
                        "positions against a list nobody published")
                continue
        # `team` and `position` describe a CURRENT roster spot. A retired player
        # has neither, and blank is the honest answer for him -- so counting him
        # as a defect asserts something false and buries the real signal under
        # league history. The failure is scoped to active players; inactive
        # blanks are still reported, never dropped.
        active_blank, inactive_blank = blank, 0
        if "active" in _columns(con, "players"):
            active_blank = con.execute(
                f"SELECT COUNT(*) FROM players WHERE league=? AND active=1 "
                f"AND ({column} IS NULL OR TRIM({column})=''){entity_scope}", (league,)
            ).fetchone()[0]
            inactive_blank = blank - active_blank
        if active_blank:
            active_total = con.execute(
                f"SELECT COUNT(*) FROM players WHERE league=? AND active=1{entity_scope}"
                if "active" in _columns(con, "players")
                else "SELECT COUNT(*) FROM players WHERE league=?", (league,)
            ).fetchone()[0] or (blank + total)
            # Report the count first. A bare "0%" next to FAIL reads as a bug in
            # the gate rather than as two genuinely unlabelled players.
            out.add(FAIL, league, f"C/vocabulary[{column}]",
                    "%d of %d ACTIVE players blank (%.2f%%)"
                    % (active_blank, active_total,
                       100.0 * active_blank / active_total))
            continue
        note = ("one vocabulary, %d values, 0 blank on active players%s"
                % (len(values), vocabulary_note))
        if inactive_blank:
            note += (" (%d inactive players carry no %s -- they are on no "
                     "roster, which is the honest answer)"
                     % (inactive_blank, column))
        out.add(PASS, league, f"C/vocabulary[{column}]", note)


def check_leaders_reach_logs(con, league, spec, out, floor=0.60):
    """D. Can you click a leader and see a game?

    A leaderboard whose players have no logs in the season it serves is a page
    of dead ends. On 2026-08-04 only 53 of 525 NBA leaders had a 2026 log.

    The join is season-scoped on BOTH sides: a log from three seasons ago
    counts as reachable for nothing a leaderboard serves today. This check read
    PASS for NHL twice on 2026-08-05 while a season-scoped join returned 0 --
    prod still held 48,017 rows on nhle.com's raw `20252026` season key.
    """
    served = con.execute(
        "SELECT MAX(season) FROM player_stats WHERE league=?", (league,)
    ).fetchone()[0]
    if served is None:
        out.add(FAIL, league, "D/leaders-reach-logs", "no player_stats rows at all")
        return
    total, reachable = con.execute(
        """SELECT COUNT(*), SUM(CASE WHEN EXISTS(
               SELECT 1 FROM player_game_logs g
                WHERE g.player_id = s.player_id AND g.league = s.league
                  AND g.season = s.season
           ) THEN 1 ELSE 0 END)
           FROM player_stats s WHERE s.league=? AND s.season=?""",
        (league, served),
    ).fetchone()
    reachable = reachable or 0
    share = (reachable / total) if total else 0.0
    detail = ("season %s: %d of %d leaderboard players have a game log "
              "in that same season (%.0f%%)"
              % (served, reachable, total, 100 * share))
    out.add(PASS if share >= floor else FAIL, league, "D/leaders-reach-logs", detail)


def check_qualifier_unit(con, league, spec, out):
    """E. Is the qualifier's unit a column we hold?

    Every published qualifier is denominated in plate appearances, innings,
    attempts or made shots. Ours is `min_games`. Games cannot proxy for PA -- a
    pinch hitter and a leadoff man play the same number of games -- so this
    asserts the unit's COLUMN exists, which is the precondition for asking the
    published question at all.
    """
    columns = _columns(con, "player_stats")
    for stat_type, cfg in spec["stat_types"].items():
        qualifier = cfg.get("qualifier") or {}
        unit, published = qualifier.get("unit"), qualifier.get("published")
        if not unit:
            out.add(UNVERIFIED, league, f"E/qualifier[{stat_type}]",
                    "no qualifier declared")
            continue
        if published and published.startswith("NONE PUBLISHED"):
            out.add(UNVERIFIED, league, f"E/qualifier[{stat_type}]", published)
            continue
        if unit not in columns:
            out.add(FAIL, league, f"E/qualifier[{stat_type}]",
                    "published rule is '%s' but there is no `%s` column to "
                    "measure it with" % (published, unit))
        else:
            out.add(PASS, league, f"E/qualifier[{stat_type}]",
                    "`%s` present; published rule: %s" % (unit, published))


def check_identity_crosswalk(con, league, spec, out):
    """F. Can every publisher we depend on actually reach this league's players?

    `players` is the spine: one row per person, carrying our `id` plus one
    external id per publisher (`espn_id`, `mlbam_id`, `nfl_gsis_id`, `nhl_id`,
    `nba_id`). Everything else joins on `players.id`. So a publisher can only
    contribute to a league if the spine carries ITS id -- and a league's entire
    character is decided by that one fact, silently, at ingest time.

    Measured on prod 2026-08-04, and it explains every gap found this week:

      NFL   18,697 espn_id + 25,007 gsis, 16,774 rows carry BOTH.  Healthy.
            Team, position, ranks, news and ADP all work because two publishers
            can reach the same row.
      NBA   521 espn_id, 541 nba_id, **0 rows carry both.**  Two disjoint
            populations, 269 athletes split across two `players.id` rows -- one
            holding the historical stats, the other the current game logs.
      MLB   2,747 mlbam_id, **0 espn_id.**  ESPN is what publishes team and
            position, so `players.team` is 89% blank and `position` is 100%.
      NHL   875 nhl_id, **0 espn_id.**  The nhle.com feed is skater-shaped, so
            no goalie has ever recorded a save.

    Two failures, and they are different:

    `split` -- one athlete's id appears in a legacy column on one row and in
    `espn_id` on another. Those are the same person and no join will ever bring
    them together. This is what `backend/scripts/merge_nba_identities.py` exists
    to repair.

    `disjoint` -- two id columns are both populated for the league and NO row
    carries both. Nothing is split yet in the pairwise sense, but there is no
    crosswalk at all, so the next ingest keyed on the other id creates a second
    population rather than enriching the first. It is the condition immediately
    before the damage.
    """
    columns = _columns(con, "players")
    legacy = [c for c in ("mlbam_id", "nfl_gsis_id", "nhl_id", "nba_id") if c in columns]
    if "espn_id" not in columns or not legacy:
        out.add(UNVERIFIED, league, "F/identity-crosswalk",
                "players carries no external id columns to cross-check")
        return

    def filled(column):
        return con.execute(
            f"SELECT COUNT(*) FROM players WHERE league=? "
            f"AND {column} IS NOT NULL AND TRIM({column})!=''", (league,)
        ).fetchone()[0]

    espn = filled("espn_id")
    problems, notes = [], ["espn_id=%d" % espn]
    for column in legacy:
        count = filled(column)
        if not count:
            continue
        notes.append("%s=%d" % (column, count))
        both = con.execute(
            f"""SELECT COUNT(*) FROM players WHERE league=?
                AND {column} IS NOT NULL AND TRIM({column})!=''
                AND espn_id IS NOT NULL AND TRIM(espn_id)!=''""", (league,)
        ).fetchone()[0]
        split = con.execute(
            f"""SELECT COUNT(*) FROM players a JOIN players b
                  ON a.{column} = b.espn_id AND a.id != b.id
                WHERE a.league=? AND b.league=?
                  AND a.{column} IS NOT NULL AND TRIM(a.{column})!=''""",
            (league, league),
        ).fetchone()[0]
        if split:
            problems.append(
                "%d athletes split across two players.id rows via %s/espn_id "
                "-- their stats and their game logs are on different people"
                % (split, column))
        elif espn and not both:
            problems.append(
                "%s and espn_id are both populated and NO row carries both -- "
                "no crosswalk exists, so the next ingest keyed on the other id "
                "builds a second population instead of enriching this one"
                % column)

    if not espn:
        # Not a defect by itself -- a single-publisher league is a real choice.
        # But it is the reason a league cannot have what only the other
        # publisher prints, so it is reported rather than passed over.
        out.add(UNVERIFIED, league, "F/identity-crosswalk",
                "single publisher (%s): no espn_id on any row, so anything only "
                "ESPN publishes cannot reach this league" % ", ".join(notes))
        return
    if problems:
        out.add(FAIL, league, "F/identity-crosswalk", " | ".join(problems))
    else:
        out.add(PASS, league, "F/identity-crosswalk",
                "publishers cross-referenced (%s)" % ", ".join(notes))


def check_published_identity(con, league, spec, out):
    """G. Does each external id point at the person whose name is on the row?

    Check F asks whether a publisher can REACH a league. This asks whether the
    id it reaches by is the right one. They are different questions and F passing
    says nothing about G.

    Nothing asserted this until 2026-08-04, when **224 MLB rows were found
    carrying another player's `mlbam_id`**:

        id=26571 row='Mason Miller'  mlbam=702616  MLB publishes 'Jackson Holliday'
        id=26573 row='Yennier Cano'  mlbam=701538  MLB publishes 'Jackson Merrill'

    A wrong id here does not raise, it mis-joins -- and it silently converts
    every id-keyed repair into a corruption. `dedupe_mlb.py` calls a shared
    `mlbam_id` "provably the same person"; on that data 124 of 317 duplicate
    groups were two different people, and merging them would have repointed
    408,610 prop rows onto the wrong players. Only a UNIQUE constraint stopped it.

    The corruption predates every retained backup, so no root cause was
    identifiable. This check therefore asserts the STATE rather than the cause:
    it goes green when the spine is repaired and red again the moment anything
    reintroduces a bad pairing, whatever writes it.

    Comparison is diacritic- and suffix-insensitive on purpose. MLB publishes
    'Jeremy Peña' and 'Nasim Nuñez'; a naive comparison reports 25 false
    positives, which is how a real signal gets dismissed as noise. What it must
    NOT tolerate is a different person.
    """
    published = _published_identity_names(league)
    if not published:
        out.add(UNVERIFIED, league, "G/published-identity",
                "no publisher id->name map fetched for this league -- run "
                "fetch_identity_names.py; an unchecked id is not a correct id")
        return

    id_column, names = published["id_column"], published["names"]
    if id_column not in _columns(con, "players"):
        out.add(UNVERIFIED, league, "G/published-identity",
                f"players carries no {id_column} to check")
        return

    checked = wrong = 0
    examples = []
    for row_id, name, ext in con.execute(
            f"SELECT id, name, {id_column} FROM players "
            f"WHERE league=? AND {id_column} IS NOT NULL AND {id_column} != 0", (league,)):
        truth = names.get(str(ext))
        if truth is None:
            # The publisher does not list this id for the fetched season. That is
            # a retired or unlisted player, not evidence of a wrong pairing.
            continue
        checked += 1
        if _identity_name_key(truth) != _identity_name_key(name):
            wrong += 1
            if len(examples) < 3:
                examples.append(f"id={row_id} '{name}' has {id_column}={ext} "
                                f"which publishes as '{truth}'")

    if not checked:
        out.add(UNVERIFIED, league, "G/published-identity",
                f"no row's {id_column} appears in the published map -- "
                "the map and the spine may be different seasons")
    elif wrong:
        out.add(FAIL, league, "G/published-identity",
                f"{wrong} of {checked} rows carry an {id_column} belonging to a "
                f"different player: {'; '.join(examples)}")
    else:
        out.add(PASS, league, "G/published-identity",
                f"all {checked} checked {id_column}s carry the published name")


def check_injury_population(con, league, spec, out):
    """H. The NFL pool's injury fields are populated, not just present.

    On 2026-08-04 the production draft pool served 4,508 players with
    `injury_status` set on 0 of them for ~18 hours -- the API returned the
    keys, always null, no error, no empty state. A check that asks whether the
    column exists cannot catch a column that exists and carries nothing.

    Measures the share of the draft POOL (the nfl_adp rows the board actually
    renders) carrying a non-empty injury_status / last_news_date, against the
    floor declared in the manifest. Only a league with a fantasy pool declares
    this (nfl); leagues that never had the check do not skip -- they never had
    it.
    """
    cfg = spec.get("injury_population")
    if not cfg:
        return
    floor = float(cfg.get("floor", 0.35))
    if not {"injury_status", "last_news_date"} <= _columns(con, "players"):
        out.add(FAIL, league, "H/injury-population",
                "players has no injury_status/last_news_date columns")
        return
    if not _columns(con, "nfl_adp"):
        out.add(FAIL, league, "H/injury-population",
                "no nfl_adp table to define the pool population")
        return
    season = con.execute("SELECT MAX(season) FROM nfl_adp").fetchone()[0]
    if season is None:
        out.add(FAIL, league, "H/injury-population", "nfl_adp has no rows")
        return
    total, with_status, with_news = con.execute(
        """SELECT COUNT(*),
                  SUM(injury_status IS NOT NULL AND TRIM(injury_status) != ''),
                  SUM(last_news_date IS NOT NULL AND TRIM(last_news_date) != '')
             FROM players p JOIN nfl_adp na ON na.player_id = p.id AND na.season = ?
            WHERE p.league = ? AND na.position IN ('QB','RB','WR','TE','PK','DEF')""",
        (season, league),
    ).fetchone()
    total = total or 0
    status_share = (with_status or 0) / total if total else 0.0
    news_share = (with_news or 0) / total if total else 0.0
    detail = ("season %s pool: injury_status %d/%d (%.0f%%), "
              "last_news_date %d/%d (%.0f%%)"
              % (season, with_status or 0, total, 100 * status_share,
                 with_news or 0, total, 100 * news_share))
    if status_share < floor or news_share < floor:
        out.add(FAIL, league, "H/injury-population",
                detail + " -- below the %.0f%% floor" % (100 * floor))
    else:
        out.add(PASS, league, "H/injury-population", detail)


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


if __name__ == "__main__":
    sys.exit(main())
