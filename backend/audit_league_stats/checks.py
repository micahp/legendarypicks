"""checks — league stats audit checks layer."""
import json
import os
import re
import sqlite3
import sys
import unicodedata
import argparse
import name_aliases

import json
import sqlite3
import name_aliases
from .identity import (_columns, _declares_group_column, _identity_name_key, _observed_positions, _position_vocabulary, _published_identity_names)  # noqa: E402

PASS, FAIL, UNVERIFIED = "PASS", "FAIL", "UNVERIFIED"

_POSITION_CONTENT_FLOOR = 0.8

def check_required_stats(con, league, spec, out):
    """A. The column exists AND carries values for enough of this league.

    This measured PRESENCE, not COVERAGE: `if not filled` fails only at exactly
    zero, so ONE populated row out of thousands passed. Measured 2026-08-05 on
    prod, both MLB stat types read PASS while half the league had nothing:

        batting   767 of 1451 rows (52%) had no counting stats at all
        pitching  339 of 1108 rows (30%)

    Both `pa` and `era` are "present and populated" by the old test and absent
    for most players, which is the same defect check B carried until it was
    rewritten to filled/sampled. A column that exists for a minority of the
    league is not a column the product can query.

    The floor is deliberately loose (50%): a stat legitimately absent for a
    whole class of player -- a pitcher has no batting average -- must not read
    red. It is a tripwire for "half the league is missing", not a completeness
    target. A league needing a different floor declares `min_coverage` in its
    MANIFEST stat_type entry.
    """
    columns = _columns(con, "player_stats")
    if not columns:
        out.add(FAIL, league, "A/required-stats", "player_stats is unreadable")
        return
    for stat_type, cfg in spec["stat_types"].items():
        # Coverage is asserted PER COLUMN and only where the manifest says so.
        # A flat floor across every required stat cannot work: `saves` is 78 of
        # 874 NHL rows and `pass_yds_g` is 81 of 608 NFL rows because only
        # goalies make saves and only quarterbacks throw. Those are correct at
        # 9% and 13%. The number that is wrong is MLB's `pa` at 47%, and the
        # only thing that distinguishes them is a human saying which stats every
        # row of a stat_type should carry. So they say it, per column, in
        # `coverage`; anything undeclared keeps the old must-be-non-zero test.
        coverage = cfg.get("coverage") or {}
        total = con.execute(
            "SELECT COUNT(*) FROM player_stats WHERE league=? AND stat_type=?",
            (league, stat_type)).fetchone()[0]
        missing, empty, thin = [], [], []
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
                continue
            floor = coverage.get(column)
            if floor is not None and total and filled / total < floor:
                thin.append(f"{column} {filled}/{total} ({filled / total:.0%}, "
                            f"floor {floor:.0%})")
        if missing or empty or thin:
            parts = []
            if missing:
                parts.append("no such column: " + ", ".join(missing))
            if empty:
                parts.append("column exists but 0 rows populated: " + ", ".join(empty))
            if thin:
                parts.append(f"below the {floor:.0%} coverage floor: " + ", ".join(thin))
            out.add(FAIL, league, f"A/required-stats[{stat_type}]", "; ".join(parts))
        else:
            declared = ", ".join(f"{c} >={f:.0%}" for c, f in sorted(coverage.items()))
            out.add(PASS, league, f"A/required-stats[{stat_type}]",
                    "%d required stats present and populated over %d rows%s"
                    % (len(cfg["required"]), total,
                       f"; coverage asserted: {declared}" if declared else ""))

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
            # A league with ONE class and no position column (UFC fighters,
            # WC footballers) declares that class across every log rather than
            # per position. all_logs=True samples the whole league, so the
            # declaration is measurable instead of forever UNVERIFIED by a
            # position join that can never match.
            all_logs = bool(entry.get("all_logs", False))
        else:
            keys = entry
            floor = _POSITION_CONTENT_FLOOR
            all_logs = False
        if all_logs:
            rows = con.execute(
                "SELECT l.stats FROM player_game_logs l "
                "JOIN players p ON p.id = l.player_id "
                "WHERE l.league=? LIMIT 500", (league,)).fetchall()
        else:
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
        # `key_coverage` (dict form only) overrides the floor per stat: a stat
        # the publisher only emits when it happened (CFBD omits the
        # interceptions category entirely when no INT was recorded) is honest
        # at a low presence rate, while the position's always-published stats
        # keep the strict floor. Absence of an override keeps the entry floor.
        key_coverage = entry.get("key_coverage") or {} if isinstance(entry, dict) else {}
        floors = [key_coverage.get(alts[0], floor) for alts in keys]
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
        low = [c for i, c in enumerate(counts) if filled[i] < floors[i] * sampled]
        if low:
            out.add(FAIL, league, f"B/position-content[{position}]",
                    "%d logs sampled, below the declared floor: %s"
                    % (sampled, "; ".join(low)))
        else:
            out.add(PASS, league, f"B/position-content[{position}]",
                    "%d logs sampled, all recorded at >=%.0f%%: %s"
                    % (sampled, 100 * min(floors), ", ".join(counts)))

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
        # Same for `position_group`: a team defence has no position and no
        # group, and entity_type is how the two populations stay distinct.
        entity_scope = ""
        if column in ("position", "position_group") and "entity_type" in _columns(con, "players"):
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
    # A league whose manifest declares no stat_types has no leaderboard surface
    # to serve (UFC is fighters + rankings; WC is dormant until 2030) -- D has
    # nothing to measure, and a FAIL here would assert a defect in a surface
    # that does not exist. The manifest's "nothing to declare, said out loud"
    # is the contract; honor it rather than contradicting it.
    if not spec.get("stat_types"):
        out.add(UNVERIFIED, league, "D/leaders-reach-logs",
                "no stat_types declared -- this league has no leaderboard "
                "surface to serve (rankings/dormant, not a stats league)")
        return
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
            # Strict comparison failed. Before reporting a wrong person, ask
            # whether this id has a recorded accepted alternate spelling
            # (data/name-aliases.json). The decision (2026-08-05): the
            # market-facing nickname is canonical on the row -- ESPN fantasy
            # and Yahoo both publish 'Kenny Gainwell' -- and the publisher's
            # legal-form spelling is a same-person alias, never a different
            # person. An id absent from the alias file has no alternates.
            if name_aliases.matches_published(league, ext, name, truth):
                continue
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
