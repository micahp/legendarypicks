"""matchup_context.py — the facts that make a pregame summary worth reading.

generate_game_story had exactly two sources of grounding: the team strength table and
prop-derived player form. Soccer has no props, so every Leagues Cup story was written from
strength ranks alone, and it showed — "Inter Miami sits at #7 in the 36-team table,
Monterrey at #27" is a sentence about a leaderboard, not about a match.

Everything here comes out of the ESPN summary payload we already fetch for that game. No
new host, no extra request: `summary()` is one call with a 20s TTL and these are four keys
of it that nothing was reading.

  lastFiveGames  recent form, and it crosses competitions — an MLS club's last five
                 spans MLS and Leagues Cup rows, which is what makes "lost five straight"
                 true rather than "lost five straight in this tournament"
  leaders        who the story is. Present BEFORE kickoff and tournament-to-date there
                 ("Matches: 2, Goals: 2"); after full time it is that match's stats
  standings      for a cross-league tournament, the two groups ARE the two leagues
  header.season  the phase, in the publisher's own words

The origin split is the one that cannot be read off a single row. Leagues Cup pairs MLS
clubs against Liga MX clubs, so summing each group's wins answers "how is one league doing
against the other" — 36 matches, Liga MX 11 wins, MLS 22. That is the difference between a
writer saying "Santos are 27th" and saying "the Mexican sides have been struggling."

Fail-soft by contract, the same as stakes.py: any error, any missing key, any shape we did
not expect returns fewer lines or none. A thin story is acceptable; a wrong one is not.
"""

# ESPN labels one group of a cross-league tournament and leaves the other None (Liga MX is
# named, MLS is not). Rather than hardcode "the unnamed one is MLS", derive it from the
# match's own teams: lastFiveGames carries each club's home-league abbreviation.
_MAX_LEADER_CATS = 2


def context_lines(league, game_id, summary=None, fetch=None):
    """-> list of grounding strings for this matchup. Empty when nothing is derivable."""
    try:
        if summary is None:
            if fetch is None:
                import espn_client as espn
                fetch = espn.summary
            summary = fetch(league, game_id)
        if not isinstance(summary, dict):
            return []
    except Exception:
        return []

    lines = []
    for producer in (_phase, _origin_split, _form, _leaders):
        try:
            lines.extend(producer(summary) or [])
        except Exception:
            continue
    return lines


def _phase(d):
    """The competition and the stage, as the publisher names them."""
    season = (d.get("header") or {}).get("season") or {}
    name = (season.get("name") or "").strip()
    out = [f"Competition: {name}."] if name else []
    # An ingest note carries advancement/elimination once it is decided.
    for comp in ((d.get("header") or {}).get("competitions") or []):
        for note in (comp.get("notes") or []):
            text = (note.get("text") or "").strip()
            if text:
                out.append(text)
    return out


def _home_leagues(d):
    """{team abbrev -> home league abbrev} for the two clubs in this match, read off their
    own recent fixtures. 'Leagues Cup' is the tournament itself, never a home league."""
    out = {}
    for entry in d.get("lastFiveGames") or []:
        ab = ((entry.get("team") or {}).get("abbreviation") or "").strip()
        if not ab:
            continue
        for ev in entry.get("events") or []:
            lg = (ev.get("leagueAbbreviation") or "").strip()
            if lg and lg.lower() not in ("leagues cup",):
                out[ab] = lg
                break
    return out


def _group_totals(group):
    """Summed W-L-D and match count for one standings group."""
    tot = {"wins": 0, "losses": 0, "ties": 0, "gamesPlayed": 0}
    for entry in (group.get("standings") or {}).get("entries") or []:
        for stat in entry.get("stats") or []:
            name = stat.get("name")
            if name in tot:
                tot[name] += int(stat.get("value") or 0)
    return tot


