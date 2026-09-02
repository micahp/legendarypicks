"""Game stories: the preview before kickoff and the recap after it.

Lifted out of `_core.py`, the last and largest of its unrelated concerns. Owns
`generate_game_story`, the staleness rule that decides a preview has outlived
the game it previews, and the background kicker that writes them.

Like `core_snapshots`, everything it needs from `_core` is imported INSIDE the
function that uses it. `_core.DB` and `_core._db` are patch targets in seven
test files, and a module-level binding would capture the real objects once at
import and make those patches silently ineffective here. A call-time lookup
resolves through `_core`'s namespace on every call, so patches apply and no
import cycle forms — `_core` imports this module, not the other way round.
"""
import datetime as dt
import json
import os
import re
import threading as _threading
from contextlib import closing

import espn_client as espn
# The 08-12 split moved the prop-form block here and left these two behind in
# core_markets. `routers/props.py` still reached them through `from _core import *`,
# so nothing raised until a code path that ran outside a request did — the recap
# sweep, which then crashed on its first MLB game every three hours for two days.
# core_markets imports nothing, so this is a leaf import and cannot cycle.
from core_markets import _MARKET_STAT_KEY, _base_market


def _db():
    """`_core._db`, resolved at call time so test patches are honoured."""
    from _core import _db as _core_db
    return _core_db()


def _deepseek_chat(*args, **kwargs):
    """`_core._deepseek_chat`, resolved at call time for the same reason."""
    from _core import _deepseek_chat as _chat
    return _chat(*args, **kwargs)


_TIMESTAMP_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _story_is_stale_preview(generated_at, state, start_time) -> bool:
    """True when a cached story was written BEFORE kickoff and the game has since finished.

    A preview and a recap are different pieces of writing, and the cache could not tell
    them apart: the first story written for a game was final forever, so a game detail page
    kept previewing a match that ended hours ago. There is no column recording which kind a
    row holds, and there does not need to be — a story generated before the opening whistle
    is a preview by construction.

    Both sides are compared in UTC: generated_at is written by SQLite's datetime('now'),
    which is UTC, and ESPN's start time is a Zulu instant."""
    if (state or "").lower() != "post" or not generated_at or not start_time:
        return False
    try:
        written = str(generated_at).strip().replace("T", " ").rstrip("Z")[:16]
        kickoff = str(start_time).strip().replace("T", " ").rstrip("Z")[:16]
        # Both must actually look like timestamps. A lexical compare on anything else is
        # not a time comparison: "12345" sorts before "2026-08-10", which would call a
        # malformed row a stale preview and regenerate it on every single view.
        if not (_TIMESTAMP_PREFIX.match(written) and _TIMESTAMP_PREFIX.match(kickoff)):
            return False
        return written < kickoff
    except Exception:
        return False


_SEASON_YEAR = re.compile(r"\b(19|20)\d{2}\b")


def _season_year_from_name(name):
    m = _SEASON_YEAR.search(str(name or ""))
    return int(m.group(0)) if m else None


def _short_day(game_date):
    """'Aug 18' from a stored game_date, or '' when there is none."""
    if not game_date:
        return ""
    try:
        import datetime as _d
        return _d.date.fromisoformat(str(game_date)[:10]).strftime("%b %-d")
    except Exception:
        return ""


def _game_start_instant(lg: str, game_id: str):
    """The game's own UTC instant, for callers that did not pass start_time.

    `game_result` does NOT carry a date (measured 2026-08-19: its keys are
    scores/state/winner and nothing else), which is why reading `gr["date"]`
    silently produced no date at all. The scoreboard row has one and two of the
    three callers pass it as `start_time`; the serving route in
    routers/game_extras does not, because it only has a league and a game id.

    The summary payload carries it at `header.competitions[0].date`, and
    `espn.summary` is already fetched for this game with a TTL, so this costs
    no request.
    """
    try:
        d = espn.summary(lg, game_id) or {}
        comps = ((d.get("header") or {}).get("competitions") or [{}])
        return (comps[0] or {}).get("date")
    except Exception:
        return None


def _game_season_year(lg: str, game_id: str):
    """The season this game belongs to, per the publisher — an int year or None.

    Read from the summary payload's header.season, NOT from start_time: an NFL
    game in January belongs to the prior season, and the calendar year of
    kickoff would call last season's logs stale. The summary was already fetched
    by game_result earlier in generate_game_story, so this is an in-memory hit.
    """
    try:
        d = espn.summary(lg, game_id)
        season = (d or {}).get("header", {}).get("season") or {}
        year = season.get("year")
        if isinstance(year, int):
            return year
        return _season_year_from_name(season.get("name"))
    except Exception:
        return None


