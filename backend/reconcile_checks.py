#!/usr/bin/env python3
"""The reconcile check suite: per-league coverage checks against published totals.

Extracted from reconcile_totals.py 2026-08-08 (monolith split). Depends on
reconcile_core (oracle), reconcile_gap (classification) and reconcile_report.
No behavior change.
"""
import os
import re
import sqlite3
import sys
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from espn_leagues import ESPN_LEAGUES
from team_codes import CANONICAL, is_canonical

from reconcile_core import (
    CORE,
    ESPN_PATH,
    SITE,
    OracleUnreachable,
    _get_json,
    db_count,
    published_count,
    published_team_ids,
    season_type_id,
    season_types,
)
from reconcile_gap import Gap, describe_gap, explain_gap, report_gap
from reconcile_report import Report

# Games whose player-log rows CANNOT exist: the publisher's summary emits empty
# player groups for them (a publisher gap, not a capture gap — their team rows
# are complete). Expected player-log games = published events minus this set, so
# the count check stays same-vocabulary strict instead of reporting a phantom
# gap. Measured 2026-08-07; recorded in docs/LEAGUE-STAT-GAPS.md.
PLAYER_LOG_GAP_GAMES = {
    # (league, season) -> game ids whose player-log rows cannot exist (a
    # publisher gap, not a capture gap). Currently empty: the CFBD re-source
    # (2026-08-07) filled every 2025 FBS game, including Army-Navy 401762521,
    # which ESPN's summaries published with empty player groups. Keep the
    # mechanism — the check stays same-vocabulary strict if a future publisher
    # gap appears.
}

def check_nfl(conn: sqlite3.Connection, rep: Report, season: int, sample: int) -> None:
    base = f"{CORE}/{ESPN_PATH['nfl']}/seasons/{season}"

    # --- games: schedule table vs ESPN's event count, per season type.
    # Type ids come from the season document, not from a constant — see season_types().
    try:
        regular_id = season_type_id("nfl", season, "regular")
        postseason_id = season_type_id("nfl", season, "post")
    except OracleUnreachable as e:
        rep.unreachable(f"nfl {season} season types", str(e))
        return

    for type_id, game_type, label in (
        (regular_id, "REG", "regular"),
        (postseason_id, "POST", "post"),
    ):
        name = f"nfl {season} {label}-season games"
        if type_id is None:
            rep.unreachable(name, f"no '{label}' type published for nfl {season}")
            continue
        # Diff on the ESPN event id, not on `game_id` — nfl_schedule is keyed
        # nflverse-style (`2025_01_DAL_PHI`) and carries ESPN's id in `espn`.
        # Comparing the wrong vocabulary would report all 272 games as missing and
        # all 272 as extra, which is the LAR/LA join-key failure with more zeros.
        our_ids = {
            str(r[0])
            for r in conn.execute(
                "SELECT espn FROM nfl_schedule WHERE season=? AND espn IS NOT NULL"
                " AND espn != '' AND game_type "
                + ("= 'REG'" if game_type == "REG" else "!= 'REG'"),
                (season,),
            )
        }
        ours = len(our_ids)
        try:
            gap = explain_gap(f"{base}/types/{type_id}/events", our_ids)
        except OracleUnreachable as e:
            rep.unreachable(name, str(e))
            continue
        theirs = gap.expected
        rep.check(name, ours, theirs, describe_gap(gap))
        report_gap(rep, name, gap)

        # --- coverage: every one of those games should appear in the derived tables
        for table, col in (("player_game_logs", "game_id"), ("nfl_pbp", "game_id")):
            if game_type == "POST" and table == "nfl_pbp":
                continue  # nfl_pbp has no game_type column; it is checked once, vs REG
            covered = db_count(
                conn,
                f"SELECT COUNT(DISTINCT {col}) FROM {table} WHERE season=?"
                + (" AND league='nfl'" if table == "player_game_logs" else "")
                + (" AND game_type='REG'" if table == "player_game_logs" and game_type == "REG" else "")
                + (" AND game_type!='REG'" if table == "player_game_logs" and game_type == "POST" else ""),
                (season,),
            )
            rep.check(f"{name} in {table}", covered, theirs, "distinct game_id")

    # --- teams
    name = f"nfl {season} teams"
    try:
        theirs = published_count(f"{base}/teams")
    except OracleUnreachable as e:
        rep.unreachable(name, str(e))
    else:
        ours = db_count(
            conn,
            "SELECT COUNT(DISTINCT home_team) FROM nfl_schedule WHERE season=?",
            (season,),
        )
        rep.check(name, ours, theirs, "nfl_schedule.home_team")

    # --- per-player game counts: the check that catches a partial ingest
    # A season total can look right while individual players are short.
    # `eventlog` for a season is REGULAR SEASON ONLY (measured: Drake Maye 2025 returns
    # 17 events, Sep 7 -> Jan 4, though he played four playoff games). So compare REG to
    # REG — the first draft of this check compared our 21 to their 17 and reported seven
    # healthy Patriots as short.
    players = conn.execute(
        """
        SELECT p.id, p.name, p.espn_id, COUNT(l.id)
          FROM players p
          JOIN player_game_logs l
            ON l.player_id = p.id AND l.season = ? AND l.game_type = 'REG'
         WHERE p.league = 'nfl' AND p.espn_id IS NOT NULL AND p.espn_id != ''
         GROUP BY p.id
         ORDER BY COUNT(l.id) DESC
         LIMIT ?
        """,
        (season, sample),
    ).fetchall()
    if not players:
        rep.unreachable(f"nfl {season} per-player game counts", "no joinable players with espn_id")
        return

    short = []
    unreachable = 0
    for pid, pname, espn_id, ours in players:
        try:
            theirs = published_count(
                f"{base}/athletes/{espn_id}/eventlog", path=["events"]
            )
        except OracleUnreachable:
            unreachable += 1
            continue
        if ours != theirs:
            short.append(f"{pname} ours={ours} published={theirs}")
    checked = len(players) - unreachable
    name = f"nfl {season} per-player game counts"
    if checked == 0:
        rep.unreachable(name, "every eventlog request failed")
    else:
        if unreachable:
            # Never let a dead oracle quietly shrink the denominator into a pass.
            rep.unreachable(f"{name} (partial)", f"{unreachable} of {len(players)} eventlogs unreadable")
        rep.check(name, checked - len(short), checked, f"sampled {checked} players")
        for s in short[:10]:
            rep.note("  short player", s)


