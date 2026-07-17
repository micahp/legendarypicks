"""Build a grounded Call of Duty match-context response from existing sources.

PandaScore's ``codmw`` feed is authoritative for match identity, state, series
score, per-map winners, and recent history. The existing esports slate supplies
the current market favorite and watch target when that exact fixture is present.
Broadcast reads come only from timestamped CDL signal files whose time window
overlaps this match.

The feed does not currently expose map names or a validated roster-change
history. Those values stay absent rather than being inferred.
"""

from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
from typing import Any

from routers.esports.pandascore import _fetch_ps


BROADCAST_DIR = os.environ.get(
    "LP_BROADCAST_DIR", "/root/prediction-market-trading/data/broadcast"
)

_TAG_LABEL = {
    "momentum": "Momentum",
    "tactical": "Tactical",
    "morale": "Mentality",
    "fatigue": "Fatigue",
    "lockin": "Key man",
    "injury": "Injury",
}
_ROSTER_RE = re.compile(r"\b(roster|rookie|let go|bring(?:ing)? in|replace|filling|two week)\b", re.I)


def _is_cod(match: dict) -> bool:
    videogame = match.get("videogame") or {}
    return (
        videogame.get("slug") == "cod-mw"
        or (videogame.get("name") or "").lower() == "call of duty"
    )


