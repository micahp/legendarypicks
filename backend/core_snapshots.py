"""ESPN summary -> our tables: the capture and snapshot path.

Lifted out of `_core.py`. These read a published game summary and persist it —
team stats, scoring plays, game context, rosters — plus the small parsers they
all share (`_parse_int`, `_parse_real`, `_num`).

The DB-only readers `_final_score_from_db` and `_state_from_db` stay in `_core`:
they answer from our own tables and never touch a summary, so they belong with
the game-detail path rather than the capture path.

`_db` is imported INSIDE each function rather than at module scope, on purpose.
`_core.DB` and `_core._db` are patch targets in seven test files; a module-level
`from _core import _db` would bind the real function once at import and make
`mock.patch.object(_core, "_db", ...)` a no-op here — a patch that silently stops
taking effect is worse than no patch. A call-time lookup goes through `_core`'s
namespace every time, so patches apply and the import cycle never forms.
"""
import datetime as dt
import json
from contextlib import closing

import espn_client as espn
from team_stats_json import stats_to_json


def _db():
    """`_core._db`, resolved at call time so test patches are honoured."""
    from _core import _db as _core_db
    return _core_db()


def _parse_int(v):
    try: return int(v)
    except (TypeError, ValueError): return None


def _parse_real(v):
    try: return float(v)
    except (TypeError, ValueError): return None


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _fetch_summary(league, game_id):
    """Raw ESPN summary payload for a single game. Returns the full JSON dict."""
    return espn.summary(league, game_id)


def _extract_team_stats(league, game_id, summary):
    """Parse boxscore.teams[].statistics[] → list of {team_abbrev, home_away, stats_dict}."""
    bs = summary.get("boxscore", {})
    teams = bs.get("teams", [])
    if not teams:
        # fall back to header
        comp = (summary.get("header", {}).get("competitions") or [{}])[0]
        teams = [{"team": c.get("team", {}),
                   "statistics": [],
                   "_homeAway": c.get("homeAway")}
                  for c in comp.get("competitors", [])]
    out = []
    for t in teams:
        team_info = t.get("team", {})
        abbrev = team_info.get("abbreviation", "")
        home_away = t.get("_homeAway") or t.get("homeAway", "")
        raw = {}
        for s in t.get("statistics", []):
            name = s.get("name")
            if name:
                raw[name] = s.get("displayValue")
        out.append({"team_abbrev": abbrev, "home_away": home_away, "stats": raw})
    return out


def _extract_scoring_plays(league, game_id, summary):
    """Parse plays[] filtered to scoringPlay=true → list of dicts."""
    plays = summary.get("plays", [])
    out = []
    for p in plays:
        if not p.get("scoringPlay"):
            continue
        period = p.get("period", {})
        clock = p.get("clock", {})
        ptype = p.get("type", {})
        # Determine scoring team from text: "[Team] Goal" / "[Player] made..."
        text = p.get("text", "")
        team_abbrev = ""
        scorer = ""
        # Try to extract team from competitors or text pattern
        comp = (summary.get("header", {}).get("competitions") or [{}])[0]
        competitors = comp.get("competitors", [])
        if p.get("homeScore", 0) > p.get("_prev_home", -1) if "_prev_home" in p else (len(out) > 0 and p["homeScore"] > out[-1]["home_score"]):
            # home scored
            for c in competitors:
                if c.get("homeAway") == "home":
                    team_abbrev = c.get("team", {}).get("abbreviation", "")
        elif len(competitors) == 2:
            # away scored (or we guess from context)
            for c in competitors:
                if c.get("homeAway") == "away":
                    team_abbrev = c.get("team", {}).get("abbreviation", "")
        out.append({
            "play_id": str(p.get("id", "")),
            "period": _parse_int(period.get("number")) if period else None,
            "period_disp": period.get("displayValue", "") if period else "",
            "clock": clock.get("displayValue", "") if clock else "",
            "away_score": _parse_int(p.get("awayScore")),
            "home_score": _parse_int(p.get("homeScore")),
            "team_abbrev": team_abbrev,
            "scorer_name": scorer,
            "play_text": text,
            "play_type": ptype.get("text", "") if ptype else "",
        })
    return out


def _extract_game_context(league, game_id, summary):
    """Parse gameInfo + header → {venue_name, venue_city, attendance, officials, home/away}."""
    gi = summary.get("gameInfo", {})
    venue = gi.get("venue", {})
    officials = [o.get("displayName", "") for o in gi.get("officials", [])]
    header = summary.get("header", {})
    comp = (header.get("competitions") or [{}])[0]
    home_team = ""
    away_team = ""
    for c in comp.get("competitors", []):
        ab = c.get("team", {}).get("abbreviation", "")
        if c.get("homeAway") == "home":
            home_team = ab
        else:
            away_team = ab
    import json
    return {
        "venue_name": venue.get("fullName", ""),
        "venue_city": venue.get("address", {}).get("city", ""),
        "attendance": _parse_int(gi.get("attendance")),
        "officials": json.dumps(officials) if officials else "[]",
        "home_team": home_team,
        "away_team": away_team,
    }


def _snapshot_rosters(league, team_abbrev, players):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with closing(_db()) as con:
        con.executemany(
            "INSERT INTO roster_snap(captured_at,league,team_abbrev,player_id,name,jersey,position) "
            "VALUES(?,?,?,?,?,?,?)",
            [(now, league, team_abbrev, p["player_id"], p["name"], p["jersey"], p["position"])
             for p in players])
        con.commit()