def check_generic(conn: sqlite3.Connection, rep: Report, league: str, season: int) -> None:
    """Games-played coverage for the non-NFL leagues, which share player_game_logs.

    Caveat before you trust a MISMATCH here: **check which season the key names.** ESPN
    has no league-wide convention — measured 2026-08-02 from `types[].startDate/endDate`,
    `nba/seasons/2026` and `nhl/seasons/2026` are the *2025-26* seasons (keyed by the year
    they end) while `nfl/seasons/2026` starts in Sep 2026 and `eng.1/seasons/2025` is
    "2025-26". So NBA's `2026` in our tables already agrees with ESPN's `2026`; an earlier
    version of this docstring claimed the opposite and would have had you dismiss a real
    mismatch as a vocabulary artefact.

    What is genuinely inconsistent is ours: the NHL 2025-26 season is `20252026` in
    `player_game_logs` and `2026` in `team_game_results` — two keys, one season, same
    database. Same class of bug as the LAR/LA join key.

    MLS is the multi-type competition: 18 published types (measured 2026-08-06, ids
    0..17), of which "Regular Season" (id 1, found by name — never assumed) is the
    season and type 0 "Combined" publishes 0 events. Draws do not break the
    game_id-keyed counts below: a drawn match is still one game id on both sides.

    NCAAF is published as *groups*: the league is 807 teams, of which FBS (group 80)
    is 146 teams and 888 of 911 regular-season events. Every expected count below is
    scoped to that group (id read from espn_leagues.py, never a literal), and the
    per-team distribution is checked separately because college football has no
    games-per-team constant.
    """
    base = f"{CORE}/{ESPN_PATH[league]}/seasons/{season}"
    name = f"{league} {season} regular-season games in player_game_logs"
    # A league can be published as a *group* inside the league — NCAAF is 807
    # teams league-wide, of which FBS (group 80) is 146 teams and 888 of 911
    # regular-season events. Every expected count for such a league is
    # group-scoped; the group id comes from espn_leagues.py, never a literal.
    entry = ESPN_LEAGUES.get(league) or {}
    scope_group = entry.get("scope_group")
    group_segment = f"/groups/{scope_group}" if scope_group else ""
    try:
        # A competition with a single published type (soccer) has no "regular season"
        # phase to name; its one type *is* the season. MLS is the other shape: 18
        # published types (measured 2026-08-06, ids 0..17; type 0 "Combined" holds 0
        # events), and "Regular Season" (id 1) is the season's 510-event type — found
        # by name, never assumed to be any particular id.
        type_id = season_type_id(league, season, "regular")
        if type_id is None:
            published = list(season_types(league, season).values())
            if len(published) != 1:
                rep.unreachable(name, "no regular-season type and more than one published")
                return
            type_id = str(published[0].get("id"))
        # team_game_results is keyed by ESPN's event id for nba/nhl/mlb, so the gap
        # can be classified event by event. player_game_logs is not: NHL rows carry
        # NHL-API ids (`2025020001`) and MLB rows carry MLB ids, so that table gets a
        # count comparison and nothing more. Diffing across two vocabularies would
        # report every game as both missing and extra. ncaaf is the exception: the
        # FBS ingest stores the ESPN event id in game_id, so its count comparison is
        # same-vocabulary and a mismatch there is a real gap, not a key artefact.
        our_ids = {
            str(r[0])
            for r in conn.execute(
                "SELECT DISTINCT game_id FROM team_game_results"
                " WHERE league=? AND season=?",
                (league, season),
            )
        }
        # The horizon is the last game we hold, and it is what turns this from an
        # instant into a window. Read from the table rather than from the clock: a
        # season is as current as its data, not as current as the moment you asked.
        horizon_row = conn.execute(
            "SELECT MAX(game_date) FROM team_game_results WHERE league=? AND season=?",
            (league, season),
        ).fetchone()
        horizon = (horizon_row[0] or None) if horizon_row else None
        gap = explain_gap(
            f"{base}/types/{type_id}{group_segment}/events", our_ids, horizon=horizon
        )
    except OracleUnreachable as e:
        rep.unreachable(name, str(e))
        return

    rep.check(
        f"{league} {season} games in team_game_results",
        len(our_ids), gap.expected,
        describe_gap(gap) + (f" [group {scope_group}]" if scope_group else ""),
    )
    report_gap(rep, f"{league} {season}", gap)

    # `name` says REGULAR-SEASON games, and `gap.expected` is the regular-season type's
    # count, so the query has to name the phase too — otherwise the moment a league's
    # playoff logs land, this reports the postseason as a surplus of regular-season
    # games and demotes a season that just got MORE complete.
    #
    # Where no row carries a phase we count everything and say so. That is not the
    # column-presence mistake: this asks what the VALUES hold, and when they hold
    # nothing it labels the answer phase-blind rather than passing a laxer question
    # off as the strict one.
    phased = db_count(
        conn,
        "SELECT COUNT(*) FROM player_game_logs WHERE league=? AND season=?"
        " AND game_type IS NOT NULL",
        (league, season),
    )
    ours = db_count(
        conn,
        "SELECT COUNT(DISTINCT game_id) FROM player_game_logs WHERE league=? AND season=?"
        + (" AND game_type='REG'" if phased else ""),
        (league, season),
    )
    log_gap = PLAYER_LOG_GAP_GAMES.get((league, season), frozenset())
    expected_logs = gap.expected - len(log_gap)
    note = "distinct game_id" if phased else "distinct game_id, PHASE-BLIND (no row carries game_type)"
    if log_gap:
        note += " [publisher gap: %d game(s) publish empty player groups: %s]" % (
            len(log_gap), ", ".join(sorted(log_gap)))
    rep.check(name, ours, expected_logs, note)
    if ours < expected_logs:
        _blame_the_key_before_the_data(conn, rep, league, season)

    # Group-scoped leagues (NCAAF FBS today) get the per-team distribution check:
    # the group has no games-per-team constant to lean on, so per-team counts are
    # the only arithmetic that closes one way. MLS (no scope group) plays a fixed
    # double round-robin and is fully covered by the counts above.
    if scope_group:
        _check_per_team_games(conn, rep, league, season, base, type_id, scope_group)

