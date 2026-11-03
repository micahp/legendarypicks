# PR #30 Multisport Story Run: 2026-11-03

- Run time: `2026-11-03T16:54:59Z` (America/Chicago)
- PR head: `cc5695849a9454c58ca7bfd78031dde8552ded9f`
- Database: `/root/legendarypicks/backend/data/picks.dev.db` (3,636,723,712 bytes, opened read-only)
- Slate counts: NHL today 11; NCAAF today 2; NBA tomorrow 14.
- Total stories: 27; engine runtime: 899.277 ms.
- Grader `lp-story-quality-v1.0.0` ran on 27 stories. Status counts: `{"blocked": 0, "eligible": 0, "needs-audit": 27, "review": 0}`.
- Mean rubric score: overall 85.26; NHL 85; NCAAF 82; NBA 85.93.
- Model calls: 0; network calls during generation: 0; database writes: 0; repository files modified: no.

## Scope and data handling

The pinned PR engine natively supports NBA and NFL. The NBA run used its unmodified database collector, story selector, and renderer. NHL and NCAAF used temporary, read-only adapters that supplied cutoff-filtered facts to the pinned selector and renderer. No adapter code was written to the repository.
NHL team records came from ESPN scoreboard snapshots through Nov 2. The current-season player log data ends Oct 13, so NHL player form was excluded. NHL records use W-L-OTL formatting; the runtime adapter also changes the generic home-turf phrase to home ice.
NCAAF team records came from final ESPN scoreboard snapshots through Oct 31; player logs for the two teams are current through Oct 24. NCAA conference/national rankings were not generated. Existing football statistical templates were used only for supported passing, rushing, and receiving fields.
NBA used the pinned PR data collector with the 2026-27 season roster and logs through Nov 2.
The grader received no independent mechanical claim audit, so its rubric gates should be read as editorial/provenance review signals, not factual certification or human ratings.

## Generated stories

### NHL Utah Mammoth at Toronto Maple Leafs

- Tipoff/kickoff: `2026-11-04T00:00:00Z`; angle: `records`; rubric target ID: `401892633`.
- Utah brings a 9-6-0 record into Toronto, where the 8-6-2 Leafs look to protect home ice.

### NHL Winnipeg Jets at Montreal Canadiens

- Tipoff/kickoff: `2026-11-04T00:00:00Z`; angle: `streak_clash`; rubric target ID: `401892634`.
- Montreal has won five straight at 9-3-2 and already beat Winnipeg 2-1 on Oct. 25; the 4-8-3 visitors have lost nine in a row.

### NHL Detroit Red Wings at Tampa Bay Lightning

- Tipoff/kickoff: `2026-11-04T00:00:00Z`; angle: `records`; rubric target ID: `401892635`.
- Detroit brings a 7-5-3 record into Tampa Bay, where the 8-3-2 Lightning look to protect home ice.

### NHL St. Louis Blues at New York Rangers

- Tipoff/kickoff: `2026-11-04T00:00:00Z`; angle: `losing_streak`; rubric target ID: `401892637`.
- New York has dropped four straight at 7-7-1 entering its matchup with St. Louis, which is 7-6-1.

### NHL Minnesota Wild at Philadelphia Flyers

- Tipoff/kickoff: `2026-11-04T00:00:00Z`; angle: `records`; rubric target ID: `401892638`.
- Minnesota brings a 10-3-3 record into Philadelphia, where the 4-8-4 Flyers look to protect home ice.

### NHL Vegas Golden Knights at Pittsburgh Penguins

- Tipoff/kickoff: `2026-11-04T00:00:00Z`; angle: `records`; rubric target ID: `401892639`.
- The 9-5-2 Knights have dropped two straight entering Pittsburgh, where the Penguins sit at 5-7-2.

### NHL Dallas Stars at Washington Capitals

- Tipoff/kickoff: `2026-11-04T00:00:00Z`; angle: `records`; rubric target ID: `401892640`.
- Dallas brings an 8-5-1 record into Washington, where the 8-5-0 Capitals look to protect home ice.

