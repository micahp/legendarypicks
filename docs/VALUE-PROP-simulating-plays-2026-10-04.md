# Legendary Picks: simulating plays from player movement

2026-10-04, Micah. Also kept as a Claude Doc:
https://claude.ai/code/artifact/fdfa1c33-2f8a-4baa-b37c-02e257f4aaac (this file is the copy of record).

## Thesis

Legendary Picks has two value propositions, in this order.

1. **Prop data and prop history.** Every line the books and Kalshi post, from many sources, settled against what actually happened. That is the product today.
2. **How the players actually move.** Enough about each player's real body mechanics to simulate what happens on each down in football, each point in tennis, each play in basketball and each possession in soccer. A model that knows how a quarterback throws and how a receiver and cornerback move against each other can estimate a play before it happens, which no box score, play-by-play feed or commentary can.

The first is a record of outcomes. The second is a model of the process that produces them, and it is the harder and more defensible asset.

## The main path: no video

We do not need video or a trained movement model to make money. The first thing to build is the non-video stack, and most of it already exists. Video stays a later edge on top (sections below).

**Pregame, the class of data that matters:**

- Prop history and line movement: every book's line over time, settled against results. LP's core asset.
- Player stats and team stats.
- Injury reports.
- Head-to-head history, team and player.
- Situational splits: Thursday night, road, primetime, rest, travel, coach against coach. Micah's examples from 2026: the Bears' Thursday-night record and the Steelers on the road on a Thursday (that read held); Nick Sirianni 4-0 against the Rams' coach going into Eagles vs Rams (that one did not).

**In the game:** play-by-play (point-by-point in tennis) and live prices, from Kalshi's own feed for every sport.

**The caution, and how we handle it:** a split like 8-0 on Thursday nights is a true number on a sample of 4 to 8 games, and the market sees it too. The edge is knowing which kinds of factor actually beat the price, measured over every game they apply to, not picked one at a time. So each factor gets tested before agents lean on it:

1. For each factor (situational record, coach head-to-head, rest, travel, injury counts), find every past game where it applied.
2. Check whether the side it favored beat the pregame price, using LP's game results and prop history and the competition's recorded Kalshi pregame prices.
3. Keep the factors that survive, with their sample size shown; drop the rest.

**Gaps for football:** LP has no 2026 NFL player game logs yet, and coach records are not stored anywhere. Both are cheap compared with video.

## Full circle: why the agents need all of this

The trading agents keep passing because "the book moves before the feed". That is true and beside the point: the feed was never the edge. The play-by-play tells an agent **what** happened; everything else tells it **what that should mean**.

- After a touchdown, a break of serve or a knockdown, the price moves within seconds, before any feed or commentary arrives. Nobody beats the market to the play.
- Whether that move was too big or too small depends on context the market may weigh wrongly: the two sides' strength, the injury report, head-to-head history, the situation (rest, road, primetime), what the props market says about the players involved, and the pregame line.
- So the live question is never "did I see it first?" It is "given everything I know about these two sides, is the new price right?" That is judgment, and judgment is what the pregame data stack and prop history feed.
- The movement layer, later, sharpens the same judgment: a model of how these specific players move says what the next snap or serve is likely to bring, which no box score can.

**Done on 10-04:** the agents' briefing (`/root/prediction-market-trading/docs/AGENT-BRIEFING.md`, commit `2ed32d7`) now says this directly. It replaced "the feed explains a move; it rarely predicts one" with: you will not beat the market to a play; trade on whether the new price is right given all the context, and name the factors you used. It also tells them a 4-to-8-game split is a stated sample, never the whole reason.

## What the agents see today

Only tennis gets Kalshi's own live feed. Kalshi publishes the same kind of feed for football, baseball and hockey, and we have not plugged those in (Codex task: `/root/prediction-market-trading/docs/TASK-kalshi-live-data-all-sports.md`). Counts are feed events from 10-02 to 10-04.

| Sport | What the agents get | Source | Kalshi live data available, not wired |
| --- | --- | --- | --- |
| Tennis | Every point: server, score, break points (5,433) | Kalshi live data | wired |
| UFC | Takedowns, knockdowns, submission attempts, rounds (193) | UFC live stats | not checked |
| NFL | Play-by-play (1,314 plays) | ESPN, via LP's scoreboard | `football_game`: last play, down and distance, clock, timeouts, review status (Stats Perform) |
| NCAAF | Play-by-play (2,248 plays) | ESPN, via LP's scoreboard | `football_game`, same as NFL |
| MLB | Score and inning changes only | LP's scoreboard | `baseball_game`: balls, strikes, outs, runners, pitchers, last play |
| NHL | Score and period changes only | LP's scoreboard | `hockey_match`: last play, power-play strength, clock |
| NBA | Score changes only | LP's scoreboard | not checked |

Broadcast commentary is on top of these for any game on a captured channel (Tennis Channel 2, FS1, ESPNU, NBC, RedZone piped from home).

