TASK: two defects in the sports picks ledger you built in /root/lp-sport-first-nav.
Both are in UNCOMMITTED work: backend/routers/games/predictions.py.

FILES YOU MAY TOUCH
  backend/routers/games/predictions.py
  backend/test_sports_predict_api.py
Do NOT touch: backend/routers/props.py, components/Props/*, ops/, /etc, systemd,
cron, or any shared util. props.py and MarketSlateBoard.tsx were rewritten on
`dev` today and will conflict.

--------------------------------------------------------------------
BUG 1 — a tie in a non-draw league leaves picks open forever, silently.

_DRAW_LEAGUES is {mls, lcup, wc}. _published_winning_side returns None for any
tie outside that set and settle_sports_picks does `continue`. NFL regular-season
ties are real (~1-2 a season). Reproduced against your current file:

    settled: 1
      G1 side=A -> win            (decided game, 17-20)
      G2 side=A -> OPEN FOREVER   (17-17 tie)
      G2 side=B -> OPEN FOREVER

    tie -> winning side, per league offered:
    {'mlb': None, 'nba': None, 'wnba': None, 'nhl': None, 'nfl': None,
     'ncaaf': None, 'mls': 'D', 'lcup': 'D', 'wc': 'D', 'atp': None, 'wta': None}

The deeper problem is that None is ALSO what an unparseable or missing payload
returns, so a permanent condition and "try again later" are handled identically
and neither is reported. Decide what a tie means for a league that does not
offer D as a pick -- both sides void, or both sides lose -- and make the
unsettleable case VISIBLE rather than a silent `continue`.

BUG 2 — settlement runs inside a GET handler.

settle_sports_picks() is called from GET /api/sports/picks/me (line ~351). Every
page load scans all unsettled picks across all leagues and writes to them. There
is no timer and no cron: I checked /etc/systemd/system, ops/systemd, and root's
crontab. Consequences: nothing settles unless someone opens their picks page, and
concurrent readers become concurrent writers on SQLite.

The pattern already exists one directory over. backend/routers/esports/picks.py:408
exposes POST /api/esports/picks/settle, documented "for a cron or manual trigger".
Match it. Do not add a systemd timer or cron entry yourself -- name what should be
scheduled and stop.

--------------------------------------------------------------------
ALSO: test_non_soccer_draw_is_rejected reads like coverage of BUG 1 and is not.
It asserts that SUBMITTING side="D" for NBA returns 400 -- the input path. No test
covers a non-draw-league game that ENDS tied, which is the settlement path.

ACCEPTANCE
- A tie in nfl/ncaaf/nba/mlb/nhl/wnba/atp/wta resolves to a stated outcome, and a
  test asserts it by running settle_sports_picks() end to end, not by calling
  _published_winning_side directly.
- A genuinely unsettleable pick is reported, not skipped in silence.
- Settlement is reachable without a GET, and GET /api/sports/picks/me no longer
  writes.
- Say which command or timer should own the schedule. Do not install it.
- Full backend suite green on BOTH databases:
    LP_DB_PATH=data/picks.dev.db PYTHONPATH=$PWD venv/bin/python -m pytest -q
    LP_DB_PATH=data/picks.db     PYTHONPATH=$PWD venv/bin/python -m pytest -q