# Column order for the team_game_stats INSERT, paired with the ESPN key and the
# parser each one needs. Was 38 positional `?` against a 38-item tuple, which is
# a correctness hazard nobody can eyeball: insert a column in the middle and every
# value after it shifts one to the left, silently, into a column of the same type.
_TEAM_STAT_COLUMNS = (
    # (column, espn key, parser)
    ("fgm_fga", "fieldGoalsMade-fieldGoalsAttempted", None),
    ("fg_pct", "fieldGoalPct", _parse_real),
    ("tpm_tpa", "threePointFieldGoalsMade-threePointFieldGoalsAttempted", None),
    ("tp_pct", "threePointFieldGoalPct", _parse_real),
    ("ftm_fta", "freeThrowsMade-freeThrowsAttempted", None),
    ("ft_pct", "freeThrowPct", _parse_real),
    ("rebounds", "totalRebounds", _parse_int),
    ("off_rebounds", "offensiveRebounds", _parse_int),
    ("def_rebounds", "defensiveRebounds", _parse_int),
    ("assists", "assists", _parse_int),
    ("steals", "steals", _parse_int),
    ("blocks", "blocks", _parse_int),
    ("turnovers", "turnovers", _parse_int),
    ("fouls", "fouls", _parse_int),
    ("pts_off_to", "turnoverPoints", _parse_int),
    ("fast_break_pts", "fastBreakPoints", _parse_int),
    ("pts_in_paint", "pointsInPaint", _parse_int),
    ("largest_lead", "largestLead", _parse_int),
    ("lead_changes", "leadChanges", _parse_int),
    ("lead_pct", "leadPercentage", _parse_real),
    ("shots", "shotsTotal", _parse_int),
    ("blocked_shots", "blockedShots", _parse_int),
    ("hits", "hits", _parse_int),
    ("takeaways", "takeaways", _parse_int),
    ("giveaways", "giveaways", _parse_int),
    ("faceoffs_won", "faceoffsWon", _parse_int),
    ("faceoff_pct", "faceoffPercent", _parse_real),
    ("powerplay_goals", "powerPlayGoals", _parse_int),
    ("powerplay_opps", "powerPlayOpportunities", _parse_int),
    ("powerplay_pct", "powerPlayPct", _parse_real),
    ("shorthanded_goals", "shortHandedGoals", _parse_int),
    ("penalties", "penalties", _parse_int),
    ("penalty_min", "penaltyMinutes", _parse_int),
)


def _snapshot_team_game_stats(league, game_id, team_stats_list):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    # DUAL WRITE during the JSON migration: the blob is the new home, the columns
    # stay populated so a database migrated later than this code still reads
    # correctly. See team_stats_json — readers prefer the blob and fall back.
    # The columns are frozen, not deprecated-in-place: dropping them is a separate
    # step, after prod is backfilled.
    with closing(_db()) as con:
        has_stats = any(
            r[1] == "stats" for r in con.execute("PRAGMA table_info(team_game_stats)")
        )
        names = [c for c, _, _ in _TEAM_STAT_COLUMNS]
        for t in team_stats_list:
            s = t["stats"]
            values = {
                col: (parse(s.get(key)) if parse else s.get(key))
                for col, key, parse in _TEAM_STAT_COLUMNS
            }
            cols = ["league", "game_id", "captured_at", "team_abbrev", "home_away"] + names
            row = [league, game_id, now, t["team_abbrev"], t["home_away"]] + [
                values[c] for c in names
            ]
            if has_stats:
                cols.append("stats")
                row.append(stats_to_json(league, values))
            con.execute(
                "INSERT OR REPLACE INTO team_game_stats(%s) VALUES(%s)"
                % (",".join(cols), ",".join("?" * len(cols))),
                row,
            )
        con.commit()


def _snapshot_scoring_plays(league, game_id, plays):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with closing(_db()) as con:
        con.executemany(
            "INSERT OR IGNORE INTO scoring_plays("
            "league,game_id,play_id,captured_at,period,period_disp,clock,"
            "away_score,home_score,team_abbrev,scorer_name,play_text,play_type"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(league, game_id, p["play_id"], now,
              p["period"], p["period_disp"], p["clock"],
              p["away_score"], p["home_score"], p["team_abbrev"],
              p["scorer_name"], p["play_text"], p["play_type"])
             for p in plays])
        con.commit()


def _snapshot_game_context(league, game_id, ctx):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with closing(_db()) as con:
        con.execute(
            "INSERT OR REPLACE INTO game_context("
            "league,game_id,captured_at,home_team,away_team,"
            "venue_name,venue_city,attendance,officials"
            ") VALUES(?,?,?,?,?,?,?,?,?)",
            (league, game_id, now,
             ctx["home_team"], ctx["away_team"],
             ctx["venue_name"], ctx["venue_city"],
             ctx["attendance"], ctx["officials"]))
        con.commit()


def _snapshot_boxscore_full(league, game_id):
    """One call snapshots team_game_stats + scoring_plays + game_context for a game."""
    try:
        summary = _fetch_summary(league, game_id)
    except Exception:
        return  # game not available yet (pre-game) — silently skip
    team_stats = _extract_team_stats(league, game_id, summary)
    if team_stats:
        _snapshot_team_game_stats(league, game_id, team_stats)
    plays = _extract_scoring_plays(league, game_id, summary)
    if plays:
        _snapshot_scoring_plays(league, game_id, plays)
    ctx = _extract_game_context(league, game_id, summary)
    _snapshot_game_context(league, game_id, ctx)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))


# Export the underscore-prefixed helpers; `from _core import *` must keep
# reaching them and the default import-* rule hides a leading underscore.
__all__ = [n for n in dir() if not n.startswith("__")]
