# Reference: NFL tiebreaking procedures

Copied verbatim (text only, list numbering lost in extraction; steps are in the page's order) from
nfl.com, "NFL Tiebreaking Procedures", https://www.nfl.com/standings/tie-breaking-procedures,
fetched 2026-10-11. `backend/nfl_seeding.py` implements it. The draft-order section that follows
on the page is not copied.

```
To Break A Tie Within A Division
If, at the end of the regular season, two or more clubs in the same division finish with identical won-lost-tied percentages, the following steps will be taken until a champion is determined.
Two Clubs
Head-to-head (best won-lost-tied percentage in games between the clubs).
Best won-lost-tied percentage in games played within the division.
Best won-lost-tied percentage in common games.
Best won-lost-tied percentage in games played within the conference.
Strength of victory in all games.
Strength of schedule in all games
Best combined ranking among conference teams in points scored and points allowed in all games.
Best combined ranking among all teams in points scored and points allowed in all games.
Best net points in common games.
Best net points in all games.
Best net touchdowns in all games.
Coin toss
Three or More Clubs
(Note: If two clubs remain tied after one-or-more clubs are eliminated during any step, tiebreaker restarts at Step 1 of two-club format. If three clubs remain tied after a fourth club is eliminated during any step, tiebreaker restarts at Step 1 of three-club format.)
Head-to-head (best won-lost-tied percentage in games among the clubs).
Best won-lost-tied percentage in games played within the division.
Best won-lost-tied percentage in common games.
Best won-lost-tied percentage in games played within the conference.
Strength of victory in all games.
Strength of schedule in all games.
Best combined ranking among conference teams in points scored and points allowed in all games.
Best combined ranking among all teams in points scored and points allowed in all games.
Best net points in common games.
Best net points in all games.
Best net touchdowns in all games.
Coin toss
To Break A Tie For The Wild-Card Team
If it is necessary to break ties to determine the three Wild-Card clubs from each conference, the following steps will be taken.
If the tied clubs are from the same division, apply division tiebreaker.
If the tied clubs are from different divisions, apply the following steps.
Two Clubs
Head-to-head, if applicable.
Best won-lost-tied percentage in games played within the conference.
Best won-lost-tied percentage in common games, minimum of four.
Strength of victory in all games.
Strength of schedule in all games.
Best combined ranking among conference teams in points scored and points allowed in all games.
Best combined ranking among all teams in points scored and points allowed in all games.
Best net points in conference games.
Best net points in all games.
Best net touchdowns in all games.
Coin toss.
Three or More Clubs
(Note: If two clubs remain tied after one-or-more clubs are eliminated during any step, tiebreaker restarts at Step 1 of two-club format. If three clubs remain tied after a fourth club is eliminated during any step, tiebreaker restarts at Step 2 of three-club format.)
Apply division tiebreaker to eliminate all but the highest ranked club in each division prior to proceeding to step 2. The original seeding within a division upon application of the division tiebreaker remains the same for all subsequent applications of the procedure that are necessary to identify the two Wild-Card participants.
Head-to-head sweep. (Applicable only if one club has defeated each of the others or if one club has lost to each of the others.)
Best won-lost-tied percentage in games played within the conference.
Best won-lost-tied percentage in common games, minimum of four.
Strength of victory in all games.
Strength of schedule in all games.
Best combined ranking among conference teams in points scored and points allowed in all games.
Best combined ranking among all teams in points scored and points allowed in all games.
Best net points in conference games.
Best net points in all games.
Best net touchdowns in all games.
Coin toss
When the first Wild Card team has been identified, the procedure is repeated to name the second and third Wild Card (i.e., eliminate all but the highest-ranked club in each division prior to proceeding to Step 2). In situations in which three teams from the same division are involved in the procedure, the original seeding of the teams remains the same for subsequent applications of the tiebreaker if the top-ranked team in that division qualifies for a Wild Card berth.
Other Tie-Breaking Procedures
Only one club advances to the playoffs in any tie-breaking step. Remaining tied clubs revert to the first step of the applicable division or Wild Card tie-breakers. As an example, if two clubs remain tied in any tie-breaker step after all other clubs have been eliminated, the procedure reverts to Step 1 of the two-club format to determine the winner. When one club wins the tiebreaker, all other clubs revert to Step 1 of the applicable two-club or three-club format.
In comparing records against common opponents among tied teams, the best won-lost-tied percentage is the deciding factor, since teams may have played an unequal number of games.
To determine home-field priority among division winners, apply Wild Card tiebreakers.
To determine home-field priority for Wild Card qualifiers, apply division tiebreakers (if teams are from the same division) or Wild Card tiebreakers (if teams are from different divisions).
To determine the best combined ranking among conference team's in points scored and points allowed, add a team's position in the two categories, and the lowest score wins. For example, if Team A is first in points scored and second in points allowed, its combined ranking is "3." If Team B is third in points scored and first in points allowed, its combined ranking is "4." Team A then wins the tiebreaker. If two teams are tied for a position, both teams are awarded the ranking as if they held it solely. For example, if Team A and Team B are tied for first in points scored, each team is assigned a ranking of "1" in that category, and if Team C is third, its ranking will still be "3."
```
