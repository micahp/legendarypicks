# TASK — QA the "What decided it" panel across many games

**Type: READ-ONLY QA. You will not change any code.**

## Hard scope lock — violating any of these fails the task

- **Do NOT edit, create, or delete ANY file** except the one report file named below.
- **Do NOT** run `git` commands that write (no commit/push/checkout/merge/stash/reset).
- **Do NOT** touch host config: `/etc`, systemd units, timers, cron, nginx.
- **Do NOT** restart, kill, or start any server, tunnel, or process. The dev
  backend and frontend are already running and are NOT yours to manage.
- **Do NOT** write to any database. No `UPDATE`, `INSERT`, `DELETE`, `VACUUM`.
- **Do NOT** run machine-wide greps or scans of large directories.
- If something looks broken and you want to fix it: **report it, do not fix it.**

## Base URL (verified live 2026-08-11)

```
https://resume-stress-education-pros.trycloudflare.com
```

Do NOT use `coat-develop-rooms-prague.trycloudflare.com` — it serves stale code
and will give you wrong answers.

Confirm your base URL is the right one before starting:

```
curl -s "$BASE/api/game/mlb/401816457/props" | head -c 400
```

It MUST contain a `leaders` key. If it does not, STOP and report that.

## What you are testing

A new endpoint field `leaders` on `/api/game/{league}/{game_id}/props`, which
feeds a "What decided it" panel on the game page. It is the up-to-3 settled prop
lines that finished furthest from their own number.

**The panel is client-rendered React. You cannot verify how it LOOKS by curling
HTML — do not try, and do not grep served HTML for it.** Your job is the data
contract underneath it, across many real games.

## Method

1. Get a list of finished games. For each league in `mlb`, `nfl`, `nhl`, `nba`,
   pull a few dates of scoreboard:
   `GET $BASE/api/{league}/games?date=YYYY-MM-DD`
   MLB has by far the most settled props; prioritise it. Use dates in
   2026-07-20 .. 2026-08-10.
2. Aim for **at least 25 games total** with `state == "post"`, spread across at
   least 3 dates. Also include **at least 5 games that are NOT final**
   (`state` of `pre` or `in`) as negative cases.
3. For each game call `GET $BASE/api/game/{league}/{game_id}/props` and check
   every assertion below.

## Assertions — report each one that fails, with the game_id

For every game:

- **A1** `leaders` is always present and is a list (never missing, never null).
- **A2** `len(leaders) <= 3`.
- **A3** A game with no settled props has `leaders == []` and
  `settled_lines == 0`. A game that has not started must never produce leaders.
- **A4** `leaders` is sorted by `margin` descending.
- **A5** For every leader: `margin == abs(actual - line)`, within 0.001.
- **A6** For every leader: `cashed` is exactly `"over"` or `"under"`.
- **A7** `cashed` agrees with the numbers: if `actual > line` then `cashed`
  must be `"over"`; if `actual < line` then `"under"`.
- **A8** Every leader corresponds to a real settled prop in the same response —
  find a player in `players` with that `player_id`, holding a prop with the same
  `market` and `line` whose `result` is not null. No leader may be invented.
- **A9** No leader has a blank/empty `name` or `team`.
- **A10** Leaders are unique on `(player_id, market, line)` — the same line must
  not appear twice even though we store both its over and under side.
- **A11** `settled_lines` >= `len(leaders)`.

## Deliverable

Write **one file only**:

```
/root/legendarypicks/RESULT-whatdecidedit-qa.md
```

It must contain:

1. The exact number of games checked, broken down by league and by state.
2. A table of every FAILED assertion: assertion id, league, game_id, and the
   actual values that failed it.
3. If everything passed, say so **and** paste the raw JSON `leaders` block for
   3 different games as evidence you actually looked.
4. Any game where the leaders looked wrong to you as a sports fan even though
   the assertions passed — e.g. a leader that is obviously not what decided the
   game. Name the game and say why.

Do not summarise as "all good" without the counts. A count of zero checked games
is a FAIL, not a pass.
