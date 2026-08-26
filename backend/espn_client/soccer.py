"""espn_client.soccer -- summary-based reads and soccer/college standings.

`summary` is the shared cached fetch behind boxscore, lineups, match_events,
game_result and game_result_soccer -- one fetch serves all callers via the
in-memory _CACHE. This module also carries the World Cup knockout bracket
contract (`wc_knockout_standings` / `wc_is_knockout`), the MLS and NCAAF
conference standings, and the finality-aware `game_result`.

Shared calls (`_check`, `_get`, `_num`, `_int`, `_iso`) and the summary-based
public functions resolve through the `espn_client` package at call time so
monkeypatching `espn_client._get` / `espn_client.summary` (as the test suite
does) keeps working.
"""
import re

import espn_client


def summary(league, game_id):
    """Cached raw ESPN /summary JSON for one game. TTL 20s.
    Shared by boxscore, play-by-play, lineups, match_events, and game_result.
    One fetch serves all callers — the second and subsequent hits come from the in-memory
    _CACHE without an extra HTTP round-trip."""
    _, path = espn_client._check(league)
    return espn_client._get(espn_client._SITE.format(path=path) + f"/summary?event={game_id}", ttl=20)


def game_result_soccer(league, game_id):
    """Soccer-specific game result — uses competitor.winner flag (penalty/AET aware)."""
    d = espn_client.summary(league, game_id)
    comp = (d.get("header", {}).get("competitions") or [{}])[0]
    status = comp.get("status", {})
    st = status.get("type", {})
    scores = {}
    winner = home_abbr = away_abbr = None
    for c in comp.get("competitors", []):
        abbr = c.get("team", {}).get("abbreviation")
        scores[abbr] = espn_client._num(c.get("score"))
        if c.get("homeAway") == "home":
            home_abbr = abbr
        elif c.get("homeAway") == "away":
            away_abbr = abbr
        if c.get("winner") is True:
            winner = abbr
    # See game_result: a postponed match is state="post" too. `completed` is the
    # published answer to "was this played to a result".
    completed = bool(st.get("completed"))
    if not completed:
        winner = None
    return {
        "state": st.get("state"),
        "completed": completed,
        "scores": scores,
        "home": home_abbr,
        "away": away_abbr,
        "home_score": scores.get(home_abbr),
        "away_score": scores.get(away_abbr),
        "winner": winner,
        "period": status.get("period"),
        "clock": status.get("displayClock"),
        "status_detail": st.get("shortDetail"),
    }


def lineups(league, game_id):
    """Starting XI + formation for a soccer match. [{side: 'home'|'away', formation, players: [{jersey, name, position}]}]"""
    d = espn_client.summary(league, game_id)
    result = []
    for roster in d.get("rosters", []):
        side = "home" if roster.get("homeAway") == "home" else "away"
        formation = roster.get("formation", "")
        players = []
        for p in roster.get("roster", []):
            ath = p.get("athlete", {})
            players.append({
                "jersey": p.get("jersey"),
                "name": ath.get("displayName") or ath.get("fullName"),
                "position": p.get("position", ""),
                "starter": p.get("starter", False),
            })
        result.append({"side": side, "formation": formation, "players": players})
    return result


# ── Canonical World Cup knockout contract ─────────────────────────────────
# One shape, used by BOTH /api/wc/standings (during knockouts) and
# /api/wc/knockout. Each round: {round, matches:[M]}. Each match M:
#   {game_id, date, home:{abbrev,name}, away:{abbrev,name},
#    homeScore, awayScore, winner, status, state}
# §10: ESPN team/score fields are OBJECTS — extract .abbreviation/.displayName
#      and .displayValue before returning. Never ship raw ESPN objects.
_WC_ROUND_MAP = {
    "round-of-32": "Round of 32",
    "round-of-16": "Round of 16",
    "quarterfinals": "Quarterfinals",
    "semifinals": "Semifinals",
    "3rd-place-match": "Third Place",
    "final": "Final",
}
_WC_ROUND_ORDER = [
    "Round of 32", "Round of 16", "Quarterfinals",
    "Semifinals", "Third Place", "Final",
]


