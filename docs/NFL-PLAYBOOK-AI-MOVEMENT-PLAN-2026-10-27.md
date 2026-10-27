# NFL playbooks for every team and season, and their use in AI player movement (2026-10-27)

Status: plan. Not yet executed. Execution is assigned to hermes2 (the Gridiron repo agent). It is queued behind the Week 8
frozen simulation runs, which hermes2 is running now (five games active at 6,000 of 10,000 seeds, six queued). Nothing
has been sent to hermes2. The 2026 season is the sealed holdout for model evaluation. A playbook is descriptive, but
the 2026 playbook is limited to Weeks 1 to 7 (section 4).

## 1. Scope

- **Playbooks.** One per team and season for 2022, 2023, 2024 and 2025, and one for 2026 in season. That is 32 teams for
  each season, 128 team-seasons plus 32 in-season 2026 playbooks, 160 in total.
- **Use.** Priors for how AI players move in the Gridiron physics simulation, in the prospective (pregame) demo only.
  Observed-play replays keep their charted constraints and do not use playbook priors.
- **Out of scope.** Madden ratings, market prices, and any use of 2026 results to choose a model or tune a movement policy.

## 2. What already exists

Repo: `/root/gridiron-physics` (branch `main` for the playbook files; the work runs on a research branch).

- `pipeline/build_playbooks.py` builds one JSON per team and season (`schema_version: gridiron.playbook.v1`). It draws on
  nflverse play-by-play and participation, joined by legacy game ID and `play_id`.
- `data/playbooks/` holds 14 committed 2025 profiles: ATL, BAL, CAR, CHI, CIN, DAL, DET, GB, MIA, NE, NYJ, PHI, SF, TB.
  The other 18 teams for 2025 are missing. Nothing exists for 2022 to 2024 or for 2026.
- `docs/PLAYBOOKS.md` sets the rules: five provenance categories, Wilson 95% intervals on every rate, a denominator and
  missing count for every distribution, separate postseason exclusions, and no outcome labels in the sampler.
- The 2025 NE and CHI files are the reference. Rebuilding them from the pinned inputs must reproduce them exactly, or the
  difference must be explained, before any other season is built.

## 3. Data available by season

| Source | 2022 | 2023 | 2024 | 2025 | 2026 (through Week 7) |
|---|---|---|---|---|---|
| Play-by-play (nflverse) | yes | yes | yes | yes | yes, 107 completed games |
| Participation (formations, personnel, routes, coverage type, man or zone, pressure, rushers) | yes | yes | yes | yes | not on disk |
| Charting release (`ftn_charting`: formation, motion, play action, RPO, blitz counts, drops) | yes | yes | yes | yes | yes, 106 games |

Notes:

- Participation is on disk for 2016 to 2025 (plus an older 2023 file). There is no 2026 participation file in the download.
  If it is published later, the 2026 playbook gains route, personnel and coverage fields. Until then, every 2026 field
  that depends on participation is marked missing, not inferred.
- The charting release is 2022 to 2026. It is the only source for motion, play-action, and blitz counts.
- Coverage type (`defense_coverage_type`) and man or zone (`defense_man_zone_type`) are charted in participation. They are
  not in the play-by-play, so the 2022 to 2025 playbooks have them and the 2026 playbook does not.

## 4. Time basis and leakage rules

1. **2026 playbooks use Weeks 1 to 7 only.** The Week 8 frozen runs have a cutoff of 2026-10-27T18:20:23Z. A playbook used
   by a Week 8 run must be a frozen, content-hashed snapshot built from Weeks 1 to 7. It is never rebuilt in place.
2. **A playbook for season S is built from completed games of season S.** Its use in a forecast for a game in S must be
   limited to games completed before that forecast's cutoff, not the whole season. For a historical test, the season
   playbook is descriptive, not a pregame input. For a pregame use, the playbook is rebuilt from earlier weeks only.
3. **Labels and outcomes never enter a playbook.** The sampler reads attributes, not results. The `outcome_label` field
   stays in its own subobject, as in `PLAYBOOKS.md`.
