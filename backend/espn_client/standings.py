"""espn_client.standings -- published standings tables.

`team_strength` is the flat quality prior (win%, differential, streak, last-10);
`team_strength_standings` wraps it with the season the publisher says the rows
belong to; `group_standings` copies the publisher's leaf-group tables for
soccer and conference-shaped leagues (NCAAF, MLS).

Shared calls (`_check`, `_get`, `_int`) resolve through the `espn_client`
package at call time so monkeypatching `espn_client._get` (as
test_group_standings_contract does) keeps working.
"""
import espn_client


def team_strength(league):
    """Every team ranked by quality — win%, differential, streak, last-10. The selection prior.

    `differential` is run differential (MLB), goal diff (NHL), point diff (NBA/NFL) per game.
    """
    _, path = espn_client._check(league)
    d = espn_client._get(espn_client._CORE.format(path=path) + "/standings", ttl=900)
    return _team_strength_rows(d)


def _team_strength_rows(d):
    rows = []
    for child in d.get("children", []):                  # divisions / conferences
        for ent in child.get("standings", {}).get("entries", []):
            s = {x.get("name"): x.get("value") for x in ent.get("stats", [])}
            disp = {x.get("name"): x.get("displayValue") for x in ent.get("stats", [])}
            t = ent.get("team", {})
            wp = s.get("winPercent")
            w, l = espn_client._int(s.get("wins")), espn_client._int(s.get("losses"))
            if wp is None and w is not None:
                # NHL (and any league) exposes no winPercent stat — derive it.
                # Prefer games played (includes OT losses) so it isn't overstated.
                denom = espn_client._int(s.get("gamesPlayed")) or ((w or 0) + (l or 0))
                wp = (w / denom) if denom else None
            # ESPN's NHL "Last Ten Games" displayValue is e.g. "7-2-1, 0 PTS";
            # keep just the record and drop the stray points suffix.
            last10 = disp.get("Last Ten Games")
            if isinstance(last10, str) and "," in last10:
                last10 = last10.split(",")[0].strip()
            rows.append({
                "abbrev": t.get("abbreviation"),
                "name": t.get("displayName"),
                "wins": w,
                "losses": l,
                "win_pct": round(wp, 4) if wp is not None else None,
                "differential": s.get("pointDifferential", s.get("differential")),
                "streak": disp.get("streak"),
                "last10": last10,
                "games_played": espn_client._int(s.get("gamesPlayed")),
            })
    rows.sort(key=lambda r: (r["win_pct"] if r["win_pct"] is not None else -1), reverse=True)
    return rows


def team_strength_standings(league, season=None):
    """`team_strength` rows plus the season the publisher says they belong to.

    Same core /standings document team_strength already reads — the year and the
    league's selectable years are fields on it, so this copies them rather than
    inferring a season from the calendar or from MAX() of what we hold. Without
    this the standings tab rendered a table with nothing naming its season.

    `season` selects a past year; None serves whatever ESPN calls current, so the
    default never pins a year that goes stale. `available_seasons` is read from
    the payload's own `seasons[]`, filtered to the years that actually carry a
    standings table, so a year we cannot serve is never offered.
    """
    _, path = espn_client._check(league)
    url = espn_client._CORE.format(path=path) + "/standings"
    if season is not None:
        url += "?season=%d" % int(season)
    d = espn_client._get(url, ttl=900)
    season_doc = d.get("season") or {}
    year = espn_client._int(season_doc.get("year"))
    # Only years the publisher says carry a standings table are offerable.
    published = {}
    for entry in d.get("seasons") or []:
        entry_year = espn_client._int(entry.get("year"))
        if entry_year is None:
            continue
        if any(t.get("hasStandings") for t in (entry.get("types") or [])):
            published[entry_year] = entry.get("displayName") or str(entry_year)
    available = sorted(published, reverse=True)

    # On a default request `season.year` names the season ESPN is POINTING at,
    # which is not always the one it just served. Measured 2026-08-17: NBA, MLB
    # and NHL all reported 2027 while returning the 2026 table (MLB's Brewers at
    # 77-48 through 125 games — an in-progress 2026 season), and 2027 is absent
    # from their own `seasons[]` because it has no standings table yet. NFL and
    # MLS agreed. Trusting it would have labelled a live 2026 table "2027".
    #
    # An explicitly requested season is accurate (?season=2015 returns STL
    # 100-62, GS 67-15, CAR 15-1), so only the default is corrected, and only
    # ever downward to a year the publisher itself lists.
    if season is None and available and (year is None or year > available[0]):
        year = available[0]
        label = published[year]
    else:
        label = season_doc.get("displayName") or published.get(year) or (
            str(year) if year is not None else None
        )
    return {
        "league": league.lower(),
        "season": year,
        "season_label": label,
        "available_seasons": available or ([year] if year is not None else []),
        "teams": _team_strength_rows(d),
    }


def team_strength_map(league):
    """{abbrev: strength_row} for O(1) lookup / joining to a market."""
    return {r["abbrev"]: r for r in espn_client.team_strength(league) if r["abbrev"]}


def _standing_int(value):
    """Copy a published integer-like standings field, preserving absence."""
    if value is None or value == "":
        return None
    return int(value)


def _standing_rows(entries):
    rows = []
    for ent in entries:
        s = {x.get("name"): x.get("value") for x in ent.get("stats", [])}
        t = ent.get("team", {})
        rows.append({
            "rank": _standing_int(s.get("rank")),
            "abbrev": t.get("abbreviation"),
            "name": t.get("displayName"),
            "played": _standing_int(s.get("gamesPlayed")),
            "wins": _standing_int(s.get("wins")),
            "draws": _standing_int(s.get("ties")),
            "losses": _standing_int(s.get("losses")),
            "gf": _standing_int(s.get("pointsFor")),
            "ga": _standing_int(s.get("pointsAgainst")),
            "gd": _standing_int(s.get("pointDifferential")),
            "points": _standing_int(s.get("points")),
        })
    # ESPN publishes standings in rank order. Preserve that order rather than
    # inventing an order from a nullable rank field during preseason.
    return rows


def group_standings(league):
    """Published leaf-group standings for soccer and conference-shaped leagues.

    Returns [{group, rows}] and copies the publisher's values without deriving
    records, points, or membership. A container such as the Sun Belt Conference
    can hold published East/West child tables instead of direct entries, so only
    empty containers are descended; every populated leaf remains separately
    visible. Missing publisher stats stay ``None`` for an honest UI dash.
    """
    _, path = espn_client._check(league)
    d = espn_client._get(espn_client._CORE.format(path=path) + "/standings", ttl=900)
    groups = []

    def add_leaf_groups(node):
        entries = (node.get("standings") or {}).get("entries") or []
        if entries:
            groups.append({
                "group": node.get("name", ""),
                "rows": _standing_rows(entries),
            })
            return
        for child in node.get("children") or []:
            add_leaf_groups(child)

    for child in d.get("children", []):
        add_leaf_groups(child)
    return groups