def _wc_round_from_event(e):
    """Determine the knockout round name from event.season.slug (canonical),
    falling back to competition.altGameNote text parsing."""
    slug = ((e.get("season") or {}).get("slug") or "").lower()
    if slug in _WC_ROUND_MAP:
        return _WC_ROUND_MAP[slug]
    # Fallback: altGameNote like "FIFA World Cup, Round of 32"
    note = ((e.get("competitions") or [{}])[0].get("altGameNote") or "")
    for key, label in _WC_ROUND_MAP.items():
        if label.lower() in note.lower():
            return label
    return "Knockout"


def _wc_competitor(c):
    """Extract {abbrev, name} + numeric score + winner flag from one ESPN
    competitor entry (objects → strings/ints per §10)."""
    t = c.get("team", {}) or {}
    abbrev = t.get("abbreviation")
    name = t.get("displayName") or t.get("name") or abbrev or ""
    score_raw = c.get("score")
    if isinstance(score_raw, dict):
        score_val = score_raw.get("displayValue")
        if score_val is None:
            score_val = score_raw.get("value")
    else:
        score_val = score_raw
    try:
        score = int(score_val) if score_val not in (None, "") else None
    except (TypeError, ValueError):
        score = None
    return {
        "abbrev": abbrev,
        "name": name,
        "score": score,
        "winner": bool(c.get("winner") is True),
    }


def wc_knockout_standings():
    """World Cup knockout bracket/results — the COMPLETE current bracket.

    Future-proof: read leagues[0].calendar[0].entries from the default
    scoreboard, exclude the 'Group' phase, derive the first knockout start
    date and last knockout end date, then issue ONE cached range request
    (?dates=START-END&limit=100). Group matches by event.season.slug into
    the canonical six rounds, dedupe by event id.

    Returns {rounds:[{round, matches:[{game_id, date, home:{abbrev,name},
    away:{abbrev,name}, homeScore, awayScore, winner, status, state}]}]}.

    During the group stage the bracket is empty — callers fall back to
    group tables. See wc_is_knockout() for the gate.
    """
    _, path = espn_client._check("wc")

    # ── 1. Derive the knockout date window from the calendar ──
    d = espn_client._get(espn_client._SITE.format(path=path) + "/scoreboard", ttl=300)
    league_blob = (d.get("leagues") or [{}])[0]
    calendar = league_blob.get("calendar") or [{}]
    entries = (calendar[0].get("entries") if calendar else []) or []
    ko_start = None
    ko_end = None
    for ent in entries:
        if (ent.get("label") or "").lower().startswith("group"):
            continue
        sd = ent.get("startDate")
        ed = ent.get("endDate")
        if sd and (ko_start is None or sd < ko_start):
            ko_start = sd
        if ed and (ko_end is None or ed > ko_end):
            ko_end = ed

    if not ko_start or not ko_end:
        # No knockout window published yet (pre-tournament) — nothing to show.
        return {"rounds": []}

    # ESPN date range format: YYYYMMDD-YYYYMMDD
    def _ymd(iso):
        return iso[:10].replace("-", "")
    rng = f"{_ymd(ko_start)}-{_ymd(ko_end)}"

    # ── 2. One cached range request for the whole bracket ──
    rd = espn_client._get(
        espn_client._SITE.format(path=path) + f"/scoreboard?dates={rng}&limit=100",
        ttl=120,
    )

    # ── 3. Build canonical rounds, dedupe by event id ──
    rounds_map = {}
    seen = set()
    for e in rd.get("events", []):
        eid = e.get("id")
        if eid in seen:
            continue
        seen.add(eid)
        comp = (e.get("competitions") or [{}])[0]
        comp_status = comp.get("status", {}) or {}
        st = comp_status.get("type", {}) or {}
        state = st.get("state") or ""

        home = away = None
        for c in comp.get("competitors", []):
            ci = _wc_competitor(c)
            if c.get("homeAway") == "home":
                home = ci
            else:
                away = ci
        if not home or not away:
            continue

        winner = home["abbrev"] if home["winner"] else (
            away["abbrev"] if away["winner"] else None)

        match = {
            "game_id": eid,
            "date": e.get("date"),
            "home": {"abbrev": home["abbrev"], "name": home["name"]},
            "away": {"abbrev": away["abbrev"], "name": away["name"]},
            "homeScore": home["score"],
            "awayScore": away["score"],
            "winner": winner,
            "status": st.get("name") or st.get("description") or "",
            "state": state,
        }
        rname = _wc_round_from_event(e)
        rounds_map.setdefault(rname, []).append(match)

    # Stable canonical order
    rounds = []
    for rname in _WC_ROUND_ORDER:
        if rname in rounds_map:
            rounds.append({"round": rname, "matches": rounds_map.pop(rname)})
    for rname, match_list in rounds_map.items():  # unknown round names last
        rounds.append({"round": rname, "matches": match_list})

    return {"rounds": rounds}