### NHL Colorado Avalanche at Columbus Blue Jackets

- Tipoff/kickoff: `2026-11-04T00:00:00Z`; angle: `winning_streak`; rubric target ID: `401892641`.
- Colorado brings a three-game winning streak into its matchup with Columbus, which is 5-7-0.

### NHL Edmonton Oilers at New Jersey Devils

- Tipoff/kickoff: `2026-11-04T00:30:00Z`; angle: `winning_streak`; rubric target ID: `401892636`.
- Edmonton brings a three-game winning streak into its matchup with New Jersey, which is 9-5-0.

### NHL Carolina Hurricanes at Nashville Predators

- Tipoff/kickoff: `2026-11-04T01:00:00Z`; angle: `winning_streak`; rubric target ID: `401892642`.
- Carolina brings a four-game winning streak into its matchup with Nashville, which is 5-4-5.

### NHL Anaheim Ducks at Vancouver Canucks

- Tipoff/kickoff: `2026-11-04T02:00:00Z`; angle: `records`; rubric target ID: `401892643`.
- The 6-7-1 Ducks visit Vancouver, where the 3-12-1 Canucks have dropped two straight.

### NCAAF Ohio Bobcats at Akron Zips

- Tipoff/kickoff: `2026-11-04T00:00:00Z`; angle: `streak_clash`; rubric target ID: `401866453`.
- Ohio has won five straight and sits at 6-2, while Akron has dropped six in a row at 1-7. Akron's Jordan Gant has topped 100 rushing yards in one of his last four games.

### NCAAF Buffalo Bulls at Miami (OH) RedHawks

- Tipoff/kickoff: `2026-11-04T01:00:00Z`; angle: `winning_streak`; rubric target ID: `401866454`.
- Buffalo brings a three-game winning streak into its matchup with Miami (Ohio), which is 5-3. Buffalo's Messiah Burch has topped 100 rushing yards in one of his last four games, while Miami (Ohio)'s David McComb has found the end zone in three of his last five games.

### NBA Philadelphia 76ers at Detroit Pistons

- Tipoff/kickoff: `2026-11-05T00:00:00Z`; angle: `top_four`; rubric target ID: `401909922`.
- Two of the NBA's top four teams meet in Detroit, where the 6-1 Pistons host the 7-1 76ers. Cade Cunningham is averaging 25.6 points and 6.8 assists over his last five for Detroit, while Philadelphia's Tyrese Maxey has scored at least 23 in each of his last five, including a 38-point night.

### NBA Atlanta Hawks at Washington Wizards

- Tipoff/kickoff: `2026-11-05T00:00:00Z`; angle: `records`; rubric target ID: `401909923`.
- The 4-4 Hawks visit Washington, where the 4-3 Wizards are riding a two-game winning streak. Washington's Trae Young is averaging 9 assists over his last five, while Atlanta's Jalen Johnson is averaging 8.2 assists over his last five.

### NBA Milwaukee Bucks at Boston Celtics

- Tipoff/kickoff: `2026-11-05T00:30:00Z`; angle: `losing_streak`; rubric target ID: `401909924`.
- Milwaukee has dropped three straight at 1-6 entering its matchup with Boston, which is 5-2. Milwaukee's Kel'el Ware is averaging 10.8 rebounds over his last five, while Celtics star Jayson Tatum is averaging 28 points and 7.4 assists over his last five games, including a 40-point outing.

### NBA Charlotte Hornets at Brooklyn Nets

- Tipoff/kickoff: `2026-11-05T00:30:00Z`; angle: `losing_streak`; rubric target ID: `401909925`.
- Charlotte has dropped four straight at 3-5 entering its matchup with Brooklyn, which is 1-6.

### NBA Chicago Bulls at New York Knicks

- Tipoff/kickoff: `2026-11-05T00:30:00Z`; angle: `losing_streak`; rubric target ID: `401909926`.
- Chicago has dropped five straight at 1-6 entering its matchup with New York, which is 3-4. Jalen Brunson is averaging 26.4 points and 6 assists over his last five for New York.

### NBA Indiana Pacers at Memphis Grizzlies