def _parse_time(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def _identity_tokens(value: Any) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def _subject_matches_team(subject: str, teams: list[dict]) -> bool:
    """Require explicit lexical evidence before assigning a booth read to a team."""
    subject_tokens = _identity_tokens(subject)
    if not subject_tokens:
        return False
    subject_key = "".join(sorted(subject_tokens))
    for team in teams:
        for label in (team.get("name"), team.get("acronym")):
            label_tokens = _identity_tokens(label)
            if not label_tokens:
                continue
            if subject_key == "".join(sorted(label_tokens)):
                return True
            if any(
                len(token) >= 4 or (len(token) >= 2 and any(char.isdigit() for char in token))
                for token in subject_tokens & label_tokens
            ):
                return True
    return False


def _subject_is_grounded(row: dict, teams: list[dict]) -> bool:
    subject = str(row.get("subject") or "").strip()
    if _subject_matches_team(subject, teams):
        return True
    # A player/non-team label must appear verbatim in the evidence. Case-sensitive
    # matching avoids promoting an ordinary ASR word (for example "phase") into a
    # named subject while retaining explicit names such as "Nasty" in the quote.
    return len(subject) >= 4 and re.search(
        rf"\b{re.escape(subject)}\b", str(row.get("quote") or "")
    ) is not None


def _match_time(match: dict) -> dt.datetime | None:
    return (
        _parse_time(match.get("begin_at"))
        or _parse_time(match.get("scheduled_at"))
        or _parse_time(match.get("end_at"))
    )


def _opponents(match: dict) -> list[dict]:
    return [
        item.get("opponent") or {}
        for item in (match.get("opponents") or [])
        if item.get("opponent")
    ]


def _team_ids(match: dict) -> set[int]:
    return {team.get("id") for team in _opponents(match) if team.get("id") is not None}


def _scores(match: dict) -> dict[int, int | None]:
    return {
        row.get("team_id"): row.get("score")
        for row in (match.get("results") or [])
        if row.get("team_id") is not None
    }


def _team_name(match: dict, team_id: int | None) -> str | None:
    for team in _opponents(match):
        if team.get("id") == team_id:
            return team.get("name")
    return None


def _other_team(match: dict, team_id: int) -> dict | None:
    return next((team for team in _opponents(match) if team.get("id") != team_id), None)


def _finished_before(match: dict, cutoff: dt.datetime, exclude_id: int) -> bool:
    when = _match_time(match)
    return (
        match.get("id") != exclude_id
        and match.get("status") == "finished"
        and when is not None
        and when < cutoff
    )


def _series_summary(match: dict, focus_team_id: int) -> dict | None:
    opponent = _other_team(match, focus_team_id)
    winner_id = match.get("winner_id")
    if not opponent or winner_id is None:
        return None
    scores = _scores(match)
    return {
        "match_id": match.get("id"),
        "date": (_match_time(match).isoformat() if _match_time(match) else None),
        "opponent": opponent.get("name"),
        "opponent_logo": opponent.get("image_url"),
        "result": "W" if winner_id == focus_team_id else "L",
        "score_for": scores.get(focus_team_id),
        "score_against": scores.get(opponent.get("id")),
        "event": (match.get("serie") or {}).get("full_name")
        or (match.get("serie") or {}).get("name"),
    }


def _recent_form(
    matches: list[dict], team_id: int, cutoff: dt.datetime, current_id: int
) -> dict:
    finished = [
        match
        for match in matches
        if team_id in _team_ids(match) and _finished_before(match, cutoff, current_id)
    ]
    finished.sort(key=lambda match: _match_time(match) or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True)

    series = [summary for match in finished if (summary := _series_summary(match, team_id))][:5]
    series_wins = sum(1 for row in series if row["result"] == "W")

    maps = []
    for match in finished:
        opponent = _other_team(match, team_id)
        if not opponent:
            continue
        match_when = _match_time(match) or dt.datetime.min.replace(tzinfo=dt.timezone.utc)
        for game in match.get("games") or []:
            winner_id = (game.get("winner") or {}).get("id")
            if not game.get("finished") or winner_id is None:
                continue
            maps.append({
                "match_id": match.get("id"),
                "opponent": opponent.get("name"),
                "position": game.get("position"),
                "result": "W" if winner_id == team_id else "L",
                "finished_at": game.get("end_at"),
                "_sort": (_parse_time(game.get("end_at")) or match_when, game.get("position") or 0),
            })
    maps.sort(key=lambda row: row["_sort"], reverse=True)
    maps = maps[:10]
    for row in maps:
        row.pop("_sort", None)
    map_wins = sum(1 for row in maps if row["result"] == "W")
    map_total = len(maps)

    return {
        "series": series,
        "series_record": {"wins": series_wins, "losses": len(series) - series_wins},
        "recent_maps": maps,
        "map_record": {"wins": map_wins, "losses": map_total - map_wins},
        "map_win_pct": round(map_wins / map_total * 100, 1) if map_total else None,
    }


def _head_to_head(
    matches: list[dict], team_a_id: int, team_b_id: int, cutoff: dt.datetime, current_id: int
) -> list[dict]:
    rows = [
        match
        for match in matches
        if _team_ids(match) == {team_a_id, team_b_id}
        and _finished_before(match, cutoff, current_id)
    ]
    rows.sort(key=lambda match: _match_time(match) or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True)
    out = []
    for match in rows[:5]:
        scores = _scores(match)
        out.append({
            "match_id": match.get("id"),
            "date": (_match_time(match).isoformat() if _match_time(match) else None),
            "team_a_score": scores.get(team_a_id),
            "team_b_score": scores.get(team_b_id),
            "winner_id": match.get("winner_id"),
            "winner_name": _team_name(match, match.get("winner_id")),
            "event": (match.get("serie") or {}).get("full_name")
            or (match.get("serie") or {}).get("name"),
        })
    return out


def _current_maps(match: dict) -> list[dict]:
    return [{
        "position": game.get("position"),
        "status": game.get("status"),
        "finished": bool(game.get("finished")),
        "winner_id": (game.get("winner") or {}).get("id"),
        "winner_name": _team_name(match, (game.get("winner") or {}).get("id")),
        "length_seconds": game.get("length"),
    } for game in sorted(match.get("games") or [], key=lambda row: row.get("position") or 0)]


def _slate_match(match: dict) -> tuple[dict | None, str | None]:
    """Find this fixture in the existing board without a name-only guess.

    Prefer the exact PandaScore id. Finished store rows currently predate psId
    persistence, so a fallback requires both exact team names and a start time
    within six hours; otherwise market/watch data remains absent.
    """
    try:
        from routers.esports.slate import esports_upcoming

        board = esports_upcoming()
    except Exception:
        return None, None
    rows = board.get("matches", []) if isinstance(board, dict) else []
    game_id = str(match.get("id"))
    exact = next((row for row in rows if row.get("psId") is not None and str(row.get("psId")) == game_id), None)
    if exact:
        return exact, "psId"

    names = {team.get("name") for team in _opponents(match) if team.get("name")}
    when = _match_time(match)
    if len(names) != 2 or when is None:
        return None, None
    target_ms = int(when.timestamp() * 1000)
    candidates = []
    for row in rows:
        if row.get("title") != "Call of Duty" or {row.get("teamA"), row.get("teamB")} != names:
            continue
        start_ms = row.get("startTime")
        if start_ms is None:
            continue
        distance = abs(int(start_ms) - target_ms)
        if distance <= 6 * 60 * 60 * 1000:
            candidates.append((distance, row))
    if not candidates:
        return None, None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1], "exact_pair_time"