def _logs_predate_season(game_season, newest_log_season) -> bool:
    """True when a league's newest game log is older than the season a game is in.

    Only True when BOTH are known: an unknown game season or an unknown newest
    log must not suppress the form section on a guess.
    """
    return (game_season is not None and newest_log_season is not None
            and newest_log_season < game_season)


def generate_game_story(lg: str, game_id: str, refresh: bool = False,
                        home: str = None, away: str = None,
                        state: str = None, start_time: str = None) -> dict:
    """Generate (or fetch cached) the AI blurb for one game, grounded ONLY in our
    records/streaks/form. Shared by the /story endpoint (lazy, on view) and the
    pregenerate_game_stories job (eager, when a game is first discovered).

    home/away (team abbrevs) let the pre-game path work: a scheduled game has no
    `scores` yet, so the team abbrevs come from the scoreboard instead.

    state/start_time come from the same scoreboard row and cost no extra request. They are
    what lets a preview be replaced by a recap once the game is final — without them the
    behaviour is exactly as before, so every existing caller keeps working."""
    lg = lg.lower()
    cached = None
    stale_preview = False
    with closing(_db()) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS game_story(
            league TEXT, game_id TEXT, story TEXT, generated_at TEXT, has_form INTEGER DEFAULT 0,
            PRIMARY KEY(league, game_id))""")
        cols = [c["name"] for c in con.execute("PRAGMA table_info(game_story)")]
        if "has_form" not in cols:
            con.execute("ALTER TABLE game_story ADD COLUMN has_form INTEGER DEFAULT 0")
            con.commit()
        # has_stakes: story was written WITH the stakes context (stakes.py). A has_form story
        # from before the stakes engine is provisional the same way thin pre-form stories
        # were: regenerate once stakes are computable, then it's final.
        if "has_stakes" not in cols:
            con.execute("ALTER TABLE game_story ADD COLUMN has_stakes INTEGER DEFAULT 0")
            con.commit()
        # form_suppressed: the form section was SKIPPED because the league's newest
        # player_game_logs season is older than this game's season (mls/ncaaf/nfl logs
        # stop at 2025). has_form stays 1 when matchup context is present, so the cache
        # would otherwise treat the story as final and it would never come back to pick
        # up the form it was denied the day the logs catch up. This flag is the reason
        # it is allowed — and required — to regenerate once.
        if "form_suppressed" not in cols:
            con.execute("ALTER TABLE game_story ADD COLUMN form_suppressed INTEGER DEFAULT 0")
            con.commit()
        if not refresh:
            cached = con.execute(
                "SELECT story, has_form, has_stakes, form_suppressed, generated_at FROM game_story "
                "WHERE league=? AND game_id=?", (lg, game_id)).fetchone()
            stale_preview = cached and _story_is_stale_preview(
                cached["generated_at"], state, start_time)
            if cached and cached["has_form"] and not cached["form_suppressed"] and not stale_preview:
                import stakes as _stakes_mod
                # Final unless this league HAS a stakes model and the story predates it —
                # that one case regenerates once (below) and becomes final with has_stakes=1.
                if cached["has_stakes"] or lg not in _stakes_mod.SUPPORTED:
                    return {"league": lg, "game_id": game_id, "story": cached["story"], "cached": True}

    try:
        gr = espn.game_result(lg, game_id)
        teams = list((gr.get("scores") or {}).keys())
    except Exception:
        gr, teams = {}, []
    # Pre-game fallback: a scheduled game has no scores yet — use the scoreboard's
    # home/away abbrevs so we can still write the preview when the game is discovered.
    if len(teams) != 2 and away and home:
        teams = [away, home]
    # A finished scoreless game (UFC, tennis walkover): the summary endpoint 404s for
    # these, so `gr` carries nothing and teams would be empty. The scoreboard snapshot
    # has both sides — use it, or the generator bails before ever grounding the result.
    if len(teams) != 2:
        try:
            from _core import _snapshot_result_info
            snap_teams = _snapshot_result_info(lg, game_id)
            if snap_teams and snap_teams.get("home_name") and snap_teams.get("away_name"):
                teams = [snap_teams["home_name"], snap_teams["away_name"]]
        except Exception:
            pass
    if len(teams) != 2:
        return {"league": lg, "game_id": game_id,
                "story": cached["story"] if cached else None, "cached": bool(cached)}
    smap = espn.team_strength_map(lg)
    try:  # quality rank: position in the strength table (same rows smap is built from)
        _rank = {r["abbrev"]: i + 1 for i, r in enumerate(espn.team_strength(lg))}
    except Exception:
        _rank = {}

    def facts(ab):
        s = smap.get(ab) or {}
        rk = f", quality rank #{_rank[ab]} of {len(_rank)}" if ab in _rank else ""
        # ".500 winning percentage", not "0.5 win%". Measured 2026-08-19: two of
        # three runs turned `0.5 win%` into "leads the AL West by half a game",
        # a standings claim that is nowhere in the facts, and Liquid made the
        # same misread as "a +0.5 win percentage edge". A bare 0.5 beside a
        # division lead reads as games-back to anyone who knows the sport.
        wp = s.get("win_pct")
        try:
            wp = f"{float(wp):.3f}".lstrip("0")
        except (TypeError, ValueError):
            wp = str(wp)
        return (f"{s.get('name', ab)} ({ab}): {s.get('wins')}-{s.get('losses')}, "
                f"{wp} winning percentage, streak {s.get('streak')}, "
                f"last-10 {s.get('last10')}, "
                f"run differential {s.get('differential')}{rk}")
    # THE DATE OF THIS GAME. Without it the writer has no anchor for "yesterday",
    # "Tuesday" or "the series opener", and a model with no date produces one
    # anyway: measured 2026-08-19, every candidate model named a weekday for the
    # last meeting and every one was wrong. The last-five results carry their own
    # dates now too (matchup_context._when), so relative language is checkable.
    # New York day, DST-aware, because that is how every game in the store is
    # bucketed and a UTC date is the previous evening in the US.
    when = ""
    _start = start_time or _game_start_instant(lg, game_id)
    if _start:
        try:
            from espn_client.scoreboard import _ny_date
            import datetime as _d
            _m = _d.datetime.fromisoformat(str(_start).replace("Z", "+00:00"))
            when = f" Date: {_ny_date(_m).strftime('%A %b %-d, %Y')}."
        except Exception:
            when = ""
    grounding = (f"Matchup: {teams[0]} vs {teams[1]}. Game state: {gr.get('state')}.{when}\n"
                 f"{facts(teams[0])}\n{facts(teams[1])}")

    # THE RESULT. It was never in the grounding — `gr` carried scores and a winner and none
    # of it was passed on, so a finished game's facts said only "state: post". The soccer
    # recaps read fine because matchup_context's form line happens to include the scoreline;
    # MLB has no such line, so the Reds-Nationals recap opened on a prop and never said the
    # Nationals won 7-1. A recap that omits the score is not a recap.
    scores = gr.get("scores") or {}
    if scores and (gr.get("state") or "").lower() == "post":
        line = ", ".join(f"{ab} {int(v) if float(v).is_integer() else v}"
                         for ab, v in scores.items())
        winner = gr.get("winner")
        grounding += (f"\nFINAL SCORE: {line}."
                      + (f" {winner} won." if winner else " The game was drawn."))
    # A finished game with NO score (UFC, tennis walkover) must still be grounded on
    # who won. `gr` carries no winner for these (UFC's summary endpoint 404s), so read
    # the scoreboard snapshot — the same payload the board already serves. Never leave
    # a finished game's result to the model to invent.
    if (not scores) and (state or gr.get("state") or "").lower() == "post":
        try:
            from _core import _snapshot_result_info
            snap = _snapshot_result_info(lg, game_id)
            if snap:
                winner_name = snap.get("winner_name") or snap.get("winner_abbrev")
                if snap.get("is_draw"):
                    grounding += "\nRESULT: The match was drawn."
                elif winner_name:
                    detail = []
                    if snap.get("outcome_method"):
                        detail.append(snap["outcome_method"])
                        if snap.get("outcome_round"):
                            detail.append(f"R{snap['outcome_round']}")
                            if snap.get("outcome_clock"):
                                detail.append(snap["outcome_clock"])
                    elif snap.get("sets", {}).get("home") and snap.get("sets", {}).get("away"):
                        # Name each side's set line so the order cannot be misread:
                        # "Parks won sets 1-6, 6-4, 2-6" vs "Eala won 6-4..." — a bare
                        # "1-6 | 6-4 | 2-6" was read backwards by the model (measured
                        # 2026-08-20, the winner's first set became the loser's).
                        hn = snap.get("home_name") or "home"
                        an = snap.get("away_name") or "away"
                        hs = snap["sets"]["home"] or []
                        as_ = snap["sets"]["away"] or []
                        if len(hs) == len(as_):
                            sets_line = "; ".join(
                                f"{hn} {h}-{a} {an}" for h, a in zip(hs, as_))
                            detail.append(f"({sets_line})")
                    suffix = f" ({', '.join(detail)})" if detail else ""
                    grounding += f"\nRESULT: {winner_name} won{suffix}."
                elif snap.get("sets", {}).get("home") is not None:
                    # Sets present but no winner derivable (e.g. abandoned mid-match) —
                    # state the sets, not a guess.
                    grounding += "\nRESULT: sets " + " | ".join(
                        f"{h}-{a}" for h, a in zip(
                            snap["sets"]["home"] or [], snap["sets"]["away"] or [])) + "."
        except Exception:
            pass

    # Stakes: what each team is playing for in THIS game (stakes.py — certain facts only).
    try:
        import stakes as _stakes
        stakes_lines = _stakes.for_matchup(lg, teams[0], teams[1])
    except Exception:
        stakes_lines = []
    if stakes_lines:
        grounding += "\nWhat's at stake in this game:\n" + "\n".join(stakes_lines)

    # Player form, from the prop board first and then from our own game logs.
    #
    # The prop path stays because it is TARGETED: it surfaces the players whose markets we
    # actually price, which is what a reader of this product is looking at. But it was the
    # only path, and props exist for MLB, MLS, UFC and the World Cup — nowhere else. Every
    # NBA, NFL and NHL story was written with an empty form section while 232,669 player
    # game logs sat one table over. player_form reads those directly, keyed on the two
    # clubs, and states the season it read so an out-of-date league (MLS logs stop at 2025)
    # cannot be passed off as current.
    # The form section is only honest if the logs are from the season this game
    # is in. MLS logs stop at 2025 while 2026 games are being previewed; the
    # season label player_form adds was being stripped by the writer, so "last
    # five" from nine months ago read as current form (measured: game 761719,
    # "Kelvin Yeboah ... no goals in his last five matches" — those five are
    # 2025-09-14..2025-11-25). Suppress the whole section instead: a preview
    # with no form line is honest; one with last year's form presented as this
    # year's is not. The records and the matchup context are current and stay.
    game_season = _game_season_year(lg, game_id)
    with closing(_db()) as con:
        newest_log_season = con.execute(
            "SELECT MAX(season) FROM player_game_logs WHERE league=?", (lg,)).fetchone()[0]
    logs_stale = _logs_predate_season(game_season, newest_log_season)

    form_lines, seen = [], set()
    if not logs_stale:
        with closing(_db()) as con:
            prs = con.execute(
                """SELECT pl.id, pl.name, p.market, COUNT(*) c FROM props p
                  JOIN prop_games g ON g.id = p.game_id JOIN players pl ON pl.id = p.player_id
                  WHERE g.espn_event_id = ? GROUP BY pl.id, p.market ORDER BY c DESC""",
                (str(game_id),)).fetchall()
            for r in prs:
                if r["id"] in seen or len(form_lines) >= 8:
                    continue
                sk = _MARKET_STAT_KEY.get(lg, {}).get(_base_market(r["market"]))
                if not sk:
                    continue
                logs = con.execute(
                    """SELECT stats, game_date FROM player_game_logs WHERE player_id=?
                       ORDER BY COALESCE(game_date,'') DESC, CAST(game_no AS INTEGER) DESC LIMIT 5""",
                    (r["id"],)).fetchall()
                # `sk` is a stat key OR a list of them: two MLB markets are compound
                # ("total_hits,_runs_and_rbis" -> ["H","R","RBI"]). The chart path in
                # routers/props.py already reads both shapes; this one assumed a string
                # and raised `unhashable type: 'list'` the moment it saw a compound —
                # which is every MLB slate, so no story ever got past this line.
                # Same rule as the chart, deliberately: sum the keys treating a missing
                # one as 0, and keep the game only if at least one key was published.
                vals = []
                for x in logs:
                    st = json.loads(x["stats"])
                    if isinstance(sk, list):
                        if any(st.get(k) is not None for k in sk):
                            vals.append((_short_day(x["game_date"]),
                                         sum(st.get(k) or 0 for k in sk)))
                    else:
                        if st.get(sk) is not None:
                            vals.append((_short_day(x["game_date"]), st[sk]))
                if len(vals) >= 3:
                    # DATED, not a bare array. A list of five numbers under the heading
                    # "most recent first" was read BACKWARDS by every model tested
                    # (2026-08-19): Mike Trout's combined H+R+RBI ran
                    # [0, 0, 1, 1, 5] newest-first, and three different models called the
                    # 5 "his last game" when it was five games ago. Sports game logs are
                    # universally printed oldest-first, so the label loses to the
                    # convention. That inverts hot and cold streaks, which is the single
                    # claim these stories lead with.
                    shown = ", ".join(f"{d} {v}" if d else str(v) for d, v in vals)
                    form_lines.append(
                        f"{r['name']} — last 5 {_base_market(r['market'])}: {shown}")
                    seen.add(r["id"])

            if len(form_lines) < 6:
                try:
                    import player_form as _pform
                    for line in _pform.lines(lg, teams, con=con):
                        if len(form_lines) >= 6:
                            break
                        form_lines.append(line)
                except Exception:
                    pass
    if form_lines:
        grounding += "\nRecent player form (each value is dated; newest first):\n" + "\n".join(form_lines)

    # Matchup context: team form, who is producing, and — for a tournament that pairs two
    # leagues — how those leagues are faring against each other. All of it read off the
    # summary payload this game already fetches. Soccer has no props, so form_lines above
    # is always empty there and a Leagues Cup story was being written from strength ranks
    # alone: "#7 in the 36-team table" instead of "Santos have lost five straight".
    try:
        import matchup_context as _mctx
        context_lines = _mctx.context_lines(
            lg, game_id, state=state or gr.get("state"))
    except Exception:
        context_lines = []
    if context_lines:
        grounding += "\nMatchup context:\n" + "\n".join(context_lines)

    # Settled props are NOT given to the recap writer.
    #
    # They were, briefly, and the rendered page settled the question. The Reds-Nationals
    # recap came out as "CJ Abrams's 0 total bases cashed the under on his 1.5 total bases
    # line, as the Nationals, riding a three-game win streak, faced the Reds" — three prop
    # outcomes and not one mention of the 7-1 result. Handing a writer the most specific
    # numbers in the pile makes it write about them, and a prop is never the biggest thing
    # that happened in a game.
    #
    # The panel below the recap now carries every settled line with its actual value, which
    # is a better home for it: complete rather than a sampled three, and it cannot crowd out
    # the score. Re-enabling is one flag if the recap ever earns it back.
    RECAP_MENTIONS_PROPS = False
    settled_lines = []
    if RECAP_MENTIONS_PROPS and (
            (state or "").lower() == "post" or (gr.get("state") or "").lower() == "post"):
        try:
            with closing(_db()) as con:
                for r in con.execute(
                        """SELECT pl.name, p.market, p.line, p.side, r.actual_value, r.hit
                           FROM props p
                           JOIN prop_games pg ON pg.id = p.game_id
                           JOIN players pl ON pl.id = p.player_id
                           JOIN prop_results r ON r.prop_id = p.id
                           WHERE pg.espn_event_id = ? AND r.hit IS NOT NULL
                           GROUP BY pl.id, p.market, p.side
                           ORDER BY r.hit DESC LIMIT 6""", (str(game_id),)):
                    verdict = "HIT" if r["hit"] else "missed"
                    settled_lines.append(
                        f"{r['name']} {_base_market(r['market'])} {r['side']} {r['line']}: "
                        f"actual {r['actual_value']} — {verdict}.")
        except Exception:
            settled_lines = []
    if settled_lines:
        grounding += ("\nHow our published props landed in this game (state these exactly as "
                      "given; never round or restate a line):\n" + "\n".join(settled_lines))

    # Regenerate a cached story ONLY when genuinely new context arrived since it was written
    # (form for a pre-form story, stakes for a pre-stakes story). Otherwise keep it — never
    # burn an LLM call re-writing the same blurb, and never loop when a source is down.
    if cached:
        new_form = ((bool(form_lines or context_lines) and not cached["has_form"])
                    # A suppressed-form story is deliberately not final: the moment the
                    # logs catch up to the game's season it regenerates once and takes
                    # the form it was denied, then becomes final with form_suppressed=0.
                    or (bool(form_lines) and cached["form_suppressed"]))
        new_stakes = bool(stakes_lines) and not cached["has_stakes"]
        if not new_form and not new_stakes and not stale_preview:
            return {"league": lg, "game_id": game_id, "story": cached["story"], "cached": True}

    # A finished game gets a recap, not a preview. Without this the writer keeps setting up
    # a match whose result is sitting in the facts it was handed — "Chicago look to advance"
    # under a scoreline that says they already did.
    finished = (state or "").lower() == "post" or (gr.get("state") or "").lower() == "post"
    opening = ("You are a sharp sports writer. This game is OVER — write the recap, in past "
               "tense, using ONLY the facts given. The FINAL SCORE and who won come first; "
               "a recap that does not say who won is not a recap. Then what decided it and "
               "what it changed. "
               if finished else
               "You are a sharp sports writer. Set up this matchup using ONLY the facts given. ")
    system = (opening +
              "Lead priority: (1) what's at stake in this game, (2) a player or team on a clear "
              "hot or cold run, (3) record/quality context, including where these two clubs "
              "sit in the competition. Name the players the facts name. A fact marked "
              "BACKGROUND is true of every game in the competition — it is scenery, not the "
              "story, and belongs in this card only if this game is what changed it. Be "
              "specific with numbers, but NEVER "
              "state the same stat twice in different units, and never pad — if the facts are "
              "thin, one sharp sentence beats four generic ones. 1-4 sentences. Do NOT invent "
              "injuries, trades, lineup news, or anything not in the facts. No clichés, no hype, "
              "plain confident tone.")
    story = _deepseek_chat(system, grounding)
    if story:
        with closing(_db()) as con:
            con.execute("INSERT OR REPLACE INTO game_story(league, game_id, story, generated_at, has_form, has_stakes, form_suppressed) "
                        "VALUES (?,?,?,datetime('now'),?,?,?)",
                        (lg, game_id, story, 1 if (form_lines or context_lines) else 0,
                         1 if stakes_lines else 0, 1 if logs_stale else 0))
            con.commit()
    elif cached:
        # generation failed this time — keep the previous story rather than blanking it
        return {"league": lg, "game_id": game_id, "story": cached["story"], "cached": True}
    return {"league": lg, "game_id": game_id, "story": story,
            "cached": False, "has_form": bool(form_lines or context_lines)}


import threading as _threading
_story_inflight: set = set()
_story_lock = _threading.Lock()
_story_sema = _threading.Semaphore(3)  # cap concurrent DeepSeek generations

def kick_game_stories(lg: str, games: list):
    """Fire-and-forget: when a league scoreboard is fetched, warm the preview cache
    for any games we don't have a story for yet. Each generation runs in a daemon
    thread (bounded by a semaphore) so the /games response returns immediately and the
    preview is ready — or generating — by the time the user opens the game.

    This is the 'write the preview whenever we find out about the game' hook: games are
    lazy-loaded via /api/{league}/games, so that fetch is exactly when we find out."""
    lg = lg.lower()
    ids = [(str(g.get("game_id")), (g.get("home") or {}).get("abbrev"),
            (g.get("away") or {}).get("abbrev"), g.get("state"), g.get("date"))
           for g in (games or []) if g.get("game_id")]
    if not ids:
        return
    gid_list = [i[0] for i in ids]
    try:
        with closing(_db()) as con:
            con.execute("""CREATE TABLE IF NOT EXISTS game_story(
                league TEXT, game_id TEXT, story TEXT, generated_at TEXT,
                PRIMARY KEY(league, game_id))""")
            qs = ",".join("?" * len(gid_list))
            cached = {r[0]: r[1] for r in con.execute(
                f"SELECT game_id, generated_at FROM game_story WHERE league=? AND game_id IN ({qs})",
                [lg] + gid_list)}
    except Exception:
        cached = {}
    for gid, home, away, state, start_time in ids:
        # A cached story is enough UNLESS it is a preview of a game that has since ended —
        # then this scoreboard load is exactly when we find out the recap is owed, the same
        # way it is when we first find out the game exists.
        if gid in cached and not _story_is_stale_preview(cached[gid], state, start_time):
            continue
        with _story_lock:
            if gid in _story_inflight:
                continue
            _story_inflight.add(gid)
        def _run(gid=gid, home=home, away=away, state=state, start_time=start_time):
            try:
                with _story_sema:
                    generate_game_story(lg, gid, home=home, away=away,
                                        state=state, start_time=start_time)
            except Exception as e:
                print(f"[story] bg gen failed {lg} {gid}: {e}")
            finally:
                with _story_lock:
                    _story_inflight.discard(gid)
        _threading.Thread(target=_run, daemon=True).start()


# Export the underscore-prefixed helpers; `from _core import *` must keep
# reaching them and the default import-* rule hides a leading underscore.
__all__ = [n for n in dir() if not n.startswith("__")]
