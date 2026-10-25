# NFL 2026 rules contract for the LP ↔ Gridiron game simulator

**Status:** normative **engineering rules reference**, 2026 NFL **regular-season regulation**, dated 2026-10-24. This is a versioned implementation checklist derived from the published NFL playing rules, **not** the official rulebook, not a complete legal implementation, and not evidence that the current generator conforms. For any dispute, the [official 2026 NFL rulebook](https://operations.nfl.com/rules-officiating/2026-nfl-rulebook) controls. Don't substitute flag-football or college rules.

**Ownership:** Legendary Picks owns legal game/drive state and authoritative play outcomes. Gridiron Physics consumes versioned outcomes and makes the sequence inspectable; no independently guessed scores, directions, post-play ball spots or kickoff recipients. Physics-determined outcomes, if added later, require their own tested research interface. Both agents should read this reference and document which rules are implemented/tested versus missing.

**Why this exists:** The prior E0 demo assigned `dir=+1` to **every offense** in Q1–Q2 and `dir=-1` in Q3–Q4. That is **not** an NFL rule. The actual half starts with a **kickoff** determined by choices made around the opening coin toss and before the second half. Teams also change goals after Q1 and Q3 without changing possession or ending the drive. E1 must never substitute an inferred possession for an actual kickoff event. In **normal** simulations, the opening receiver is explicitly required to kick off Q3, and that requirement must be confirmed against the recorded toss/choice ledger. Never derive field direction from home/away or mark all quarter boundaries as drive terminals.

## STRICT DEFAULT SIMULATION POLICY — NOT OPTIONAL

**Normal NFL simulations MUST have two different teams kicking off to start the two halves: each team kicks exactly once for `kickoff.reason=half_start`.** This is a **product/prediction policy based on ordinary NFL choices**, not a claim that the NFL prohibits rare alternate declarations. Do not interpret the full legal coin-toss option set as permission to randomly create bizarre strategies.

**Implement it as an invariant, not prose:**
1. In `normal_nfl_game` mode, the coin toss winner may **receive** or **defer**. A winner choosing **kick** without deferral, **defend_goal** as the first privilege, or any first-choice choice that results in the same team kicking to start both halves is **not eligible to be sampled**. The team with first choice in either half chooses **receive**, consistent with the standard real-game strategy. Field-end selection remains explicit and is assigned by the team granted that privilege.
2. The second-half kickoff is still a distinct, fully modeled `half_start` kickoff with a proper coin-toss/defer/choice ledger and derived receiving/kicking teams. Never infer possession from a `quarter` number or omit the kickoff. A team's half-start kicking obligation is not the same as kickoffs **after touchdowns or field goals**: the one-each invariant applies **only** to the two half-opening kickoffs.
3. **Fail closed:** Validation requires exactly two `half_start` kickoff events (Q1 and Q3), one by each team, opposing first- and second-half receivers, a valid declared choice ledger, and no missing/unknown choice or result. A double-half-kickoff by the same team in normal mode is a **hard test failure**; no warning-only status, quiet fallback, or guessed second-half receiver.
4. A `historical_reconstruction` may show a **source-verified actual exception** without calling it a sampled normal simulation. A separate `explicit_exception_scenario` test mode may reproduce a **user-requested, documented counterexample**, but it must require deliberate opt-in, preserve the explicit coin-toss/choice ledger and reason, be marked exceptional, and be excluded from normal simulations, prediction distributions, game realism benchmarks and release metrics. **Default rate of sampled exceptional choices in normal mode: exactly zero (0).** No `1%` or tiny nonzero probability is authorized.
5. If an agent cannot implement this contract yet, mark the game **incomplete** or **unsupported**. Do not produce `valid_full_game=true` for a normal game that violates the half-opening kickoff invariant.

**Engineering acceptance test:** run many normal seeded games (including both coin-toss outcomes, receive and defer cases). Assert `half_start_kickoffs.length === 2`; `Set(kicking_team).size === 2`; the Q3 kicker is the Q1 receiver and vice versa; the choice ledger explains both kickoffs. Include a negative fixture where the same team kicks twice and assert **normal mode rejects it**. A documented exceptional case must **fail in normal mode** and work only in the explicitly enabled exception/reconstruction context. This test is required **before E2 may be called a complete simulated game**.

**Decision rationale:** The user explicitly wants the simulator to model **the game as normally played**, not inject a vanishingly rare legal technicality into forecast trials. Preserve unusual options as compliance knowledge and narrowly gated test cases, **not** as stochastic football behavior. This policy takes priority over any more permissive language later in this document.

## Authoritative references (versioned)

- [2026 NFL Rulebook](https://operations.nfl.com/rules-officiating/2026-nfl-rulebook) ([official 2026 PDF](https://static.www.nfl.com/image/upload/fl_attachment/league/tqivdkzt9mu6wdgsh1ku.pdf)): Rule **4-1** periods/halftime; **4-2-1, 4-2-2, 4-2-3** kickoff of halves, coin-toss privileges, change of goals; **4-3/4-4/4-5/4-7/4-8** clock/timeouts/timing. Rule **6-1-1/6-1-2/6-1-3** free kicks and safety-kick procedure; **7-2-1/7-3** dead ball and series of downs; **8** passes/fumbles; **9-2-1 through 9-2-5** touching of a scrimmage kick; **9-3-1 and 9-3-2** kicking-team recovery; **9-4** dead-ball/touchback variants; **11-4-2** missed-FG exceptions; **11-5-2** restart after safety; **14** penalty enforcement; **16** overtime.
- [2026 rule changes listed by NFL Football Operations](https://operations.nfl.com/rules-officiating/2026-nfl-rulebook): kickoff receiving-team setup-zone changes (**6-1-3**), special 50-yard kick touchback spot (**6-1-5**), onside declaration now allowed **any time** (**6-1-6**). Never hardcode the 2025 kickoff/onside restrictions in a `rules_version=2026` simulator.
- [NFL announcement of 2026 adopted changes](https://www.nfl.com/news/nfl-announces-new-playing-rules-bylaws-resolutions-for-2026). Use for change provenance, not a substitute for the full rule.
- **Historical data:** Published `nfl_pbp` inputs and observed coin-toss/field-end facts must be source-verified separately. An authored default is allowed for a clearly labeled *hypothetical* game, but it is **not** a sourced fact about a real historical game.

## 1. Coin toss and first-half opening kickoff (Rule 4-2-2)

1. Before the first half, identify home/away, visiting toss call, winner, loser, and the winner's actual **first choice**. Winner may **defer** the first-choice privilege to the second half. Otherwise winner chooses a privilege for the first half: **receive/kick** *or* **goal to defend**. Other team receives the remaining type of privilege. These are different rights; "defer" is not the same as "kick."
2. Record both first-half declarations and resolve the **opening kicking and receiving teams** and the **defended goals**. The opening kickoff is its **own free-kick event**; the receiving team does not start at an invented fixed field position. Only the kick outcome (return, touchback, out-of-bounds, valid recovery, etc.) determines the next scrimmage state.
3. Under the **normal simulation policy above**, the first-choice team elects to **receive**, and the team kicking to start Q1 **receives** the kickoff to start Q3. The deferred choice is still recorded as first-selection rights, not the same thing as choosing to kick. **Do not randomly sample the rare legal exception.**

**Required game state:** `coin_toss.winner`, `loser`, `winner_deferred`, `first_half.first_choice_team`, `first_half.choice_type`, `first_half.choice_value`, `first_half.other_team_choice`, `first_half.kicking_team`, `receiving_team`, `first_half.defended_goal_by_team`, `rules_version`, `source` (`observed_and_verified` or `authored_simulation_choice`). Model loss of coin-toss privilege as an explicit exception; do not silently invent it.

## 2. End of Q1 and Q3: *change ends, continue the series* (Rule 4-2-3)

- At the Q1→Q2 and Q3→Q4 boundaries, **both teams change goals**. Continue the existing possession and series: offense/defense, next down, yards to go, relative ball position and line to gain persist. Reset the period clock to 15:00, subject to NFL untimed-down/period extension rules. **No kickoff. No automatic end of drive.**
- Because field x is a fixed stadium/renderer axis, the same offense now attacks the **opposite direction**; the renderer's absolute `los` will generally mirror (`los_after=100-los_before`) when preserving the offense-relative `yardline_100`, down and distance. This is a *change-of-ends transition*, not a turnover.
- For period orientation, `dir_by_team[q+1][team] = -dir_by_team[q][team]` only for `q = 1` or `3`, and the opponent remains opposite. Do **not** apply this across halftime automatically.

## 3. End of Q2: *finish half, choose, kickoff* (Rule 4-2-1/2)

- At halftime, the **first-half scrimmage possession ends** when all legally required plays/untimed extensions are complete. A first-half drive does **not** cross halftime. Record a `halftime`/end-of-half event, not a turnover on downs.
- The team that **lost the opening coin toss** normally has **first choice for the second half**, **unless** the opening winner deferred, in which case the opening winner has that choice. The **official rules** permit a choice of **receive**, **kick** or **goal to defend**, with the other privilege allocated to the other team. But in **normal simulation mode, first choice is ALWAYS receive**; other selections are reserved for source-verified historical reconstruction or explicit opt-in exception tests. Both halves' choices are recorded separately and confirmed before the second half; exceptions for forfeited privileges are explicitly unsupported in normal mode unless modeled and reviewed.
- Resolve the second-half **kicking team, receiving team and defended goals** separately from first-half choices. Assign Q3 team directions from those second-half defending-goal choices, not from a universal Q3 sign and not from the first-half receiving team. Generate a **second-half kickoff event** and derive the ensuing scrimmage possession/spot from the actual sampled kickoff outcome.
- Kickoff to begin Q3 occurs **even if a team possessed the ball as Q2 ended**, barring an explicitly modeled applicable exception. Preserve the two halves' kickoff rights in a persisted coin-toss choice ledger.

**Historical/legal counterexample, NEVER normal default:** A wins the toss and explicitly chooses **kick** (does **not** defer); B receives to open. B later has first second-half choice and could receive again, making A kick twice. **Normal simulations MUST reject this situation** rather than randomly generating it. Only a **source-verified historical reconstruction** or **deliberate opt-in exception scenario** may accept it. Do not write tests that require the normal game generator to pass a two-kickoffs-by-one-team sequence.

**Required normal defer example:** A wins and defers. B chooses to receive in the first half; A kicks. A has first second-half choice and selects receive; B kicks to begin Q3. **Required normal receive example:** A wins and receives Q1; B has first second-half choice and receives Q3, so A kicks Q3. **Both normal paths have one half-start kickoff per team.**

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
coin_toss: winner, defer, 1H/2H choice ledger, forfeiture flags, policy_mode=normal_nfl_game|historical_reconstruction|explicit_exception_scenario
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
- `punt`, `field_goal_attempt`, `try`, `kickoff`, `safety_free_kick`, blocked/returned variants, with distinct participants/clock/possession/spot rules or **explicit not-yet-supported refusal**. Blocked scrimmage kicks require the Rule 9-2/9-3 recovery distinctions in section 5A; a safety free kick follows Rule 6 and 11-5-2, **not** the blocked-punt recovery rules.
- `quarter_end_change_goals` Q1/Q3 (drive continues); `halftime` (half ends; resolve second-half choices and kickoff); `game_end`; `overtime` separately versioned/unsupported until tested.
- `timeout`, `two_minute_warning`, `clock_runoff`, clock-start/stop, penalty enforcement and untimed-down extension as separate substates; do not infer these from a single sampled yards value.

E1 may ship a **scoped research drive** with unsupported transitions clearly labeled as such; E2 cannot claim a **complete legal NFL game** until required restarts/score/clock/possession paths either work or the output is explicitly marked **partial/unverified**, not `valid_full_game=true`.

## 5A. Blocked scrimmage-kick recovery and safety-kick transition (Rule 9-2, 9-3, 11-4-2, 11-5-2)

**Source/edition:** [Official NFL 2026 playing rules (PDF)](https://static.www.nfl.com/image/upload/fl_attachment/league/tqivdkzt9mu6wdgsh1ku.pdf), Rule 9 Section 2 (touching), Rule 9 Section 3 Articles 1 and 2 (recovery), Rule 7-3 (series), Rule 7-2-1 (ball dead), Rule 9-4 (goal-line/dead-ball cases), Rule 11-4-2 (missed field goals), Rule 11-5-2 (ball in play after safety). **Correct citation is 9-3-1 / 9-3-2, not 2-3-1 / 2-3-2.** These are separate from free-kick rules in Rule 6.

### 5A.1 Scrimmage-kick recovery decision table (punt or field-goal attempt)

Here **kicking team** means the team that punted or attempted the field goal, **receivers** its opponent, and **line** the original line of scrimmage. Determine whether the receivers touched the ball **beyond the line** before awarding a new series. An attempted block or passive player blocked into the ball does not necessarily count as qualifying receiver touching (9-2-2 Note 2; 9-2-4). Touching **behind** the line is not a substitute for touching **beyond** it.

| Recovery and touching facts | Ball status, possession and next series | 2026 authority |
| --- | --- | --- |
| Kicking team recovers **behind** original line; no receiver touch beyond it, including a kick that crossed the line and returned | Ball may be **advanced**. Same series continues if the kickers are short of the original line to gain at the dead-ball spot. Advance to the line to gain earns a new first down. If it was fourth down and the kickers remain short, receivers obtain possession on downs at the dead-ball spot, barring enforcement or another exception. | 9-3-1 Item 1; 7-3-1/2 |
| Receivers touched the kick **beyond** original line; ball returns behind it; kicking team recovers | Ball may be **advanced**; award kicking team **a new series** because a rule-defined change of possession occurred, regardless of whether it advanced to the old line to gain. | 9-3-1 Item 2; 7-3-1(d) |
| Kicking team catches or recovers **beyond** original line **after receivers touched beyond it** | Kick becomes **dead on recovery**; normally kickers receive **first-and-10** at recovery spot. If qualifying recovery is in receivers' end zone, apply the specific touchdown rule. Do **not** allow a post-recovery return. | 9-3-2 Item 1; 9-4-1(c) |
| Kicking team catches or recovers **beyond** original line **without** receiver touching beyond it | Kick becomes **dead** and receivers are awarded the ball, generally first-and-10 at the catch/recovery spot. Apply first-touching options, goal-line/touchback treatment and missed-FG exceptions when applicable. Receiver touching *behind* the line alone does **not** validate kicking-team recovery beyond it. | 9-3-2 Item 2/3; 9-2-2; 9-4; 11-4-2 |
| Receivers catch or recover a kick | Receivers may advance, subject to the fair-catch and goal-line exceptions; the ensuing spot depends on the actual dead-ball result. | 9-3-3; 10-2; 9-4 |

**Important boundaries:**

- The location of **the recovery** relative to the **original** scrimmage line is not the same as the final dead-ball spot after a permitted advance. Record both, and retain the original down, line to gain, and kick type. A behind-line recovery does not automatically end the play or force a new drive.
- A receiver's touch in an attempted **block in the immediate vicinity of the line**, or passive contact caused by being **blocked into the kick**, does not automatically qualify as receiver touching for 9-3-1 Item 2 or 9-3-2 Item 1. Track the manner and location of first legal touching, not just a boolean `touched`.
- A fourth-down blocked punt recovered and advanced by the punting team short of the line to gain is **turnover on downs** in the no-qualifying-touch case. A blocked punt recovered and advanced *to or past* the original line to gain is a first down. An intervening qualifying touch beyond the line changes the series ruling.
- A blocked **field goal** remains a scrimmage-kick case, but do not apply the ordinary missed-FG spot rule blindly. Rule 11-4-2 has explicit exceptions when receivers touch the ball beyond the line or when the kick ends behind the line. End-zone, touching, fouls, and enforcement must be checked separately. A refused blocked FG stays refused until these facts are represented.
- Illegal first touching and touching by an out-of-bounds kicking-team player can alter the receivers' award/options (9-2-2/9-2-3). Do not turn every kicking recovery beyond the line into a penalty or a legal new possession.

**Minimal reducer evidence before permitting a result:** `kick_type` (punt/FG); `original_scrimmage_spot`; `original_down`; `original_line_to_gain`; `kick_crossed_line`; `receiver_touched_beyond_line` plus source/manner/timing; `recovery_team`; `recovery_spot`; `recovery_side_of_original_line`; `post_recovery_advance_end` if legal; `dead_ball_reason`; `resulting_possession`; `resulting_spot`; `resulting_down_and_distance`; `score_effect`; `clock_effect`; and any `foul`/`touchback`/`first_touching` or missed-FG exception. These are **engineering requirements**, not a claim the existing shared `GRIDIRON-CONTRACT-v1` already contains them. Add a separately versioned research/output extension if needed; leave shared v1 byte-identical until both projects explicitly approve a versioned contract change.

**Fail closed:** If any fact required for the applicable branch is absent or cannot be legally derived, emit a named refusal (for example `blocked_punt_kicking_recovery_not_modelled` or `blocked_field_goal_not_modelled`). A refusal is **not** a turnover, final score, completed regulation game, or `valid_full_game=true` result. Do not repair refusal frequency by resampling a different play or relaxing the independent possession/score checker.

### 5A.2 Safety free kick: separate restart, not a blocked scrimmage kick

- A safety awards **two points** to the opponent; the **team scored upon** must next free kick from its own **20-yard line**, subject to applicable enforcement and period-extension rules. A safety kick may be a punt, drop kick, or place kick (11-5-2; 6-1-1(b), 6-1-2). It remains a **free kick**, not a scrimmage punt governed by the Rule 9-3 recovery table.
- Close the drive that ended in the safety **before** appending the restart kick. Preserve distinct `kicking_team` (the team scored upon) and `receiving_team` (normally the team awarded the safety). The actual next scrimmage offense/spot must be resolved from the **legal free-kick outcome**; never infer it from the mere presence of a safety or a nominal receiving team.
- **Gridiron research/viewer grouping convention:** if the generated safety-free-kick/refusal event is attached to a receiving-team-owned pending drive, open that **new** drive before recording the kick, set the generator's current pending offense to that receiving team, and keep the refusal/event in the same pending drive. This is an **internal event/drive representation rule**, not a claim the receiving team already possessed the live kicked ball. A legal kicking-team recovery would need explicit resolution and could override the expected receiver.
- Missing safety-kick outcome distribution, receiver/recovery, legal spot or clock handling means **explicit `safety_free_kick_not_modelled` refusal**. No synthesized punt outcome, receiver at a fixed spot, inherited pre-safety kicking-team drive, or completed-game certification.

### 5A.3 Mandatory deterministic fixtures and independent checks

| Fixture | Expected independent assertion |
| --- | --- |
| Behind-line recovery on third down, no qualifying receiver touch, short of line to gain | Kickers can advance; fourth down at the actual dead-ball spot with remaining distance; same series |
| Behind-line recovery on fourth down, no qualifying receiver touch, short of line to gain | Receivers get new first down by turnover on downs at dead-ball spot; no fictitious punter first down |
| Behind-line recovery advances across line to gain | New first down for kickers, at real forward-progress spot |
| Receivers touched **beyond** line before ball returned behind it | Kickers recover behind and receive new first down; separate from same-series branch |
| Kickers recover **beyond** line after qualifying receiver touch | Immediate dead ball; kickers' first down at recovery spot, or correct end-zone scoring case; no run after recovery |
| Kickers recover **beyond** line without qualifying receiver touch | Dead ball and receivers awarded possession, including missed-FG/touchback/first-touching applicable cases |
| Receiver only touched behind line, or passive blocked-into-kick touch | No invented qualifying touch beyond line; apply corresponding behind/beyond rule |
| Blocked FG with absent location/touch/outcome facts | Named refusal with no made-up score, spot or end-game completion |
| Safety from scrimmage followed by safety free kick | Safety closes old drive; post-safety event opens distinct pending phase/drive; kicker and receiver correctly identified; any viewer receiver-owned pending drive remains consistent through refusal |
| Unsupported free kick after safety | `safety_free_kick_not_modelled`, **no final result**; no wrong-team possession-continuity event |

Add fixed-seed before/after comparisons of completed-game counts, refusal categories, score continuity, possession continuity and outcome distributions; an independent checker must flag deliberately mutated versions of these paths. Historical source PBP and a separately frozen cohort remain the football-outcome reference, not the generator's own output.

**Implementation state as of this rules clarification:** the 600-seed safety-kick survey reported **505 complete regulation / 88 blocked-FG refusals / 4 blocked-punt kicking-recovery refusals / 3 safety-kick refusals**, with possession-continuity findings reportedly **6 → 0** after a two-line Gridiron repair. This is **agent-reported evidence**, not independently re-run here, and does **not** establish implementation of the blocked-kick recovery branches above. Keep these cases fail-closed pending code, deterministic fixtures, independent review and contract-compatible integration.

## 6. Rules for sample selection are not rules of football

The LP E1 branch [`b58a19f1`](https://github.com/micahp/legendarypicks/blob/b58a19f1350897b0ded2841bcf441e70a36449af/docs/SEQUENCE-E1-LP-DRIVE-2026-10-24.md) generated a **retrospective** statistical research sample. Its four-start, 4,800-seed survey produced **4,396 completed by its current limited checker** and **404 incomplete thin-cell runs**. Terminals: 1,088 touchdowns; 509 turnovers; 2,075 turnovers on downs; 724 end-of-period. No safety fixture. It currently **does not choose punts or field goals**, and uses go-for-it-only plays on fourth down: those distributions are **not realistic football frequencies**. It also excludes important event types, timeouts, quarters, score and player identities; current `end_of_period` is not a valid **drive end at Q1/Q3**, only a period transition (or Q2 halftime / Q4 game terminal as appropriate). Do not use 4,396/4,396 checker passes as a blanket NFL rule validation.

The E0 branch [`166bb84f`](https://github.com/micahp/legendarypicks/commit/166bb84fc20412c2122a2e12835dae16e2d19e73) records an **open touchdown flag bug**: the sampled row's touchdown flag describes its own starting yardline, not necessarily the synthetic state. E1's reducer uses the actual simulated goal distance, but E0 remains unfixed. Preserve E0 seed-1042 fixture and document that defect until independently fixed and tested.

For future **as-of** predictive claims, LP must exclude all events/results unavailable before a declared kickoff/time cutoff (E0's 5,572 cell contained 1,016 future-dated results); retain a separate properly grouped holdout. An outcome from 2022 being sampled into a 2025 game does not by itself validate a pool that includes future 2025 games.

## 7. Mandatory test matrix (no extrapolation from E0 seed 1042)

| Case | Required check |
| --- | --- |
| Opening toss winner **defers**, opponent receives | Persist first-choice rights; kickoff to opponent; deferred team first choice for Q3 |
| Opening winner explicitly chooses **kick** | **REJECT in normal mode**; allow only source-verified history or explicitly opted-in exceptional test mode |
| Toss winner chooses **defended goal** as first privilege | **REJECT in normal mode**; allow only documented historical reconstruction or explicit exception test |
| Q1→Q2 | No kickoff or new drive; preserve possession, down/distance and offense-relative spot; flip defended goals |
| Q3→Q4 | Same change-of-ends continuation, not period-as-drive-ending |
| Q2→Q3 | End existing half-drive; reset half timeouts/clock; apply second-half choice; **kickoff event**; first Q3 scrimmage spot comes from kick outcome |
| Both half-opening kickoffs | Normal mode **MUST** have exactly two `half_start` kickoffs, one Q1 and one Q3, **different kicking teams**, and a matching toss/choice ledger; test both receiver and defer opening paths |
| Turnover on downs in Q2 | New offense is other team at same dead-ball spot; `dir` flips, `yardline_100` complements, `los` remains consistent |
| Touchdown | Apply **six-point** score plus distinct try; after try proceed to kickoff as rules require; no fictional auto-PAT |
| Made FG / safety | Score per Rule 11 (FG **3**, safety **2**); schedule correct post-score kick/restart; safety kick from the scored-upon team's 20 (11-5-2) |
| Fourth down | Choose between punt, FG, and go-for-it conditional on field/time/score; do not use go-for-it data as all NFL fourth downs |
| Clock/timeouts | 15-minute regulation quarters, **three timeouts per team per half**; no clock increase; end of Q1/Q3 is not drive terminal |
| Unsupported rules | Reject with an explicit unsupported code or mark incomplete; never silently force a turnover on downs, normal run, or finished game |
| Safety kick / pending possession | Close the pre-safety drive; create distinct post-safety free-kick phase; kicking team is the team scored upon. Any adapter that groups a pending/refused kick under its **expected receiver** must start a new drive and keep its refusal in that drive; this is an event-grouping convention, **not** proof of legal possession after the kick |
| Blocked punt/FG, kickers recover **behind** original line | Apply 9-3-1: kicking team may advance; if no qualifying receiver touch **beyond** line, same series unless line to gain reached; on fourth down short of line to gain, turnover on downs at dead-ball spot, absent a separate rule/penalty |
| Blocked punt/FG, receiver first touched **beyond** line, kickers recover behind | Apply 9-3-1 Item 2: a new series to kickers; do not treat as a same-series fourth down |
| Kickers recover **beyond** line | Apply 9-3-2: dead immediately; qualifying receiver touch beyond line permits kickers' new series (or touchdown under the end-zone rule); absent such touch, award receivers with first-touching/touchback/missed-FG exceptions as applicable |
| Blocked-kick missing context | No inferred touch, recovery side, spot, line-to-gain result, penalty or clock; preserve refusal and no full-game certification |
| Overtime/untimed down/penalties | Explicit rule-version-sensitive guards and test cases before claiming full-game completeness |

## 8. Near-term work order, based on real current branches

**LP sequence agent (critical path):** Implement the **strict normal-simulation kickoff invariant first**: each team kicks off once to start a half, two half-start kickoffs total, abnormal legal choices impossible without explicit exceptional mode. In normal mode, a first-choice captain always chooses receive; the opening winner may receive or defer. Build a seeded invariant checker; separate post-score kickoffs. Keep [E1 `b58a19f1`](https://github.com/micahp/legendarypicks/commit/b58a19f1350897b0ded2841bcf441e70a36449af) and [E0 defect note `166bb84f`](https://github.com/micahp/legendarypicks/commit/166bb84fc20412c2122a2e12835dae16e2d19e73) as unchanged research evidence. First introduce a **unit-tested coin-toss/half kickoff + change-ends state machine** around (not a rewrite of) the existing reducer. Then fourth-down decision families and scoring/clock ledger. Do not equate the current 4,396 checker passes with official-rule conformance. Reconcile which E1 drive outcomes continue across Q1/Q3 and which actually terminate. Pin one **authored** two-half example to show kickoff rights and correct Q3 opening.

**Gridiron viewer agent:** Build a read-only kickoff/half/quarter timeline and rule-state display without inventing 22-player physical kickoff choreography. Use LP `dir_by_team[quarter]` and verified `los` for 3D coordinates; do not validate a universal Q1–Q2 or Q3–Q4 direction for **every offense**. Preserve E0 retrospective, immutable, missing-value policies and versioned distinction between E0a record display and E0b player-specific 3D replay.

**Coordinator:** Gate E1 acceptance on a correct, documented sequence of actual legal **drive** terminal versus **quarter** transitions, including punts/FG choices or explicit limitations. Gate E2 full-game claim on both-half kickoffs, possession/scoring/restarts and reconciliation. Never imply full 2026 NFL rule coverage where only a narrow test passes. Move toward a complete game instead of isolated motion experiments.

## Tracking of rule implementation

| Rule family | E0 demo | E1 `b58a19f1` | Required E2 |
| --- | --- | --- | --- |
| Snap/line to gain/downs | Minimal legality | Limited reducer checked | Cross-quarter/full-game invariants |
| Coin toss/deferral | Not modeled | Not modeled | Complete choice ledger **and strict normal receive/defer policy; no sampled exception** |
| First- and second-half kickoff | Not modeled | Not modeled | Exactly two half-start kickoffs, **one by each team**, verified against toss ledger in normal mode |
| Change goals Q1/Q3 | Demo shortcut, **not valid general rule** | Quarter transitions not implemented | Correct field-end mapping, preserve series |
| Fourth-down choices | Scrimmage only | Go-for-it only | Punt/FG/go-for-it decisions |
| Passing/rushing/turnovers | Four events | Six sampled families | Full legal variants and provenance |
| Scoring/tries | No score | TD/safety terminals, no points | Score/tries/restarts |
| Clock/timeout/quarter/halftime | Q2 static fixture | Within-quarter sampled runoff only | Legal transitions and start-stop |
| Player lineup/3D physical motion | Not modeled | Not modeled | Separate honest replay status |
| Overtime/penalty exception handling | None | None | Explicit tested coverage or blocked full-game claim |

**2026-10-24 documentation amendment:** Added section 5A and the recovery/safety-kick acceptance matrix, verified against the official 2026 NFL rulebook PDF (9-2, 9-3-1, 9-3-2, 7-3, 11-4-2, 11-5-2). This is a **rules-only** change on LP `dev`; it does not implement previously refused blocked kicks or update shared contract-v1. Gridiron repair details and 600-run outcomes are labelled agent-reported, not independently verified or attributed to an unknown code SHA.

**Change-control:** Amend this file in a dated section with updated official rule section/edition, exact LP/GP code commit, tests and status. If rules change in 2027, create a versioned successor rather than silently altering what `rules_version=2026` means.