def _broadcast_insights(match: dict, limit: int) -> list[dict]:
    start = _match_time(match)
    if start is None:
        return []
    now = dt.datetime.now(dt.timezone.utc)
    end = _parse_time(match.get("end_at"))
    if end is None:
        end = now if start <= now else min(start, now)
    window_start = start - dt.timedelta(minutes=20)
    window_end = end + dt.timedelta(minutes=15)

    rows = []
    for path in glob.glob(os.path.join(BROADCAST_DIR, "*_signals.jsonl")):
        filename = os.path.basename(path).upper()
        if "CDL" not in filename and "COD" not in filename:
            continue
        try:
            with open(path) as handle:
                for line in handle:
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    ts = _parse_time(row.get("ts"))
                    if ts is None or not (window_start <= ts <= window_end):
                        continue
                    quote = str(row.get("quote") or "").strip()
                    if len(quote) < 25:
                        continue
                    rows.append({
                        "tag": _TAG_LABEL.get(row.get("type"), "Read"),
                        "subject": str(row.get("subject") or "").strip(),
                        "quote": quote[:260],
                        "strength": row.get("strength") or 1,
                        "direction": row.get("direction"),
                        "ts": row.get("ts"),
                        "source_file": os.path.basename(path),
                    })
        except OSError:
            continue

    deduped, seen = [], set()
    for row in sorted(
        rows,
        key=lambda item: (
            bool(_ROSTER_RE.search(item["quote"])),
            item["strength"],
            item.get("ts") or "",
        ),
        reverse=True,
    ):
        quote_key = re.sub(r"[^a-z0-9]", "", row["quote"].lower())[:80]
        if not quote_key or quote_key in seen:
            continue
        seen.add(quote_key)
        deduped.append(row)
    selected = deduped[:limit]
    selected.sort(key=lambda item: item.get("ts") or "")
    return selected


def _enrich_insight(row: dict, teams: list[dict]) -> dict:
    raw_subject = str(row.get("subject") or "").strip()
    subject = raw_subject if _subject_is_grounded(row, teams) else None
    direction = row.get("direction")
    if _ROSTER_RE.search(row.get("quote") or ""):
        return {
            "subject": subject or "",
            "headline": (
                f"Broadcast flagged lineup uncertainty around {subject}"
                if subject else "Broadcast flagged lineup uncertainty"
            ),
            "analysis": (
                "A late lineup change can make historical form less representative; this remains "
                "booth context until a roster source confirms it."
            ),
        }
    if row.get("tag") == "Tactical":
        return {
            "subject": subject or "",
            "headline": (
                f"The booth identified a tactical pressure point for {subject}"
                if subject else "The booth identified a tactical pressure point"
            ),
            "analysis": "This is matchup context from the broadcast, not a verified map or result claim.",
        }
    if row.get("tag") == "Key man":
        return {
            "subject": subject or "",
            "headline": (
                f"{subject} was singled out as a key performer"
                if subject else "The booth singled out an individual performance"
            ),
            "analysis": "The booth treated this individual performance as material to the current match flow.",
        }
    tone = "positive" if direction == "bullish" else "negative" if direction == "bearish" else "notable"
    return {
        "subject": subject or "",
        "headline": (
            f"{subject} drew a {tone} {str(row.get('tag') or 'booth').lower()} read"
            if subject else
            f"The booth carried a {tone} {str(row.get('tag') or 'match').lower()} read"
        ),
        "analysis": "The classification comes from the timestamped broadcast signal; the quote remains the evidence.",
    }