4. **Denominators are reported.** A rate with n below 30 is shown but not interpreted.

## 5. Playbook contents

The existing `gridiron.playbook.v1` schema is reused, with no new fields for 2022 to 2025. Each team-season file holds:

- **Offense.** Formation share (shotgun, under center, pistol) from participation. Personnel-code share. Run and pass
  split by down and distance. Run gap and direction. Pass depth and location. Routes (participation). Play action,
  motion, RPO and no-huddle rates (charting). Third down, short yardage, red zone, goal line, and two-minute splits.
- **Defense.** Personnel-code share. Coverage type share (COVER 1, 2, 3, 4, 2-man and others). Man or zone share. Pass
  rusher count and pressure rate (participation). Blitz rate (charting). Defenders in the box for run plays.
- **Coverage.** Eligible plays, participation join count and missing count, source IDs, and excluded postseason rows.

For 2026 the same keys are written. Fields that depend on participation are present with a missing count equal to the
denominator, and a `coverage_note` says why.

## 6. Build and validation gates

1. Rebuild NE-2025 and CHI-2025 from the pinned inputs. They must reproduce the committed files. Any difference is
   explained in the build report before the next step.
2. Build the other 2025 teams (18 missing). Gate: every observed and missing count equals its denominator, and the
   eligible play count equals the emitted record count, as `PLAYBOOKS.md` requires.
3. Build 2022 to 2024 (96 team-seasons). Gate: the same checks, plus a check that the shotgun share from play-by-play
   matches the formation share from participation within 1 point, for each team-season.
4. Build 2026 through Week 7 (32 team-seasons). Gate: every participation-based field is missing, not zero, and the
   play-by-play counts match the completed-game count (107 games).
5. Write a build report: counts per team-season, missing shares, and any team whose totals do not reconcile.

## 7. How the playbooks move AI players

The director in the physics engine is outcome-constrained. Observed plays are reproduced from charted outcomes, so
playbook priors do not apply there. The prospective demo has no outcome, so it needs priors for decisions the physics
cannot infer. Playbook priors would set:

- **Alignment and personnel.** Which formation and personnel the offense shows, from the team's shares.
- **Coverage shell and man or zone.** Whether a defender shadows a receiver or drops to a zone, from the team's shares.
- **Pass rush.** How many rushers attack, and a blitz path for one or more defenders, from the team's blitz and rusher rates.
- **Run gap.** Which gap the offensive line and the back attack, from the team's gap distribution.
- **Routes.** Which route tree each receiver runs, from the team's route shares, and the pass depth.

The priors choose decisions. The physics controller still moves the bodies. Each choice is drawn from the playbook with the
team's shares as weights, and the drawn values and the playbook snapshot ID are written into the demo record.

## 8. How AI movement is judged

The movement policy decision of 2026-10-24 in the physics repo found that the current controller adds only about 3.7 mm
at one second over a constant-acceleration predictor (about 97% of the benefit comes from the predictor). So a change
to AI movement counts only if it beats that baseline.

Validation sources on this box (inventoried 2026-10-27, read-only, `/root/nfl-tracking-data`):

- `bdb2025`: **2022 season**, Weeks 1 to 9 (game IDs begin `2022`). Tackle-event plays, each with a frame-level trace (before
  snap, snap, after snap), ball rows, and events (tackle, first contact, out of bounds). Week 1 holds 16 games and 1,952 plays.
  The folder name is the competition year, not the season.
- `bdb2026-prediction`: **2023 season**, Weeks 1 to 7, the `train` split only. Pre-throw input frames with player positions,
  roles and sides, and the post-throw positions of the player to predict. The hidden test split is not on disk.

No 2024, 2025 or 2026 season tracking is on disk.

Gates:

1. Each playbook prior is checked against the observed tracking for the seasons it covers. Example: observed man or zone
   assignments against the coverage type charted for the same play.