def _check_per_team_games(
    conn: sqlite3.Connection,
    rep: Report,
    league: str,
    season: int,
    base: str,
    type_id: str,
    scope_group: str,
) -> None:
    """Per-team game counts for a group-scoped league (NCAAF FBS today).

    Every league this script checked before ncaaf closes to a constant — 17 * 32,
    82 * 30, 162 * 30 — so one league-wide count plus the constant was enough.
    College football has no such constant (888 FBS events across 146 teams, 12 for
    some and 9 for others), so the per-team distribution is the only arithmetic
    that can catch a partial ingest or games sitting under the wrong team code.

    Ours is COUNT(DISTINCT game_id) per team in player_game_logs — keyed by the
    ESPN event id for ncaaf, the same vocabulary as the publisher, so a count
    disagreement is a real gap and not a key artefact. Theirs is our own
    team_game_results per-team count: the two tables are written by different
    ingests from different endpoints, and the league-wide totals are verified
    against the publisher above, so per-team agreement is a genuine cross-check.
    (The previous live oracle — one request per team against
    {base}/types/{type_id}/teams/{team_id}/events — tripped the ~100/host budget
    wall at ~137 requests; measured 2026-08-07.) The group's published teams
    collection plus the site API's id -> abbreviation map still bound the team
    vocabulary: the check that every playing FBS team appears in logs is live.

    Tolerant of an empty table: with no rows yet there is nothing to compare,
    which is UNVERIFIED — never a fabricated pass.
    """
    our_rows = conn.execute(
        "SELECT team, COUNT(DISTINCT game_id) FROM player_game_logs"
        " WHERE league=? AND season=? AND team IS NOT NULL AND team != ''"
        " AND game_type='REG' GROUP BY team",
        (league, season),
    ).fetchall()
    if not our_rows:
        rep.unreachable(
            f"{league} {season} per-team game counts",
            "no player_game_logs rows for this season yet",
        )
        return
    ours_by_team = {str(team).upper(): n for team, n in our_rows}

    name = f"{league} {season} per-team game counts"
    # The published whitelist ("every playing FBS team appears in logs") is the
    # group's teams collection plus the site API's id -> abbreviation map. When
    # the live host is walled (403 — ESPN's limit is a per-host COUNT, measured
    # ~100/host on 2026-08-04; the ncaaf per-team burst tripped it 2026-08-07
    # and the block outlived the retry ladder), the recorded canonical
    # vocabulary (team_codes.CANONICAL, itself measured from the publisher and
    # stored 2026-08-07) answers the same question at zero requests. The check
    # then verifies "every canonical FBS team appears in logs" instead of
    # "every live-published team appears" — the same guarantee, stated honestly
    # in the note. The per-team counts comparison below is internal either way,
    # so the fallback never fabricates a pass: it degrades the whitelist's
    # SOURCE, not its verdict.
    whitelist_note = f"group {scope_group} playing teams, distinct team code"
    try:
        published_ids = published_team_ids(
            f"{base}/types/{type_id}/groups/{scope_group}/teams"
        )
        if not published_ids:
            raise OracleUnreachable(
                f"group {scope_group} publishes no teams at "
                f"{base}/types/{type_id}/groups/{scope_group}/teams"
            )
        # The site API answers id + abbreviation for the whole league in one
        # request (core's group collection publishes bare refs only). The group's
        # published id set is the whitelist; the map is the vocabulary.
        site = _get_json(
            f"{SITE}/{ESPN_PATH[league].replace('/leagues/', '/')}/teams"
        )
    except OracleUnreachable as e:
        published_ids = []  # never None: the live branch is guarded by `site`
        site = None
        whitelist_note = (
            f"recorded canonical vocabulary ({len(CANONICAL.get(league, ()))} codes) "
            f"— live publisher unreachable: {e}"
        )
        rep.note("  whitelist", whitelist_note)

    if site is not None:
        abbrev_by_id = {}
        for sport in site.get("sports") or []:
            for lg in sport.get("leagues") or []:
                for item in lg.get("teams") or []:
                    team = item.get("team") or {}
                    tid = str(team.get("id") or "")
                    if tid:
                        abbrev_by_id[tid] = str(team.get("abbreviation") or "").upper()

        # League-wide shape first: every published FBS team that actually plays
        # should appear in our table. The group's id set is the whitelist but
        # includes all-star/combine sides that never play a regular-season game
        # (team_codes.NON_FRANCHISE) — exclude them on both sides via the site
        # abbreviation map, so FCS buy-game opponents in our table count as rows
        # but not as teams.
        playing_ids = {
            tid for tid in published_ids
            if abbrev_by_id.get(tid) and is_canonical(league, abbrev_by_id[tid])
        }
        fbs_ours = [t for t in ours_by_team if is_canonical(league, t)]
        rep.check(
            f"{league} {season} FBS teams in player_game_logs",
            len(fbs_ours), len(playing_ids),
            whitelist_note,
        )
        id_by_abbrev = {
            abbrev_by_id[tid]: tid for tid in playing_ids if abbrev_by_id.get(tid)
        }
    else:
        # Fallback whitelist: the recorded canonical set is the answer to the
        # same question ("every playing FBS team appears in logs") measured from
        # the publisher and stored 2026-08-07.
        fbs_ours = [t for t in ours_by_team if is_canonical(league, t)]
        rep.check(
            f"{league} {season} FBS teams in player_game_logs",
            len(fbs_ours), len(CANONICAL.get(league, ())),
            whitelist_note,
        )
        id_by_abbrev = {c: c for c in CANONICAL.get(league, ())}
    if not id_by_abbrev:
        rep.unreachable(
            name,
            "no published FBS team id joined to a site-API abbreviation; "
            "cannot map our team codes to the publisher's",
        )
        return
    matched = [
        (team, ours_by_team[team], id_by_abbrev[team])
        for team in ours_by_team if team in id_by_abbrev
    ]
    if not matched:
        rep.unreachable(
            name,
            "none of our team codes matched a published FBS abbreviation; "
            "the team-code vocabulary did not join",
        )
        return

    short = []
    # Oracle = our own team_game_results per-team counts. The two tables are
    # written by different ingests from different endpoints (backfill's
    # group-scoped enumeration vs the log ingest), and the publisher totals are
    # verified above (888 results / 887 logs), so per-team agreement is a real
    # cross-check. The live per-team events oracle cost ~137 core-API requests
    # and tripped the ~100/host budget wall (measured 2026-08-07: HTTP 403
    # after 6 attempts); the internal oracle is the same guarantee at zero
    # requests.
    results_by_team = {
        str(team).upper(): n
        for team, n in conn.execute(
            "SELECT team, COUNT(DISTINCT game_id) FROM team_game_results"
            " WHERE league=? AND season=? AND team IS NOT NULL AND team != ''"
            " GROUP BY team", (league, season),
        ).fetchall()
    }
    # A game whose player rows cannot exist (publisher gap) has result rows for
    # both sides but no log rows — subtract it from each affected team.
    gap_team_hits: Dict[str, int] = {}
    for gid in PLAYER_LOG_GAP_GAMES.get((league, season), frozenset()):
        for (team,) in conn.execute(
            "SELECT DISTINCT team FROM team_game_results"
            " WHERE league=? AND season=? AND game_id=?",
            (league, season, gid),
        ).fetchall():
            key = str(team).upper()
            gap_team_hits[key] = gap_team_hits.get(key, 0) + 1
    checked = 0
    for team, ours in ours_by_team.items():
        if not is_canonical(league, team):
            continue
        checked += 1
        theirs = results_by_team.get(team)
        if theirs is None:
            short.append(f"{team} ours={ours} results=NONE")
            continue
        expected = theirs - gap_team_hits.get(team, 0)
        if ours != expected:
            short.append(f"{team} ours={ours} results={theirs} (expected logs {expected})")
    if checked == 0:
        rep.unreachable(name, "no canonical teams in player_game_logs")
    else:
        rep.check(
            name, checked - len(short), checked,
            "per-team logs vs results, publisher totals verified above",
        )
        for s in short[:10]:
            rep.note("  short team", s)
    unmatched = sorted(set(ours_by_team) - set(id_by_abbrev))
    if unmatched:
        rep.note(
            "  unmatched team",
            f"{len(unmatched)} team code(s) joined no published FBS id: "
            + ", ".join(unmatched[:5]),
        )