Kalshi's traders see Kalshi's feed. Wiring `baseball_game`, `hockey_match` and `football_game` into the live feed would give the agents pitch-by-pitch, shift-level and down-by-down state from the same source the market itself prices off, the way tennis already works.

## Why feeds lag, and what they cannot say

Every feed we have reports a play after it happened, and the market has usually moved first. Measured on this box:

| Measure | Result |
| --- | --- |
| Order book vs point and play feeds, tennis and UFC | the book leads by 2 to 13 seconds |
| RedZone commentary vs the game-winner price, 12 NFL scoring plays on 10-04 | commentary a median 150 s after the price moved; first in 1 of 12 |
| RedZone commentary vs the play-by-play feed, 17 scoring plays | commentary a median 23 s later; first in 8 of 17 |
| Price move after injury mentions vs other RedZone lines, 15 minutes | 2.0c vs 2.0c median: no difference |

That is expected: a feed describes the result. What none of them carries is the process that produced it.

- A play-by-play line says "Prescott pass to Lamb for 34 yards". It does not say the receiver beat press coverage with a release the cornerback could not match, or that the throw was late and only worked because of his catch radius.
- A tennis point says who won it. It does not say the server's toss drifted, or that the returner was a step late on every wide serve.
- So an agent can only react to outcomes the market has already priced. To get ahead of the market it would need a model of how these specific players move, and what that makes likely on the next snap or serve.

## What the three reference projects show

All three are by Peter Wang and Nico Christie, published 2 to 3 October 2026. Together they show that ordinary broadcast video, run through an off-the-shelf pose model, yields body measurements precise enough to tell players apart and track how their mechanics change.