def wc_is_knockout():
    """True once the current WC league-season phase is NOT 'Group'.

    Reads league.season.type.name from the default scoreboard. While it is
    'Group' (or missing) the group stage is live and the bracket must not be
    served. Used by /api/wc/standings to pick bracket vs group tables.
    """
    _, path = espn_client._check("wc")
    d = espn_client._get(espn_client._SITE.format(path=path) + "/scoreboard", ttl=300)
    league_blob = (d.get("leagues") or [{}])[0]
    stype = (league_blob.get("season") or {}).get("type") or {}
    phase = (stype.get("name") or "") if isinstance(stype, dict) else ""
    return bool(phase) and phase.lower() != "group"


def match_events(league, game_id):
    """Key events + commentary for a soccer match."""
    d = espn_client.summary(league, game_id)
    return {
        "key_events": d.get("keyEvents", []),
        "commentary": d.get("commentary", []),
    }


def boxscore(league, game_id):
    """Full per-game box score (team + player stat lines)."""
    d = espn_client.summary(league, game_id)
    return d.get("boxscore", {})


def roster(league, team):
    """Active roster for a team (by abbreviation or id): [{player_id, name, jersey, position}]."""
    _, path = espn_client._check(league)
    d = espn_client._get(espn_client._SITE.format(path=path) + f"/teams/{team}/roster", ttl=3600)
    out = []
    for a in d.get("athletes", []):
        # NFL/NBA roster nests athletes under position groups; flatten either shape
        items = a.get("items") if isinstance(a, dict) and "items" in a else [a]
        for p in items:
            out.append({
                "player_id": (
                    str(p["id"]) if p.get("id") is not None else None
                ),
                "name": p.get("fullName") or p.get("displayName"),
                "jersey": p.get("jersey"),
                "position": (p.get("position") or {}).get("abbreviation"),
            })
    return out


def game_result(league, game_id):
    """Clean grading info for one game: {state, scores{abbrev:score}, winner|None}.

    Robust to date (queries the game directly), so it grades predictions regardless of when
    the game was played. winner is None until the game is final. Soccer (wc, lcup, mls) uses the
    competitor.winner flag — penalty/AET aware, and the only honest grade for a drawn match:
    the score heuristic below would file an MLS Cup final decided on penalties by the
    90-minute scoreline.
    """
    if league in ("wc", "lcup", "mls"):
        return espn_client.game_result_soccer(league, game_id)
    d = espn_client.summary(league, game_id)
    comp = (d.get("header", {}).get("competitions") or [{}])[0]
    status = comp.get("status", {})
    st = status.get("type", {})
    scores, home_abbr, away_abbr = {}, None, None
    for c in comp.get("competitors", []):
        ab = c.get("team", {}).get("abbreviation")
        scores[ab] = espn_client._num(c.get("score"))
        # ESPN states which side is home on the same object as the score. Read it
        # rather than asking the caller to supply a key: every caller that had to
        # supply one supplied a display name against this abbrev-keyed dict, and
        # `.get("Athletics")` into `{"ATH": 5}` misses silently. See
        # test_game_result_home_away.
        if c.get("homeAway") == "home":
            home_abbr = ab
        elif c.get("homeAway") == "away":
            away_abbr = ab
    # `state == "post"` is not "this game was played". A POSTPONED game is also
    # state="post" — with completed=false and a score of "0" on both sides rather
    # than null — so the old gate admitted one, `max(scores)` on a 0-0 tie handed
    # the win to whichever key sorted first, and settlement stamped final 0-0 on a
    # game nobody played. Measured on event 401815805 (SF at ATL, 2026-06-18).
    # `completed` is published on this same object; see test_finality_gate_completed.
    completed = bool(st.get("completed"))
    winner = None
    if completed and len(scores) == 2 and all(v is not None for v in scores.values()):
        hi, lo = sorted(scores.values(), reverse=True)
        if hi != lo:  # max() on a tie returns the first key, which is not a result
            winner = max(scores, key=scores.get)
    return {
        "state": st.get("state"),
        "completed": completed,
        "scores": scores,
        "home": home_abbr,
        "away": away_abbr,
        "home_score": scores.get(home_abbr),
        "away_score": scores.get(away_abbr),
        "winner": winner,
        "period": status.get("period"),
        "clock": status.get("displayClock"),
        "status_detail": st.get("shortDetail"),
    }


