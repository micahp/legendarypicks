TASK: prove the remaining settlers against REAL DATA, in this worktree only.

WHY THIS EXISTS. The tennis settler shipped with green unit tests and had never
once run against a real database. It turned out to work -- 480 ATP props settled,
0 errors, grades verified against the published scoreboard -- but nobody knew
that until it was run. A suite written by the author of the code cannot catch the
author's own misreading of a market. The point of this task is EVIDENCE, not more
tests.

SCOPE. Work only inside /root/lp-sport-first-nav. Its backend/data/picks*.db are
COPIES taken from live; write to them freely. Do NOT touch /root/legendarypicks,
do not deploy, do not restart anything, do not push.

--------------------------------------------------------------------
THE METHOD, which is the actual deliverable

For each settler below, in this order:

1. BASELINE. Count props on games that have already finished, and how many are
   settled and how many are GRADED (actual_value NOT NULL). Settled-but-ungraded
   is the failure this catches.

     SELECT g.league, COUNT(*) props,
            SUM(pr.prop_id IS NOT NULL) settled,
            SUM(pr.actual_value IS NOT NULL) graded
     FROM props p JOIN prop_games g ON g.id=p.game_id
     LEFT JOIN prop_results pr ON pr.prop_id=p.id
     WHERE g.date < date('now') GROUP BY 1;

2. RUN IT for real (dry-run only proves it would try):
     LP_DB_PATH=data/picks.dev.db python3 settle_props.py --league <lg>

3. VERIFY THE GRADES AGAINST THE PUBLISHER, not against the run's own summary.
   Pull 5+ settled props from one event, pull that event's scoreboard snapshot,
   and check every actual_value by hand against the published result. Include
   BOTH sides of an over/under: an under whose `hit` agrees with its over is a
   sign the side logic is inverted.

4. BEFORE FILING A DEFECT, CHECK WHAT THE MARKET MEANS. I nearly reported
   `total_games` as broken because Zverev's actual came back 14 while the match
   had 26 games. It is games won by THAT PLAYER, and the way to know is the data:
   two players carry the prop in 101 of 122 matches, and lines cluster 8.5..13.5.
   A match-total market would be one prop per match at 20..23. Measure the market
   before calling the settler wrong.

5. REPORT counts before and after, the verified sample, and anything you could
   NOT verify. "Evidence unavailable" is a finding, not something to skip.

--------------------------------------------------------------------
WHAT TO PROVE, in priority order

A. WORLD CUP (settlement/wc_settle.py). The worst signal on the board: prod has
   392 wc props with a settled_at and ZERO with an actual_value. A settled count
   that grades nothing is presence, not integrity. Find out whether wc_settle
   fixes that or reproduces it. dev has 1,128 wc props, 0 settled.

B. NFL (settlement/boxscore_extract.py). Two fixes landed here and neither has
   been proven on real data: ESPN label casing (NFL publishes YDS where the maps
   expect Yds) and made/attempted strings ("21/33" for C/ATT, FG/XP). Verify a
   kicking prop and a passing prop specifically -- those are the two the
   numerator change touches. dev has 68 nfl props on finished games, 0 settled.

C. UFC. dev has 603 props on finished games, 0 settled, while prod is at 95.5%.
   A dev-only test proves nothing about UFC today. Establish whether the dev gap
   is a missing run or a missing capability.

D. MLB and MLS are at 85.7% and 78.3% on dev. Do NOT re-run these. Instead find
   out what the remaining 14% and 22% ARE -- one named reason per bucket. An
   unsettled prop is either void, unmappable, pending, or a defect, and right now
   nobody knows which.

--------------------------------------------------------------------
NOT IN SCOPE

- Do not add set_betting back. It was removed from the Bovada tennis parser on
  dev: "<Player> 2 - 0" is the match scoreline told from one side, not a measure
  of a player's performance, and nothing in player_game_logs can chart it. If you
  see set_betting props in this worktree's database copies, they predate that.
- Do not change core_markets.py or routers/props.py; both were rewritten on dev
  today and will conflict.
