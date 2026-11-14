# NBA historical relationships: the work and its caveats

Branch `feat/historical-relationships-nba`, draft PR #46. Written 2026-11-14.
Nothing here is merged, deployed or scheduled. Production is untouched.

## 1. Why this exists

The spec (`docs/HISTORICAL-RELATIONSHIPS-RIVALRIES-2026-11-11.md`) asks for pregame story
angles for every game, such as "this player faces his old team" or "these two teams are linked
by a trade". The angles must come from verified data, with no per-story model call and no
hand-pinned fixtures.

Our database had no way to know who was traded or when. The game logs start in October 2025,
so the July 2025 Durant trade is not in them. There is no NBA transactions table. So the first
job was a source, then a graph, then the angles.

## 2. What was built

Data flows left to right. Each step is a pure function except the two noted.

| Step | File | What it does |
|---|---|---|
| Ingest (network, writes) | `backend/ingest_nba_player_movement.py` | Fetches NBA.com's official player movement file (one request). Stores every row. Reads trade direction from the description text and cross-checks the team slug. |
| Collector (read only) | `backend/story_engine_relationships.py` `collect_relationship_inputs` | Reads movement rows, a roster snapshot captured at or before the cutoff, and earlier meetings between the two teams. |
| Graph | `backend/sports_relationships.py` | One node per trade (a multi-team deal is one node), team stints, shared tenure, as-of filter. |
| Detector | `backend/storyline_candidates.py` | Finds angles for one game. Rejected angles are kept with a reason. |
| Ranking | `backend/storyline_ranking.py` | Scores angles, picks one lead, turns the rest into context cards, compares with the existing angle. |
| Templates | `backend/storyline_templates.py` | Plain wording built from structured claims. |
| Audit | `backend/storyline_audit.py` | Re-reads the finished text and checks it against the graph. |
| Adapter | `backend/story_engine_relationships.py` `generate_story_with_relationships` | Joins it all to `story_engine.generate_story`. |

Angles detected: former team, reciprocal trade, first team meeting after a trade, return to a
former arena (and a proven "first" version), former teammates now opponents.

`story_engine.py` was not changed. With no relationship input the adapter returns exactly what
`generate_story` returns (a test compares the two).

### How the adapter decides

1. It runs the existing engine first.
2. It detects and ranks relationship angles against the existing angle.
3. A relationship angle replaces the lead only if all three hold: the existing angle has an
   editorial score in the rubric, the relationship angle outranks it and may be a headline, and
   the finished text passes the audit.
4. Otherwise the existing story stays. An audit failure is written to the manifest.
   `strict=True` raises instead.
5. The manifest records the base angle, the full score log, detector rejections, the facts that
   were displaced, and the evidence ids.

The story keeps the one to three sentence rule. A four sentence trade summary is cut to three.

## 3. What was verified

- 194 tests pass. That includes the 57 existing story engine tests, run unchanged.
- The real movement file was ingested on a throwaway database and on the dev database:
  10,142 rows, 1,813 trades, 0 direction conflicts, 0 unparsed.
- Durant moves PHX to HOU. Green and Brooks move HOU to PHX. The seven team deal is one node
  with four draft consideration rows kept.
- Mutation checks: for every gate (direction, as-of, scratch, coverage, ranking, audit, adapter)
  a test fails when the gate is removed. Details in section 6.
- One end to end run on a test database produced: "Houston and Phoenix meet for the first time
  since the July 6, 2025 trade. Kevin Durant went from the Phoenix Suns to the Houston Rockets.
  Dillon Brooks and Jalen Green went from the Houston Rockets to the Phoenix Suns." The existing
  engine's line for the same input was "Houston brings a three-game winning streak into its
  matchup with Phoenix, which is 1-1."

## 4. Caveats (read these before trusting any output)

Each item says how I know it.

**A. The ranking numbers are not calibrated.**
The weights, the 120 day half life and the fixed scores for existing angles (for example
winning streak 0.40, undefeated 0.85) are my starting values. Nothing was tuned against blinded
human review. The rubric says `v0-unvalidated`. A different set of numbers could change which
angle leads. The spec asks for a 12 game editorial review. It has not been done.

**B. Dates are effective dates, and the cutoff is conservative.**
The file carries the effective date only, not the agreement date (for Durant the file says
2025-07-06). It has no publication time. The adapter uses the day before the cutoff day, so a
trade dated on game day is never used. For old trades our capture time is later than the game,
so "known before the game" rests on the effective date, not on a publication record. Spec test 7
(prove original publication before the cutoff) is only partly met.

**C. Only 746 of 2,357 player ids in the file match our players.**
Measured 2026-11-12. Every id we hold appears in the file, but about 69 percent of ids in the
file are players we do not carry. Retired players and players who left the league have no
record on our side, so their trades do not join. Angles only work for players who are on a
current roster and in our table.