def _parse_record(display_value):
    """Parse ESPN's 'W-L' displayValue ('12-2') into (wins, losses) ints.

    Returns (None, None) for anything unparseable — a missing record must
    read as absence, never as a fabricated 0-0.
    """
    if not isinstance(display_value, str):
        return None, None
    parts = display_value.strip().split("-")
    if len(parts) != 2:
        return None, None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None, None


def _season_phase(seasons, year, now=None):
    """The published season phase that is live right now, from ESPN's own
    season-type calendar. Returns (phase_name, ends_at, in_progress).

    ESPN publishes the whole calendar under `seasons[].types[]` — for MLS 2026:
    Regular Season 2026-01-01 -> 2026-11-09 with `hasStandings: true`, then the
    playoff rounds, each with its own window. "Is the season still being played?"
    is therefore a PUBLISHED fact, and published-first rung 5 applies: a schedule
    is never inferred. We never compare against a hardcoded month.

    Only types carrying `hasStandings` are considered, because those are the ones
    the table on screen is actually a table OF. Returns (None, None, None) when
    the calendar does not say — which the caller must render as unknown, not as
    "final" and not as "in progress".
    """
    import datetime as _dt
    now = now or _dt.datetime.now(_dt.timezone.utc)
    for season in seasons or []:
        if espn_client._int(season.get("year")) != year:
            continue
        for t in season.get("types") or []:
            if not t.get("hasStandings"):
                continue
            start, end = espn_client._iso(t.get("startDate")), espn_client._iso(t.get("endDate"))
            if start and end and start <= now <= end:
                return t.get("name"), end, True
            # Past its end date: the phase happened and is over. Keep looking in
            # case a later phase is live, but remember this one as the fallback.
            if end and now > end:
                return t.get("name"), end, False
    return None, None, None


def mls_conference_standings(season=None):
    """MLS Eastern/Western tables, read from the publisher's own standings.

    `season` selects a past year; None serves whatever ESPN calls current. The
    selectable years are returned as `available_seasons`, read from the payload's
    own `seasons[]` (25 of them, 2002-2026) rather than a range we make up, so a
    year we cannot actually serve is never offered.

    Replaces a DB rollup (`_mls_standings_from_db`) that summed
    `team_game_results` and applied MLS's 3/1/0 rule itself. That rollup was not
    wrong — measured 2026-08-17, it reproduced ESPN's published 2025 table for
    all 30 teams with ZERO disagreements on P/W/D/L/Pts and rank. It was stale,
    which is a different and worse failure: it served whatever season our tables
    happened to hold, and they only ever hold a COMPLETED one. In mid-August
    2026 that meant a 34-games-played 2025 final table presented as the
    standings, with no season on it anywhere.

    The season is therefore never chosen by us. It is read off the payload
    (`season.year`), so "which season is this" is answered by the publisher on
    every request and cannot drift from what the rows actually are.

    `points` and `rank` are copied, never recomputed: MLS's tiebreakers past
    points/wins/GD are a spec we would be forking, and ESPN already applies them.

    TTL is 900s, matching `ncaaf_conference_standings`. This does spend ESPN
    budget that the 2026-08-16 DB-first change deliberately stopped spending —
    but per pageview it spends none, which is what that change was protecting:
    one request per 15 minutes serves the whole league.

    Returns {league, season, season_label, phase, in_progress, phase_ends,
    as_of, groups: [{group, rows: [...]}]}. Raises ValueError when the publisher
    returns no table — never a silently empty one.
    """
    import datetime as _dt
    _, path = espn_client._check("mls")
    url = espn_client._CORE.format(path=path) + "/standings"
    if season is not None:
        url += "?season=%d" % int(season)
    d = espn_client._get(url, ttl=900)
    season_doc = d.get("season") or {}
    year = espn_client._int(season_doc.get("year"))
    if year is None:
        raise ValueError("MLS standings: publisher named no season")
    # Only years the publisher says carry a standings table are offerable.
    available = sorted({espn_client._int(s.get("year")) for s in (d.get("seasons") or [])
                        if any(t.get("hasStandings") for t in (s.get("types") or []))
                        and espn_client._int(s.get("year")) is not None}, reverse=True)

    groups = []
    for child in d.get("children") or []:
        entries = (child.get("standings") or {}).get("entries") or []
        if not entries:
            continue
        rows = []
        for ent in entries:
            s = {x.get("name"): x.get("value") for x in ent.get("stats") or []}
            t = ent.get("team") or {}
            rows.append({
                "rank": espn_client._int(s.get("rank")),
                "abbrev": t.get("abbreviation"),
                "name": t.get("displayName"),
                "played": espn_client._int(s.get("gamesPlayed")),
                "wins": espn_client._int(s.get("wins")),
                "draws": espn_client._int(s.get("ties")),
                "losses": espn_client._int(s.get("losses")),
                "gf": espn_client._int(s.get("pointsFor")),
                "ga": espn_client._int(s.get("pointsAgainst")),
                "gd": espn_client._int(s.get("pointDifferential")),
                "points": espn_client._int(s.get("points")),
            })
        rows.sort(key=lambda r: (r["rank"] is None, r["rank"]))
        groups.append({"group": child.get("name"), "rows": rows})

    if not groups:
        raise ValueError(f"MLS standings: publisher returned no groups for {year}")

    phase, ends, in_progress = _season_phase(d.get("seasons"), year)
    return {
        "league": "mls",
        "season": year,
        "available_seasons": available or [year],
        "season_label": season_doc.get("displayName") or str(year),
        "phase": phase,
        "in_progress": in_progress,
        "phase_ends": ends.isoformat() if ends else None,
        "as_of": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "groups": groups,
    }