def _origin_split(d):
    """For a tournament whose groups are two different leagues, how each league is faring
    against the other. Only meaningful with exactly two groups — that is the cross-league
    shape. A normal league table has one group or many, and gets nothing here."""
    groups = ((d.get("standings") or {}).get("groups")) or []
    if len(groups) != 2:
        return []

    # Name each group: the publisher's divisionHeader when it gives one, otherwise the home
    # league of whichever of this match's two clubs appears in it.
    home_leagues = _home_leagues(d)
    names = []
    for g in groups:
        label = (g.get("divisionHeader") or "").strip()
        if not label:
            members = {(e.get("team") or "").strip()
                       for e in (g.get("standings") or {}).get("entries") or []}
            for ab, lg in home_leagues.items():
                if _abbrev_in(ab, members, d):
                    label = lg
                    break
        names.append(label)

    totals = [_group_totals(g) for g in groups]
    # Every match pairs one club from each group, so the two groups describe the SAME set of
    # matches from opposite sides. If they disagree on how many were played, the assumption
    # does not hold for this tournament and we say nothing.
    if totals[0]["gamesPlayed"] != totals[1]["gamesPlayed"]:
        return []
    played = totals[0]["gamesPlayed"]
    if played <= 0 or not all(names):
        return []

    parts = []
    for label, t in zip(names, totals):
        parts.append(f"{label} clubs {t['wins']}-{t['losses']}-{t['ties']}")
    return [f"This tournament is {names[0]} against {names[1]}. Across {played} matches "
            f"played so far: {', '.join(parts)} (W-L-D)."]


def _abbrev_in(abbrev, member_names, d):
    """Standings entries carry a display name, the rest of the payload an abbreviation.
    Bridge them through the team objects the payload already gives us."""
    for entry in d.get("lastFiveGames") or []:
        team = entry.get("team") or {}
        if (team.get("abbreviation") or "").strip() == abbrev:
            return (team.get("displayName") or "").strip() in member_names
    return False


def _form(d):
    """Recent results, most recent first, with the competition each came in — and the run
    stated plainly, because 'lost five straight' is the fact a reader acts on."""
    out = []
    for entry in d.get("lastFiveGames") or []:
        team = entry.get("team") or {}
        name = (team.get("displayName") or team.get("abbreviation") or "").strip()
        events = list(entry.get("events") or [])
        if not name or not events:
            continue
        # ESPN orders these oldest-first.
        events.reverse()
        results = [(e.get("gameResult") or "").upper() for e in events]
        described = []
        for e, r in zip(events, results):
            opp = (e.get("opponent") or {}).get("abbreviation") or "?"
            at_vs = "at" if (e.get("atVs") or "") == "@" else "vs"
            comp = (e.get("leagueAbbreviation") or "").strip()
            described.append(f"{r or '?'} {e.get('score') or ''} {at_vs} {opp}"
                             + (f" ({comp})" if comp else ""))
        line = f"{name} — last {len(described)}, most recent first: " + "; ".join(described)
        run = _streak(results)
        if run:
            line += f". {name} {run}"
        out.append(line + ".")
    return out


def _streak(results):
    """'have lost 5 straight' / 'have won 3 straight'. Only for a run of 2 or more, and only
    for W or L — a run of draws is not a story."""
    if not results or not results[0]:
        return ""
    first = results[0]
    if first not in ("W", "L"):
        return ""
    n = 0
    for r in results:
        if r != first:
            break
        n += 1
    if n < 2:
        return ""
    verb = "have won" if first == "W" else "have lost"
    return f"{verb} {n} straight"


def _leaders(d):
    """Who is producing for each side. Before kickoff these are tournament-to-date and
    ESPN says so in the value itself ('Matches: 2, Goals: 2'); after full time they are the
    match's own numbers. Either way the displayValue is the publisher's own wording."""
    out = []
    for entry in d.get("leaders") or []:
        team = entry.get("team") or {}
        name = (team.get("displayName") or team.get("abbreviation") or "").strip()
        cats = []
        for cat in (entry.get("leaders") or [])[:_MAX_LEADER_CATS]:
            label = (cat.get("displayName") or cat.get("name") or "").strip()
            top = (cat.get("leaders") or [])
            if not label or not top:
                continue
            athlete = (top[0].get("athlete") or {}).get("displayName")
            value = (top[0].get("displayValue") or "").strip()
            if athlete and value:
                cats.append(f"{label} — {athlete} ({value})")
        if name and cats:
            out.append(f"{name} leaders: " + "; ".join(cats) + ".")
    return out