| Project | Video in | How | What it measured |
| --- | --- | --- | --- |
| [Federer, Syllable by Syllable](https://pwang724.github.io/federer/) | TV recordings of 45 US Open matches, 2003 to 2019, some only highlights | joints per frame, then [keypoint-MoSeq](https://doi.org/10.1038/s41592-024-02318-2) splits movement into repeated "syllables" with no tennis knowledge | 274 forehands and 375 serves compared by era: forehand stance closed from 49° to 65°, contact point moved from 54 cm to 62 cm from the hip, finish rose from 18 cm below to 4 cm above the shoulders |
| [NotoriousData](https://nicodunks.github.io/NotoriousData/) | 15 Conor McGregor fights, 2012 to 2021, from official UFC, Fight Pass and broadcaster uploads | RTMW-x whole-body pose (via rtmlib), 133 points per fighter; only live action, found by detecting the fight clock on screen | his head sat 17 cm above the shoulders vs 12 for opponents in all 14 fights; hands 23 cm below the shoulders vs 18; shoulders turned from 38° side-on to 26° by 2018 to 2021 |
| [Skeleton Tennis](https://pwang724.github.io/tennis-skeleton-quiz/) | serve clips | skeletons only | a quiz: identify the player from one serve's skeleton; 20 questions over 10 levels |

What this means for us:

- **The pipeline is proven and small.** Public video, a pose model, then measurements. Their code is public: [deep-sports-analysis](https://github.com/pwang724/deep-sports-analysis) and [NotoriousData](https://github.com/nicodunks/NotoriousData).
- **Its stated limits are the right ones to plan around.** NotoriousData: "Fifteen fights is not many, and a broadcast is a flat picture: movement toward the camera is invisible and whether a punch landed can't be measured."
- **It measures a player's style across many clips, not one play live.** That is exactly the prior a simulation needs: who this player is, mechanically, before the snap or serve.

## Where the video comes from

We already pull live broadcast video onto this box, and today we throw the picture away and keep only the audio. That is the cheapest source of all.

**What Micah shared** (Hermes' Discord image cache, 10-04 22:43):

- Nico Christie (@nicochristie), 4 Oct, 14.3K views: "motion sequenced every Conor McGregor fight": the karate stance disappeared over the years, he fired pull/slip rear lefts 3 to 4 times more, his left was only average speed, his cardio was better than he gets credit for.
- Peter Wang (@BrainsAndTennis), 3 Oct, 22.8K views: the Federer syllables; "Didn't know his fh was more closed-stanced as he got older."
- Peter Wang: "labelled a shitton of tennis data" for the skeleton quiz, "a fun little pit stop for much deeper tennis analysis that ill share later". The quiz places skeletons on a court diagram and labels shots ("Forehand, topspin, inside-in"), so their tennis data is already court-registered, not just joints.

**Sources, and what this box can reach:**

| Source | What it is | Reachable from this box |
| --- | --- | --- |
| Live TV we already capture | FS1, ESPNU, NBC (WTLV), Tennis Channel 2; full broadcast video, every play | yes: ffmpeg already reads these streams; we keep only audio today |
| Home box (Kallen) | anything Micah's logged-in browser plays: RedZone, NBC WTVJ, NFL+ | yes, piped over SSH, as RedZone was on 10-04 |
| Official highlight uploads | NFL, NBA, UFC, ATP/WTA YouTube channels; what NotoriousData used | YouTube is unreliable from a datacenter IP; likely needs the home box |
| In-game clips on X and Instagram | teams and leagues post plays within minutes | hard from a datacenter IP; home box or an API |
| Archived broadcasts | full games, as the Federer project used (45 matches) | depends on Micah's subscriptions |

Broadcast video has one problem for football that tennis and UFC do not: the camera follows the ball and cuts between angles, so most of the 22 players are off screen on most snaps. The all-22 coaches' film shows everyone; it comes with NFL+ Premium, so it is reachable only through the home box.

## Short of a video pipeline

Much of the movement signal is already published as numbers, and it costs nothing to ingest. It gets us part of the way: who is fast, tall, long-armed or strong-armed, and how a player's tracked movement trends. It does not tell us how a specific throw or swing was made. Availability below is from general knowledge, not checked on 10-04; each needs a look before we build on it.

| Source | What it gives | What it cannot tell |
| --- | --- | --- |
| Player measurables (NFL and NBA combines, tour bios) | height, weight, arm length, hand size, 40-yard, vertical; tennis height and handedness | anything about technique |
| MLB Statcast (Baseball Savant; LP already ingests some) | every pitch's velocity, spin and movement; bat speed and swing path; sprint speed; arm strength | body mechanics behind them |
| NFL Next Gen Stats | separation, time to throw, air yards, completion over expected, speed | per-snap positions for all 22 players |
| NFL Big Data Bowl tracking | x and y for all 22 players, several frames a second, for past seasons' sampled weeks | live, current-season data |
| NBA tracking (nba.com) | speed, distance, touches, drives, defended shots | joint-level movement |
| Soccer open event data (StatsBomb open sets) | every event; positions of visible players at each event for some competitions | most leagues we trade |
| Tennis ball tracking (Hawk-Eye) | serve speed, placement, rally length | not public at this depth |

The height example fits here: a receiver's height, arm length and speed against a cornerback's is a measurable mismatch, and a model can use it today. What it cannot see is whether the quarterback threw it on time, which is the part that needs video.

## Recommendation

Build the non-video path above first. The movement layer is the later edge: it does need video, since no published feed carries joint-level mechanics, but it does not need a new video pipeline on day one, and it should start with tennis, where one camera shows both players whole and Kalshi's point feed already marks where every point starts and ends.

1. **Now, no video: match Kalshi's own feed.** Wire Kalshi's `baseball_game`, `hockey_match` and `football_game` live data into the agents' feed, so every sport gets what tennis gets. Add measurables, Statcast and Next Gen Stats numbers to each game's context. Gate: the agents use them in their stated trade reasons.
2. **Tennis skeletons from our own capture.** Keep the video from the Tennis Channel streams we already ingest, cut it at Kalshi's point boundaries, run a whole-body pose model (RTMW via rtmlib, as NotoriousData did), and store skeletons, not video. Build each player's profile: serve toss, stance, contact point, footwork speed, how they change under pressure. Gate: a profile measured on past matches predicts something in held-out matches that the price did not already have. If it does not, stop here.
3. **UFC next.** Same shape: one camera, two bodies, a fight clock to find live action. Gate: as above.
4. **Football, basketball, soccer last.** Broadcast hides most players most of the time, so these need all-22 film through the home box, or tracking data (the Big Data Bowl sets) to build priors first.

Three practical points:

- **Store skeletons, not video.** A skeleton is a few kilobytes a second; the root disk is at 93%.
- **This box has no GPU.** Pose models on CPU are slow but fine for offline batches; live per-point inference would need a GPU or the home machine.
- **Peter Wang and Nico Christie are ahead of us.** They have labeled tennis data, public code, and say deeper tennis analysis is coming. Talking to them could save phase 2 entirely.

## Open questions

- [ ] Start phase 1 (wiring Kalshi's baseball, hockey and football live data) now? (Queued for Codex 10-04.)
- [ ] Contact Peter Wang and Nico Christie about their labeled tennis data before building phase 2?
- [ ] Which subscriptions on the home box could feed video: NFL+ Premium (all-22), Tennis TV, UFC Fight Pass?
- [ ] Is the home machine the place to run pose models (it would need a GPU), or do we rent one for batches?
- [ ] What counts as success for phase 2: a measurable price edge, a product feature (player mechanics pages in LP), or both?
- [ ] Tennis or football first for the movement layer?

## Sources

- [Federer, Syllable by Syllable](https://pwang724.github.io/federer/), Peter Wang and Nico Christie, 2 Oct 2026
- [NotoriousData](https://nicodunks.github.io/NotoriousData/), Nico Christie and Peter Wang, 3 Oct 2026
- [Skeleton Tennis](https://pwang724.github.io/tennis-skeleton-quiz/), Peter Wang
- [keypoint-MoSeq](https://doi.org/10.1038/s41592-024-02318-2), Nature Methods
- Code: [deep-sports-analysis](https://github.com/pwang724/deep-sports-analysis), [NotoriousData](https://github.com/nicodunks/NotoriousData)
- Measurements in "What the agents see today" and "Why feeds lag": the trading box, 2 to 4 Oct 2026