def _fact_lines(match: dict, teams: list[dict], forms: dict[int, dict], h2h: list[dict], market: dict | None) -> list[str]:
    lines = []
    scores = _scores(match)
    if match.get("status") in {"running", "finished"}:
        lines.append(
            f"Match status {match.get('status')}; series score "
            f"{teams[0].get('name')} {scores.get(teams[0].get('id'))} - "
            f"{scores.get(teams[1].get('id'))} {teams[1].get('name')}"
        )
    else:
        lines.append(f"Match status {match.get('status')}; no series score yet")
    for team in teams:
        form = forms.get(team.get("id"), {})
        series = form.get("series_record") or {}
        maps = form.get("map_record") or {}
        lines.append(
            f"{team.get('name')} before this match: last {len(form.get('series') or [])} series "
            f"{series.get('wins', 0)}-{series.get('losses', 0)}; last "
            f"{len(form.get('recent_maps') or [])} maps {maps.get('wins', 0)}-{maps.get('losses', 0)}"
        )
    if h2h:
        wins = {teams[0].get("id"): 0, teams[1].get("id"): 0}
        for row in h2h:
            if row.get("winner_id") in wins:
                wins[row["winner_id"]] += 1
        lines.append(
            f"Last {len(h2h)} head-to-head series before this match: "
            f"{teams[0].get('name')} {wins[teams[0].get('id')]} - "
            f"{wins[teams[1].get('id')]} {teams[1].get('name')}"
        )
    if market:
        lines.append(f"Current slate favorite: {market.get('name')} at {market.get('pct')}%")
    return lines


def _build_read(
    match: dict,
    facts: list[str],
    insights: list[dict],
    teams: list[dict],
    forms: dict[int, dict],
    h2h: list[dict],
    market: dict | None,
) -> list[dict]:
    read = []
    a, b = teams[0], teams[1]
    a_record = forms[a["id"]]["series_record"]
    b_record = forms[b["id"]]["series_record"]
    a_strength = (a_record["wins"], -a_record["losses"])
    b_strength = (b_record["wins"], -b_record["losses"])
    stronger = a if a_strength > b_strength else b if b_strength > a_strength else None
    scores = _scores(match)
    winner = next((team for team in teams if team.get("id") == match.get("winner_id")), None)
    if match.get("status") == "finished" and winner and stronger:
        if winner["id"] == stronger["id"]:
            headline = f"{winner['name']} converted the stronger pre-match form"
        else:
            headline = f"{winner['name']} overturned the pre-match form gap"
        read.append({
            "headline": headline,
            "evidence": (
                f"Before the match: {facts[1]}; {facts[2]}. Final series score "
                f"{a['name']} {scores.get(a['id'])}-{scores.get(b['id'])} {b['name']}."
            ),
            "source": "pandascore",
        })
    elif match.get("status") == "running" and stronger:
        score_a, score_b = scores.get(a["id"]), scores.get(b["id"])
        leader = a if score_a is not None and score_b is not None and score_a > score_b else b if score_a is not None and score_b is not None and score_b > score_a else None
        if leader:
            read.append({
                "headline": (
                    f"{leader['name']}'s live lead aligns with the form baseline"
                    if leader["id"] == stronger["id"] else
                    f"{leader['name']} is running against the pre-match form baseline"
                ),
                "evidence": f"{facts[1]}; {facts[2]}. Live series score {a['name']} {score_a}-{score_b} {b['name']}.",
                "source": "pandascore",
            })
    if h2h:
        h2h_wins = {a["id"]: 0, b["id"]: 0}
        for row in h2h:
            if row.get("winner_id") in h2h_wins:
                h2h_wins[row["winner_id"]] += 1
        h2h_leader = a if h2h_wins[a["id"]] > h2h_wins[b["id"]] else b if h2h_wins[b["id"]] > h2h_wins[a["id"]] else None
        read.append({
            "headline": (
                f"{h2h_leader['name']} held the recent head-to-head edge"
                if h2h_leader else "The recent head-to-head was even"
            ),
            "evidence": next((line for line in facts if line.startswith("Last ") and "head-to-head" in line), ""),
            "source": "pandascore",
        })

    roster_read = next((
        row for row in insights
        if _ROSTER_RE.search(row.get("quote") or "")
        and _subject_matches_team(str(row.get("subject") or ""), teams)
    ), None)
    if roster_read:
        read.append({
            "headline": roster_read["headline"],
            "evidence": f"Broadcast: “{roster_read.get('quote')}”",
            "source": "booth",
        })

    if market and stronger:
        favorite = next((team for team in teams if team["name"].lower() == str(market.get("name") or "").lower()), None)
        if favorite:
            read.append({
                "headline": (
                    "The current market and recent form point the same way"
                    if favorite["id"] == stronger["id"] else
                    "The current market and recent form diverge"
                ),
                "evidence": f"Current slate: {market.get('name')} {market.get('pct')}% favorite. {facts[1]}; {facts[2]}.",
                "source": "combined",
            })

    if len(read) < 4:
        first = next((row for row in insights if row is not roster_read), None)
        if first:
            read.append({
                "headline": first["headline"],
                "evidence": f"Broadcast: “{first.get('quote')}”",
                "source": "booth",
            })
    return read[:4]