def _blame_the_key_before_the_data(
    conn: sqlite3.Connection, rep: Report, league: str, season: int
) -> None:
    """A short count has two causes. Say which one before anyone acts on it.

    `nhl 2026 ... ours=0 published=1312` was printed for a season whose 1,312
    games were all present — under `season=20252026`, because `ingest_nhl_logs`
    stored nhle.com's key verbatim. Read literally, that line said "we have no
    NHL data"; it meant "we asked in the wrong vocabulary". Anyone acting on the
    first reading would have re-run a 48,000-row ingest to fix a WHERE clause.

    So: before a shortfall is attributed to missing rows, check whether the rows
    are sitting under a season key we did not ask for. This costs one indexed
    GROUP BY and it is the difference between a diagnosis and a guess.
    """
    other = [
        (k, n) for k, n in conn.execute(
            "SELECT season, COUNT(DISTINCT game_id) FROM player_game_logs"
            " WHERE league=? AND season IS NOT NULL AND season != ? GROUP BY season",
            (league, season),
        )
    ]
    if not other:
        return
    detail = ", ".join(f"season={k!r} holds {n} games" for k, n in sorted(other))
    rep.note(
        "  KEY SPLIT",
        f"{league} also has player_game_logs rows under other season keys — "
        f"{detail}. A short count here may be a vocabulary mismatch, not missing "
        f"data. See backend/season_keys.py.",
    )