**D. The file starts 2015-07-01.**
Before that, tenure is unknown. A stint with no start in the file is marked `start_covered=False`.
A "re-signed" row proves the player was already on the team, so it never counts as a documented
start. Result: Tatum and Brown at Boston come out as shared tenure with `complete=False`,
because the file shows only re-signing rows for them. The file has no draft rows (checked for
those two players). Such pairs are never headline eligible.

**E. Availability has no source.**
There is no inactive list in the database. The collector sets every player to `unknown`.
So every player level angle is not headline eligible, and only team level angles can lead.
Whether Durant played on 2025-11-24 cannot be answered from our data. The detector and
templates handle `expected_to_play`, `active_confirmed` and `inactive` correctly in tests, but
nothing feeds those states yet.

**F. "First meeting since the trade" is blocked by our meeting history.**
`team_game_results` for the NBA starts 2025-10-21 and holds regular season games only
(measured 2026-11-12). The Durant trade is dated 2025-07-06. The detector requires meeting
history to start on or before the trade, so on real data it rejects the claim with
`meeting_history_incomplete`. That is the correct fail loud result. A rule such as "no games
exist between the offseason trade and opening night" would allow it, but that rule is an
assumption I have not verified, so it is not in the code. It needs your decision.

**G. The Nov 24, 2025 and Apr 7, 2026 games cannot be replayed from our data.**
Roster snapshots start 2026-08-04 (ESPN) and 2026-10-03 (NBA.com). The collector refuses a
roster captured after the cutoff, so a 2025 replay stops with `RelationshipDataMissing`. Those
two games are covered only by synthetic tests, not by a real replay. A real replay needs a
roster source for 2025-26 and an inactive list.

**H. No appearance history is loaded.**
So no "first return to the former arena" claim can be proven in production use. The code path
exists and is tested with supplied history. The collector does not supply it.

**I. Angles that are not built.**
Playoff series rematch, championship connection, historical rivalry, and first actual
opponents after a trade. No series, championship or on court appearance source is loaded.
The detector lists them as `not_supported` in every result.

**J. Only angles with a fixed score can be replaced.**
When the existing engine takes its fallback paths (`star_performance`,
`available_player_facts`), the adapter leaves the story alone and says
`base_angle_not_ranked`. I did not invent scores for those.

**K. Not wired to anything.**
No endpoint, timer or runtime code calls the adapter. The ingest is not in
`ingest_registry.py` and has no timer. The collector needs the two new tables, which exist on
the dev database only. Prod has neither.

**L. The source may block us.**
`AGENTS.md` says stats.nba.com blocks datacenter hosts. A plain client worked on 2026-11-12,
once. That is one observation, not a guarantee. The ingest fails loud on a failed or shrunken
feed and writes nothing in that case.

**M. Evaluation is not done.**
Not done: 12 real test games, the 50 game held out set, claim precision and recall, blinded
lead agreement, before and after stories for 12 games, and latency (median and p95). The
one end to end run above is a demonstration, not an evaluation.

## 5. Decisions that need you

1. Allow the offseason rule in F, yes or no.
2. Where an inactive list and a 2025-26 roster history should come from (E, G).
3. Whether to add the ingest to `ingest_registry.py` with a timer. This changes systemd timers.
4. Whether to run the 12 game editorial review and tune the rubric (A, M).
5. Whether to wire the adapter into the preview runtime behind a flag.

## 6. How the tests were checked

A green suite can miss its own defects. For each gate I removed it or reversed it and ran the
tests again. Every one of these made a test fail:

- Trade direction reversed. As-of filter removed. Conflict rows admitted. A "re-signed" row
  counted as a start.
- Scratched player gate removed. Meeting and appearance coverage gates removed. As-of limits on
  trades and stints removed. Teammate availability check removed.
- Ranking: no decay, ineligible angle allowed to lead, no dedupe, no same event context, no
  prior use penalty, no evidence penalty, reversed tie break.
- Audit: each check removed in turn (direction, claims, first, availability, team scope,
  cutoff, banned words, postgame words, missing name, em dash). Template direction reversed.
- Adapter: cutoff day leak, audit ignored, unranked base replaced, roster after cutoff allowed,
  inactive players kept, own game counted as a meeting, no sentence cap, changed output with no
  input, displaced facts dropped.

Two weak tests were found this way and fixed (evidence penalty, claim checks in the audit).
One method error was found and fixed: a line swap that keeps the file size can reuse stale
compiled Python, so a mutation run looked like a pass or a fail it was not. The runs were
repeated with bytecode caching off. One test fixture also mapped Jalen Green to the wrong NBA
id (1631105 instead of 1630224). It is corrected.

## 7. Run it

```
cd backend
python3 -m unittest test_ingest_nba_player_movement test_sports_relationships \
  test_storyline_candidates test_storyline_ranking test_storyline_audit \
  test_story_engine_relationships test_story_engine test_story_rubric test_story_engine_runtime
python3 ingest_nba_player_movement.py --db <db>      # one request, writes two tables
```

```python
inputs = collect_relationship_inputs(db_path, game, as_of=as_of)   # read only, may raise
result = generate_story_with_relationships(bundle, inputs)         # inputs=None gives the old output
```