- Tipoff/kickoff: `2026-11-05T01:00:00Z`; angle: `losing_streak`; rubric target ID: `401909927`.
- Indianapolis has dropped five straight at 2-6 entering its matchup with Memphis, which is 6-1. Indianapolis's Tyrese Haliburton is averaging 8.8 assists over his last five, while Grizzlies star Ty Jerome is averaging 24.8 points and 5.6 assists over his last five games, including a 40-point outing.

### NBA Utah Jazz at New Orleans Pelicans

- Tipoff/kickoff: `2026-11-05T01:00:00Z`; angle: `streak_clash`; rubric target ID: `401909928`.
- New Orleans has won three straight and sits at 3-4, while Utah has dropped five in a row at 1-6.

### NBA Cleveland Cavaliers at Oklahoma City Thunder

- Tipoff/kickoff: `2026-11-05T01:00:00Z`; angle: `records`; rubric target ID: `401909929`.
- Cleveland brings a 4-3 record into Oklahoma City, where the 5-2 Thunder look to protect home court. Oklahoma City's Shai Gilgeous-Alexander has scored at least 23 in four of his last five.

### NBA Minnesota Timberwolves at Houston Rockets

- Tipoff/kickoff: `2026-11-05T01:30:00Z`; angle: `records`; rubric target ID: `401909930`.
- The 5-3 Timberwolves visit Houston, where the 7-1 Rockets are riding a two-game winning streak. Minnesota's Anthony Edwards has put up 47 and 45 in two of his last five.

### NBA Toronto Raptors at Denver Nuggets

- Tipoff/kickoff: `2026-11-05T02:00:00Z`; angle: `records`; rubric target ID: `401909931`.
- Toronto brings a 4-3 record into Denver, where the 3-3 Nuggets look to protect home court. Denver's Jamal Murray has scored 35 and 39 in his last two, while Raptors star Scottie Barnes is averaging 24 points and 5 assists over his last five games, including a 41-point outing.

### NBA Portland Trail Blazers at Phoenix Suns

- Tipoff/kickoff: `2026-11-05T02:00:00Z`; angle: `losing_streak`; rubric target ID: `401909932`.
- Phoenix has dropped three straight at 1-4 entering its matchup with Portland, which is 5-1. Phoenix's Devin Booker has scored 20 or more in three of his last four, including 26, 20, 43, while Deni Avdija is averaging 25 points and 5.8 assists over his last five for Portland.

### NBA Dallas Mavericks at San Antonio Spurs

- Tipoff/kickoff: `2026-11-05T02:30:00Z`; angle: `winning_streak`; rubric target ID: `401909933`.
- San Antonio brings a five-game winning streak into its matchup with Dallas, which is 4-3. San Antonio's Victor Wembanyama has put up 43 and 36 in two of his last five.

### NBA Los Angeles Lakers at Sacramento Kings

- Tipoff/kickoff: `2026-11-05T03:00:00Z`; angle: `records`; rubric target ID: `401909934`.
- The 6-2 Lakers bring a two-game winning streak to Sacramento, where the Kings sit at 1-6. Darius Acuff Jr. is averaging 27.6 points and 7.4 assists over his last five for Sacramento, while Los Angeles's Luka Doncic has scored 42 and 45 in his last two.

### NBA Miami Heat at LA Clippers

- Tipoff/kickoff: `2026-11-05T03:30:00Z`; angle: `losing_streak`; rubric target ID: `401909935`.
- Los Angeles has dropped six straight at 1-6 entering its matchup with Miami, which is 2-5. Miami's Giannis Antetokounmpo has scored 30 and 31 in his last two.

## Artifacts

- `full_output.json`: full schedule, facts, evidence manifests, generated stories, and grading summary.
- `engine_input.jsonl`: exact grader input records.
- `graded.jsonl`: per-story rubric grades.
- `grade_summary.json`: rubric CLI summary.
- `dashboard.html`: offline rubric dashboard.
- grade_metrics.json: mean and median scores by league and rubric dimension.
- `run_multisport.py`: reproducible local runner.
