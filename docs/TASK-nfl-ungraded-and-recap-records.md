# TASK: NFL props that never grade, and recaps citing pre-game records

Repo: `/root/legendarypicks`, branch `dev`. Written 2026-10-04. Same rules as
`logs/TASK-nhl-nba-props.md`: dev database or `/tmp` copies only, never prod; no registry, cron,
systemd, `/etc` or `.env` edits; no restarts; separate commits with explicit paths; no em dashes;
`grep -E`, not `rg`. Load the project skills first (`published-first`, `fail-loudly`,
`honest-data-ui`, `falsify-before-merge`).

## 1. 73 of 124 NFL player-market lines never grade

Measured on prod for game 9921 (DAL 34 @ HOU 30, ESPN 401872967, 2026-10-04): 3,498 props from
12 sources; only `receiving_yards`, `rushing_yards`, `receptions`, `passing_yards` and
`field_goals_made` have `prop_results`. These never do: `rushing_receiving_yards`,
`passing_rushing_yards`, `rush_attempts`, `pass_attempts`, `pass_completions`,
`passing_touchdowns`, `longest_reception`, `kicking_points`, `interceptions_thrown`, `targets`,
`sacks`, `total_rush_attempts`, `total_passing_attempts`, `total_touchdowns`,
`total_kicking_points`, `longest_rushing_attempt`. The game was decided by three rushing touchdowns
and no touchdown line settles.

The stored ESPN summary (`game_summaries`) carries passing C/ATT, YDS, TD, INT, SACKS; rushing CAR,
YDS, TD, LONG; receiving REC, YDS, TD, LONG, TGTS; kicking FG, XP, PTS; defensive SACKS.

Deliver: for each market above, either a settlement mapping from the stored box score (and the
stat it reads), or the reason it cannot be graded from what we store (state it; do not guess a
stat). Prove each new mapping by settling game 9921 on a `/tmp` copy and hand-checking 5 props
per market against the box score. Report graded/ungraded counts before and after.

## 2. Recaps cite the record from before the game

`game_story` for 401872967 (generated 2026-10-04 20:14:27, minutes after the final) says Dallas's
win dropped "the Texans to 0-3". The scoreboard row has Houston 0-4. `core_stories.py` builds team
facts from `espn.team_strength_standings` at generation time; right after a final those standings
can still be pre-game. Confirm the cause (the cached standings response, if kept), then make a
finished game's recap use records that include the game (the game's own final scoreboard row, or
wait until the standings include it). Add a test with this exact case. List other recaps from
10-04 whose cited record disagrees with the post-game scoreboard.