def ncaaf_conference_standings():
    """NCAAF per-conference standings — the {group, rows} shape the league
    hub's ConferenceStandings table renders.

    College football's ESPN /standings payload differs from every other
    league's: there is no rank/gamesPlayed/losses stat key, the overall
    record lives in the `overall` displayValue ("12-2"), and entries come
    pre-ordered by conference standing. We read the published order and
    parse the record; we never recompute it. Football has no draws, no
    points column and no gf/ga/gd — those soccer-only fields are omitted
    rather than fabricated as zeros (honest-data-ui: dash != zero).

    Returns [{group: "Big Ten Conference", rows: [{rank, abbrev, name,
    played, wins, losses}]}]. Conferences with no published entries are
    skipped entirely (a table with zero rows is a dead surface).
    """
    _, path = espn_client._check("ncaaf")
    d = espn_client._get(espn_client._CORE.format(path=path) + "/standings", ttl=900)
    groups = []
    for child in d.get("children", []):
        gname = child.get("name", "")
        entries = (child.get("standings") or {}).get("entries", [])
        if not entries:
            continue
        rows = []
        for rank, ent in enumerate(entries, start=1):
            s = {x.get("name"): x.get("value") for x in ent.get("stats", [])}
            disp = {x.get("name"): x.get("displayValue") for x in ent.get("stats", [])}
            t = ent.get("team", {})
            w, l = _parse_record(disp.get("overall"))
            rows.append({
                "rank": rank,
                "abbrev": t.get("abbreviation"),
                "name": t.get("displayName"),
                "played": (w + l) if (w is not None and l is not None) else None,
                "wins": w,
                "losses": l,
            })
        groups.append({"group": gname, "rows": rows})
    return groups


_LCUP_ROUND_ORDER = {
    "quarterfinals": 1,
    "semifinals": 2,
    "third-place": 3,
    "third-place-game": 3,
    "3rd-place-match": 3,
    "final": 4,
}


