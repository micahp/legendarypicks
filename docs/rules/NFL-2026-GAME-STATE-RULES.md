# NFL 2026 rules contract for the LP ↔ Gridiron game simulator

**Status:** normative **engineering rules reference**, 2026 NFL **regular-season regulation**, dated 2026-10-24. This is a versioned implementation checklist derived from the published NFL playing rules, **not** the official rulebook, not a complete legal implementation, and not evidence that the current generator conforms. For any dispute, the [official 2026 NFL rulebook](https://operations.nfl.com/rules-officiating/2026-nfl-rulebook) controls. Don't substitute flag-football or college rules.

**Ownership:** Legendary Picks owns legal game/drive state and authoritative play outcomes. Gridiron Physics consumes versioned outcomes and makes the sequence inspectable; no independently guessed scores, directions, post-play ball spots or kickoff recipients. Physics-determined outcomes, if added later, require their own tested research interface. Both agents should read this reference and document which rules are implemented/tested versus missing.

**Why this exists:** The prior E0 demo assigned `dir=+1` to **every offense** in Q1–Q2 and `dir=-1` in Q3–Q4. That is **not** an NFL rule. The actual half starts with a **kickoff** determined by choices made around the opening coin toss and before the second half. Teams also change goals after Q1 and Q3 without changing possession or ending the drive. E1 must not infer a kickoff from "opposite of opening receiver," derive direction from home/away, or mark all quarter boundaries as drive terminals.

## Authoritative references (versioned)

- [2026 NFL Rulebook](https://operations.nfl.com/rules-officiating/2026-nfl-rulebook): Rule **4-1** periods/halftime; **4-2-1, 4-2-2, 4-2-3** kickoff of halves, coin-toss privileges, change of goals; **4-3/4-4/4-5/4-7/4-8** clock/timeouts/timing. Rule **6** kickoff/free kicks; **7** downs, spot, snap; **8** forward passes/fumbles; **9** punts/FG mechanics; **11** scoring, try and safety; **14** penalty enforcement; **16** overtime.
- [2026 rule changes listed by NFL Football Operations](https://operations.nfl.com/rules-officiating/2026-nfl-rulebook): kickoff receiving-team setup-zone changes (**6-1-3**), special 50-yard kick touchback spot (**6-1-5**), onside declaration now allowed **any time** (**6-1-6**). Never hardcode the 2025 kickoff/onside restrictions in a `rules_version=2026` simulator.
- [NFL announcement of 2026 adopted changes](https://www.nfl.com/news/nfl-announces-new-playing-rules-bylaws-resolutions-for-2026). Use for change provenance, not a substitute for the full rule.
- **Historical data:** Published `nfl_pbp` inputs and observed coin-toss/field-end facts must be source-verified separately. An authored default is allowed for a clearly labeled *hypothetical* game, but it is **not** a sourced fact about a real historical game.

## 1. Coin toss and first-half opening kickoff (Rule 4-2-2)

1. Before the first half, identify home/away, visiting toss call, winner, loser, and the winner's actual **first choice**. Winner may **defer** the first-choice privilege to the second half. Otherwise winner chooses a privilege for the first half: **receive/kick** *or* **goal to defend**. Other team receives the remaining type of privilege. These are different rights; "defer" is not the same as "kick."
2. Record both first-half declarations and resolve the **opening kicking and receiving teams** and the **defended goals**. The opening kickoff is its **own free-kick event**; the receiving team does not start at an invented fixed field position. Only the kick outcome (return, touchback, out-of-bounds, valid recovery, etc.) determines the next scrimmage state.
3. The winner of the toss does **not** necessarily receive the opening kick and does **not** necessarily receive the second-half kick. The deferred choice gives **first selection rights in the second half**, not automatic receipt of the ball.

**Required game state:** `coin_toss.winner`, `loser`, `winner_deferred`, `first_half.first_choice_team`, `first_half.choice_type`, `first_half.choice_value`, `first_half.other_team_choice`, `first_half.kicking_team`, `receiving_team`, `first_half.defended_goal_by_team`, `rules_version`, `source` (`observed_and_verified` or `authored_simulation_choice`). Model loss of coin-toss privilege as an explicit exception; do not silently invent it.

## 2. End of Q1 and Q3: *change ends, continue the series* (Rule 4-2-3)

- At the Q1→Q2 and Q3→Q4 boundaries, **both teams change goals**. Continue the existing possession and series: offense/defense, next down, yards to go, relative ball position and line to gain persist. Reset the period clock to 15:00, subject to NFL untimed-down/period extension rules. **No kickoff. No automatic end of drive.**
- Because field x is a fixed stadium/renderer axis, the same offense now attacks the **opposite direction**; the renderer's absolute `los` will generally mirror (`los_after=100-los_before`) when preserving the offense-relative `yardline_100`, down and distance. This is a *change-of-ends transition*, not a turnover.
- For period orientation, `dir_by_team[q+1][team] = -dir_by_team[q][team]` only for `q = 1` or `3`, and the opponent remains opposite. Do **not** apply this across halftime automatically.

## 3. End of Q2: *finish half, choose, kickoff* (Rule 4-2-1/2)

- At halftime, the **first-half scrimmage possession ends** when all legally required plays/untimed extensions are complete. A first-half drive does **not** cross halftime. Record a `halftime`/end-of-half event, not a turnover on downs.
- The team that **lost the opening coin toss** normally has **first choice for the second half**, **unless** the opening winner deferred, in which case the opening winner has that choice. The first-choice captain chooses **receive**, **kick** or **goal to defend**, with the other privilege allocated to the other team; both choices are confirmed immediately before the half. Exceptions for forfeited options require explicit flags.
- Resolve the second-half **kicking team, receiving team and defended goals** separately from first-half choices. Assign Q3 team directions from those second-half defending-goal choices, not from a universal Q3 sign and not from the first-half receiving team. Generate a **second-half kickoff event** and derive the ensuing scrimmage possession/spot from the actual sampled kickoff outcome.
- Kickoff to begin Q3 occurs **even if a team possessed the ball as Q2 ended**, barring an explicitly modeled applicable exception. Preserve the two halves' kickoff rights in a persisted coin-toss choice ledger.

**Counterexample that must pass:** A wins the toss and explicitly chooses **kick** (does **not** defer); B receives to open. Because A did not defer, B gets first second-half choice and **can choose receive again**. Hence A can kick to start **both** halves. Any code that always reverses opening possession at halftime is wrong.

**Typical defer example:** A wins and defers. B chooses to receive in the first half; A kicks. A has first second-half choice and selects receive; B kicks to begin Q3. But this common scenario is **not** the only legal scenario.

## 4. Direction, possession and coordinate invariants

For an offense-relative `yardline_100` on the 100-yard **field of play** (0 at opponent goal, 100 at own goal) and an authoritative **team + quarter** attacking-end assignment:

```text
offense dir=+1, attacking toward stadium x=100:   los = 100 - yardline_100
offense dir=-1, attacking toward stadium x=0:     los = yardline_100
```

- For each quarter `q`, store `dir_by_team[q]`, home/away defended goals, origin/source, assignment version, and the half-choice record generating it. Both teams' directions must be **opposites**.
- At an ordinary change of possession *without quarter transition*, the ball's absolute physical spot remains as provided by the outcome, the new offense is the opponent, its direction is the opposite, and `new_yardline_100 = 100 - old_yardline_100` when both measurements refer to **the same dead-ball spot**, before penalties/returns/touchbacks. A turnover return changes the spot first and must not simply reuse the pre-play LOS.
- At an ordinary touchdown/try/score/half terminal, **do not** leave a fictional normal scrimmage spot. Represent required following kickoff/try as an explicit pending/restart event.
- If team/quarter assignment, kickoff outcome, return spot, or possession is unknown, **fail or mark unavailable**. Do not infer `dir` from `quarter<=2`, home/away, or the former offense alone.
- The E0 seed-1042 `e0-field-end-v1` block (`authored_demo_convention`, Q2 IND `dir=+1`, `los=12`) is acceptable *only as labeled display metadata*. It is not an NFL-accurate rule for team orientation across the complete game and must not be reused as the E1/E2 orientation authority.

## 5. Required state machine (LP authoritative reducer)

An NFL **game** has kickoff/half/quarter state distinct from a scrimmage **drive**. Recommended research types (implementation may evolve with a version bump):

```text
game: year/rules_version, teams, seed, source/as_of
coin_toss: winner, defer, 1H/2H choice ledger, forfeiture flags
period: quarter, game_clock_seconds, running/stopped, extension_state
orientation: defended_goal_by_team, dir_by_team[quarter], assignment_version
play_state: possession, down, distance, yardline_100, ball_spot, drive_id
score: home, away, pending_try, pending_kickoff, scoring_team
timeouts: remaining_per_team_per_half
play: type, before, outcome, after, provenance, eligibility
terminal: drive_ending | change_ends | halftime | kickoff | period_end | game_end
```

Every reducer action must have **exactly one rule version, input pre-state, output post-state and reason**. Legal transitions in scope:

- `scrimmage_play` (run, pass completion/incompletion, sack, scramble, kneel, spike), first down/goal-to-go, turnover on downs, interception, fumble, safety, touchdown.
- `punt`, `field_goal_attempt`, `try`, `kickoff`, `safety_free_kick`, blocked/returned variants, with distinct participants/clock/possession/spot rules or **explicit not-yet-supported refusal**.
- `quarter_end_change_goals` Q1/Q3 (drive continues); `halftime` (half ends; resolve second-half choices and kickoff); `game_end`; `overtime` separately versioned/unsupported until tested.
- `timeout`, `two_minute_warning`, `clock_runoff`, clock-start/stop, penalty enforcement and untimed-down extension as separate substates; do not infer these from a single sampled yards value.

E1 may ship a **scoped research drive** with unsupported transitions clearly labeled as such; E2 cannot claim a **complete legal NFL game** until required restarts/score/clock/possession paths either work or the output is explicitly marked **partial/unverified**, not `valid_full_game=true`.

## 6. Rules for sample selection are not rules of football

The LP E1 branch [`b58a19f1`](https://github.com/micahp/legendarypicks/blob/b58a19f1350897b0ded2841bcf441e70a36449af/docs/SEQUENCE-E1-LP-DRIVE-2026-10-24.md) generated a **retrospective** statistical research sample. Its four-start, 4,800-seed survey produced **4,396 completed by its current limited checker** and **404 incomplete thin-cell runs**. Terminals: 1,088 touchdowns; 509 turnovers; 2,075 turnovers on downs; 724 end-of-period. No safety fixture. It currently **does not choose punts or field goals**, and uses go-for-it-only plays on fourth down: those distributions are **not realistic football frequencies**. It also excludes important event types, timeouts, quarters, score and player identities; current `end_of_period` is not a valid **drive end at Q1/Q3**, only a period transition (or Q2 halftime / Q4 game terminal as appropriate). Do not use 4,396/4,396 checker passes as a blanket NFL rule validation.

The E0 branch [`166bb84f`](https://github.com/micahp/legendarypicks/commit/166bb84fc20412c2122a2e12835dae16e2d19e73) records an **open touchdown flag bug**: the sampled row's touchdown flag describes its own starting yardline, not necessarily the synthetic state. E1's reducer uses the actual simulated goal distance, but E0 remains unfixed. Preserve E0 seed-1042 fixture and document that defect until independently fixed and tested.

For future **as-of** predictive claims, LP must exclude all events/results unavailable before a declared kickoff/time cutoff (E0's 5,572 cell contained 1,016 future-dated results); retain a separate properly grouped holdout. An outcome from 2022 being sampled into a 2025 game does not by itself validate a pool that includes future 2025 games.

## 7. Mandatory test matrix (no extrapolation from E0 seed 1042)

| Case | Required check |
| --- | --- |
| Opening toss winner **defers**, opponent receives | Persist first-choice rights; kickoff to opponent; deferred team first choice for Q3 |
| Opening winner explicitly chooses **kick** | Opponent may choose to receive **both** halves if entitled to second-half first choice |
| Toss winner chooses **defended goal** | Other team has kickoff/receive privilege; resolve actual receiving/kicking teams rather than inventing them |
| Q1→Q2 | No kickoff or new drive; preserve possession, down/distance and offense-relative spot; flip defended goals |
| Q3→Q4 | Same change-of-ends continuation, not period-as-drive-ending |
| Q2→Q3 | End existing half-drive; reset half timeouts/clock; apply second-half choice; **kickoff event**; first Q3 scrimmage spot comes from kick outcome |
| Opening kickoff | Kicking/receiving teams correct; outcome spot from the free kick; no hardcoded immediate possession without a kick |
| Turnover on downs in Q2 | New offense is other team at same dead-ball spot; `dir` flips, `yardline_100` complements, `los` remains consistent |
| Touchdown | Apply **six-point** score plus distinct try; after try proceed to kickoff as rules require; no fictional auto-PAT |
| Made FG / safety | Score per Rule 11 (FG **3**, safety **2**); schedule correct post-score kick/restart |
| Fourth down | Choose between punt, FG, and go-for-it conditional on field/time/score; do not use go-for-it data as all NFL fourth downs |
| Clock/timeouts | 15-minute regulation quarters, **three timeouts per team per half**; no clock increase; end of Q1/Q3 is not drive terminal |
| Unsupported rules | Reject with an explicit unsupported code or mark incomplete; never silently force a turnover on downs, normal run, or finished game |
| Overtime/untimed down/penalties | Explicit rule-version-sensitive guards and test cases before claiming full-game completeness |

## 8. Near-term work order, based on real current branches

**LP sequence agent (critical path):** Keep [E1 `b58a19f1`](https://github.com/micahp/legendarypicks/commit/b58a19f1350897b0ded2841bcf441e70a36449af) and [E0 defect note `166bb84f`](https://github.com/micahp/legendarypicks/commit/166bb84fc20412c2122a2e12835dae16e2d19e73) as unchanged research evidence. First introduce a **unit-tested coin-toss/half kickoff + change-ends state machine** around (not a rewrite of) the existing reducer. Then fourth-down decision families and scoring/clock ledger. Do not equate the current 4,396 checker passes with official-rule conformance. Reconcile which E1 drive outcomes continue across Q1/Q3 and which actually terminate. Pin one **authored** two-half example to show kickoff rights and correct Q3 opening.

**Gridiron viewer agent:** Build a read-only kickoff/half/quarter timeline and rule-state display without inventing 22-player physical kickoff choreography. Use LP `dir_by_team[quarter]` and verified `los` for 3D coordinates; do not validate a universal Q1–Q2 or Q3–Q4 direction for **every offense**. Preserve E0 retrospective, immutable, missing-value policies and versioned distinction between E0a record display and E0b player-specific 3D replay.

**Coordinator:** Gate E1 acceptance on a correct, documented sequence of actual legal **drive** terminal versus **quarter** transitions, including punts/FG choices or explicit limitations. Gate E2 full-game claim on both-half kickoffs, possession/scoring/restarts and reconciliation. Never imply full 2026 NFL rule coverage where only a narrow test passes. Move toward a complete game instead of isolated motion experiments.

## Tracking of rule implementation

| Rule family | E0 demo | E1 `b58a19f1` | Required E2 |
| --- | --- | --- | --- |
| Snap/line to gain/downs | Minimal legality | Limited reducer checked | Cross-quarter/full-game invariants |
| Coin toss/deferral | Not modeled | Not modeled | Complete choice ledger |
| First- and second-half kickoff | Not modeled | Not modeled | Distinct free-kick events |
| Change goals Q1/Q3 | Demo shortcut, **not valid general rule** | Quarter transitions not implemented | Correct field-end mapping, preserve series |
| Fourth-down choices | Scrimmage only | Go-for-it only | Punt/FG/go-for-it decisions |
| Passing/rushing/turnovers | Four events | Six sampled families | Full legal variants and provenance |
| Scoring/tries | No score | TD/safety terminals, no points | Score/tries/restarts |
| Clock/timeout/quarter/halftime | Q2 static fixture | Within-quarter sampled runoff only | Legal transitions and start-stop |
| Player lineup/3D physical motion | Not modeled | Not modeled | Separate honest replay status |
| Overtime/penalty exception handling | None | None | Explicit tested coverage or blocked full-game claim |

**Change-control:** Amend this file in a dated section with updated official rule section/edition, exact LP/GP code commit, tests and status. If rules change in 2027, create a versioned successor rather than silently altering what `rules_version=2026` means.