2. The AI with playbook priors is compared with the current AI and with the constant-acceleration predictor, on the same
   plays, with intervals. A change counts as material only if it beats the constant-acceleration predictor by more than the
   controller's current margin.
3. A null result is reported as null. The movement policy keeps the current controller until a change is material.

### 8A. Protocol for the movement work (decided 2026-10-27)

The user's order was: 2025 first, train on 2025, check the match against 2026, then tune. The data does not allow that
order, and the holdout rule does not allow tuning on 2026. The protocol is:

1. **Playbook priors are fit on 2025.** Built from the 2025 participation and charting data, with the 2025 playbooks as the
   training description. These priors are the only thing fitted on 2025.
2. **Movement calibration is fit on 2022 tracking** (`bdb2025` folder, Weeks 1 to 9), with a within-season split. Fit the
   constant-acceleration predictor and the physics controller on the same plays.
3. **Movement validation is run on 2023 tracking** (`bdb2026-prediction` train, Weeks 1 to 7). Compare predicted and
   observed positions at the throw and after it, with intervals, against the constant-acceleration predictor.
4. **Tuning happens only on steps 1 to 3.** No setting is chosen using 2026.
5. **The 2026 holdout is one test, run once, after steps 1 to 4 are frozen.** There is no 2026 tracking, so it can test only
   play outcomes: whether the generated play's result distribution matches the charted 2026 outcomes for Weeks 1 to 7. It
   cannot test movement. The target and the metric are written down before the run and are not changed afterwards.
6. **2025 and 2026 tracking are needed for a movement check on the holdout season.** Acquiring them is a separate decision.

Items 2 and 3 use 2022 and 2023 data. They are not 2025 or 2026 results and are not holdout evidence.

## 9. Execution

- **Owner.** hermes2, on the Gridiron repo. The LP side reviews the outputs.
- **Start.** After the Week 8 frozen runs finish. Sending input to the hermes2 pane while those runs are active risks
  interrupting them.
- **Branch.** A new research branch in the Gridiron repo. The playbook files are committed there, never to `main`.
- **Handoff message.** Appendix A.
- **Status (2026-10-27).** The text was typed into the hermes2 codex pane (`hermes2:0.0`, pane `%13`) and not confirmed
  as submitted. The pane showed a Codex CLI update prompt ("Updating Codex CLI from 0.162.1 to 0.1... now?") and the
  Week 8 runs were reported active. The message must be confirmed in the pane before Part A is treated as started.

## 10. Open questions

1. Decided 2026-10-27: send the handoff now. Delivery was not confirmed: the hermes2 pane showed an open Codex update
   prompt when the text was typed. See the status note in section 9.
2. Decided 2026-10-27: the 2026 playbook stays frozen at Weeks 1 to 7 for the holdout. It is not rebuilt when Week 8
   completes.
3. Decided 2026-10-27 by the user: train on 2025 first, then tune. The inventory shows no 2025 tracking on disk, so the
   protocol in section 8A applies. The user also asked to check the 2026 result and tune on it. That conflicts with the
   holdout rule, so 2026 is used once, at the end, against a target fixed before any 2026 result is seen (section 8A).

## Appendix A. Handoff text for hermes2

Send only after the Week 8 frozen runs finish, or on the user's word.

> hermes2: new research job from LP (2026-10-27). Read `docs/NFL-PLAYBOOK-AI-MOVEMENT-PLAN-2026-10-27.md` on the LP research
> branch `research/nfl-historical-splits-2026-10-27` before starting. Do not touch the Week 8 frozen runs or their snapshot
> IDs. Part A: build the team-season playbooks in section 1 using `pipeline/build_playbooks.py`, in the gates of section 6,
> on a new research branch in the Gridiron repo. Start with NE-2025 and CHI-2025 as the reproduction check. Build the 2026
> playbooks from Weeks 1 to 7 only, marking participation fields as missing. Report the build counts and any team that does
> not reconcile. Part B (after Part A is reviewed): the movement evaluation in section 8. Do not merge to main, do not
> release, and do not change the director's outcome constraints.