def lcup_competition_snapshot_from_payload(scoreboard, statistics):
    """Build the Leagues Cup bracket and published leader categories.

    The scoreboard's season slug is the round authority.  League-phase games
    are deliberately excluded from the knockout bracket, and unpublished
    future rounds are not reconstructed from presumed winners.
    """
    scoreboard_season = espn_client._int(
        (((scoreboard.get("leagues") or [{}])[0].get("season") or {}).get("year"))
    )
    statistics_season = espn_client._int((statistics.get("season") or {}).get("year"))
    if not scoreboard_season or statistics_season != scoreboard_season:
        raise ValueError(
            f"Leagues Cup source season mismatch: scoreboard={scoreboard_season} "
            f"statistics={statistics_season}"
        )

    grouped = {}
    for event in scoreboard.get("events", []) or []:
        season = event.get("season") or {}
        slug = str(season.get("slug") or "").lower()
        if slug == "league-phase" or slug not in _LCUP_ROUND_ORDER:
            continue
        comp = (event.get("competitions") or [{}])[0]
        status = comp.get("status") or event.get("status") or {}
        status_type = status.get("type") or {}
        state = status_type.get("state")
        teams = {}
        for competitor in comp.get("competitors", []) or []:
            team = competitor.get("team") or {}
            score = espn_client._num(competitor.get("score")) if state != "pre" else None
            teams[competitor.get("homeAway")] = {
                "id": str(team.get("id") or ""),
                "abbrev": team.get("abbreviation"),
                "name": team.get("displayName") or team.get("name") or "TBD",
                "score": score,
                "winner": competitor.get("winner") is True,
            }
        game_id = str(event.get("id") or comp.get("id") or "")
        if not game_id or not teams.get("home") or not teams.get("away"):
            raise ValueError(f"incomplete Leagues Cup {slug} match id={game_id or '<missing>'}")
        grouped.setdefault(slug, []).append({
            "game_id": game_id,
            "date": event.get("date") or comp.get("date"),
            "state": state,
            "status": status_type.get("description") or status_type.get("shortDetail"),
            "home": teams["home"],
            "away": teams["away"],
        })

    labels = {
        "quarterfinals": "Quarterfinals",
        "semifinals": "Semifinals",
        "third-place": "Third Place",
        "third-place-game": "Third Place",
        "3rd-place-match": "Third Place",
        "final": "Final",
    }
    rounds = []
    for slug in sorted(grouped, key=lambda value: (_LCUP_ROUND_ORDER[value], value)):
        matches = sorted(grouped[slug], key=lambda row: (row.get("date") or "", row["game_id"]))
        rounds.append({"key": slug, "label": labels[slug], "matches": matches})
    if not rounds:
        raise ValueError("Leagues Cup publisher has not published a knockout round")

    leader_categories = []
    for category in statistics.get("stats", []) or []:
        key = str(category.get("name") or "")
        if key not in ("goalsLeaders", "assistsLeaders"):
            continue
        leaders = []
        for rank, item in enumerate(category.get("leaders", []) or [], start=1):
            athlete = item.get("athlete") or {}
            athlete_id = str(athlete.get("id") or "")
            value = espn_client._int(item.get("value"))
            if not athlete_id or not athlete.get("displayName") or value is None:
                raise ValueError(f"incomplete Leagues Cup {key} row")
            display = str(item.get("displayValue") or "")
            match_count = re.search(r"Matches:\s*(\d+)", display)
            team = athlete.get("team") or {}
            leaders.append({
                "rank": rank,
                "espn_athlete_id": athlete_id,
                "name": athlete.get("displayName"),
                "team": team.get("displayName") or team.get("name"),
                "team_abbrev": team.get("abbreviation"),
                "matches": int(match_count.group(1)) if match_count else None,
                "value": value,
            })
        leader_categories.append({
            "key": "goals" if key == "goalsLeaders" else "assists",
            "label": category.get("displayName") or category.get("shortDisplayName"),
            "leaders": leaders,
        })

    return {
        "league": "lcup",
        "season": scoreboard_season,
        "phase": (statistics.get("season") or {}).get("name"),
        "rounds": rounds,
        "leader_categories": leader_categories,
    }


def lcup_competition_snapshot(season):
    """Fetch the current full-season bracket and published leader tables."""
    season = int(season)
    scoreboard = espn_client.scoreboard_raw("lcup", str(season), ttl=3600)
    _, path = espn_client._check("lcup")
    stats_url = (
        espn_client._SITE.format(path=path)
        + f"/statistics?season={season}&limit=50"
    )
    statistics = espn_client._get(stats_url, ttl=3600)
    return lcup_competition_snapshot_from_payload(scoreboard, statistics)