def _analyze(
    match: dict,
    facts: list[str],
    insights: list[dict],
    teams: list[dict],
    forms: dict[int, dict],
    h2h: list[dict],
    market: dict | None,
) -> tuple[list[dict], list[dict]]:
    enriched = [{**row, **_enrich_insight(row, teams)} for row in insights]
    return enriched, _build_read(match, facts, enriched, teams, forms, h2h, market)


def build_context(game_id: str, limit: int = 12) -> dict | None:
    try:
        numeric_id = int(game_id)
    except (TypeError, ValueError):
        return None

    matches = [match for match in _fetch_ps(include_running=True) if _is_cod(match)]
    match = next((row for row in matches if row.get("id") == numeric_id), None)
    if not match:
        return None
    teams = _opponents(match)
    if len(teams) != 2 or any(team.get("id") is None for team in teams):
        return None

    cutoff = _match_time(match) or dt.datetime.now(dt.timezone.utc)
    forms = {
        team["id"]: _recent_form(matches, team["id"], cutoff, numeric_id)
        for team in teams
    }
    h2h = _head_to_head(matches, teams[0]["id"], teams[1]["id"], cutoff, numeric_id)
    slate, slate_match_method = _slate_match(match)
    market = slate.get("favorite") if slate and slate.get("favorite") else None
    facts = _fact_lines(match, teams, forms, h2h, market)
    raw_insights = _broadcast_insights(match, max(limit, 18))
    enriched, read = _analyze(match, facts, raw_insights, teams, forms, h2h, market)

    ps_scores = _scores(match)
    score = (
        {"a": ps_scores.get(teams[0]["id"]), "b": ps_scores.get(teams[1]["id"])}
        if match.get("status") in {"running", "finished"}
        else {"a": None, "b": None}
    )
    status = slate.get("state") if slate and slate.get("state") else match.get("status")
    serie = match.get("serie") or {}
    tournament = match.get("tournament") or {}
    league = match.get("league") or {}

    return {
        "game_id": str(numeric_id),
        "status": status,
        "live": status in {"live", "running"},
        "finished": status in {"finished", "final"},
        "scheduled_at": match.get("scheduled_at"),
        "begin_at": match.get("begin_at"),
        "end_at": match.get("end_at"),
        "best_of": match.get("number_of_games"),
        "event": {
            "league": league.get("name"),
            "serie": serie.get("full_name") or serie.get("name"),
            "tournament": tournament.get("name"),
            "serie_id": serie.get("id"),
        },
        "teams": [
            {
                "id": team.get("id"),
                "name": team.get("name"),
                "acronym": team.get("acronym"),
                "logo": team.get("image_url"),
                "score": score.get("a" if index == 0 else "b"),
                "winner": match.get("winner_id") == team.get("id"),
                "form": forms[team["id"]],
            }
            for index, team in enumerate(teams)
        ],
        "market": market,
        "market_match_method": slate_match_method,
        "watch": slate.get("watch") if slate else None,
        "maps": _current_maps(match),
        "head_to_head": h2h,
        "insights": enriched[:limit],
        "read": read,
        "discount_play": None,
        "discount_reason": (
            "No verified discount: the available feed has a current favorite snapshot but no "
            "time-aligned price history proving that new information is still mispriced."
            if market else
            "No verified discount: no current market snapshot is attached to this match."
        ),
        "roster_change": None,
        "limitations": [
            "PandaScore supplies per-map winners but not map names in this feed, so map-pool labels are omitted.",
            "No validated roster-change history source is wired; broadcast roster talk remains booth context, not a roster fact.",
        ],
        "sources": {
            "match_and_form": "PandaScore codmw",
            "market": "Existing esports slate" if market else None,
            "booth": sorted({row.get("source_file") for row in enriched if row.get("source_file")}),
        },
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
