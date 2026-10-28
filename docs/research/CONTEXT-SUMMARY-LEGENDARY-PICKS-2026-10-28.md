# Context summary: Legendary Picks, 2026-10-28

Purpose: a reference for the Legendary Picks work as of 2026-10-28. It separates what was verified in this session from
earlier history, which is cited from git or from the project memory index and was not re-verified here.

## 1. Repositories and state

| checkout | path | ref | state |
|---|---|---|---|
| dev worktree | `/root/legendarypicks` | local `dev` at `79e8e05d`; `origin/dev` at `7ce9ae4e` | **ahead 26, unpushed**. Uncommitted edits, left as found: `.claude/skills/measurement-is-a-claim/SKILL.md`, `components/Leagues/types.ts`, `pages/leagues/[league].tsx` |
| fix branch | `fix/week08-simulation-errors` | `fee78a05` (local and origin agree) | the blocked-kick guard lives here |
| integration worktree | `/root/lp-event-integration` | branch `research/lp-event-integration-2026-10-28` from `79e8e05d` | research only; this session's Phase 1 work |

Nothing was pushed to `dev` or `main`, merged, deployed, or changed in production defaults.

## 2. Event-based NFL simulator: architecture as found

Source: `scripts/nfl_sequence/` (69 modules at `79e8e05d`; the manifest in section 5 lists 70 with the generator). The
simulator is organised in layers:

- **Authoritative reducer.** `reducer.py`. Pure functions: a caller samples an event, then `apply_play` makes the legal
  transition. No sampling and no data access. Consumers: `e0_single_play`, `e1_drive`, `game_state`.
- **E2 game framework.** `game_state.py` (about 1,600 lines). Coin toss, kickoffs, scoring, clock, tries, overtime, special
  teams, and the linkage of E1 drives into one regulation game. It imports `e1_drive`, `game_stats` and `reducer`.
- **E1 drive generator.** `e1_drive.py`. Samples observed plays in down, distance and field cells. It does not model intent.
- **Reference data.** `e2_reference.py` loads observed reference data read only from the dev play-by-play table. Window 2022 to
  2025, weeks 1 to 18. The pool includes the whole of 2025.
- **Matchup context.** `contextual_pool.py` (S0 keeps the uniform empirical pool; S1 ablations reweight it), `pregame_context.py`
  (cutoff-filtered opponent-adjusted point ratings), `pregame_snapshot.py` (a reproducible matchup and depth-chart snapshot at a
  cutoff), `availability_adapter.py` (a frozen weekly availability snapshot), `rule_regimes.py` (rule registry by season).
- **Participants.** `game_stats.py` assigns the QB from the frozen depth chart and samples backs and receivers from it. **This
  happens after the event is sampled.** Confirmed in this session. It is the limitation the integration is meant to remove.
- **Observed distributions and evaluation.** `e3_observed_distributions.py` (2022 to 2025 export) and `replay_evaluation.py`
  (scoring of frozen forecasts).

## 3. Blocked-kick guard reconciliation (verified this session)

- The guard is two commits on the fix branch: `e133ab15` (fix blocked-kick period transitions) and `fee78a05` (preserve
  blocked-kick outcome weights).
- Both commits are ancestors of **local `dev`** (`79e8e05d`). The four guard files are identical to `fee78a05` on `dev`.
- **`origin/dev` (`7ce9ae4e`) does not contain either commit.** The divergence is between origin dev and local dev. Local dev
  is 26 commits ahead of origin dev and unpushed. Those commits include the fix, identity and spine-merge work, and a revert of
  `fix/identity-stale-rows` (`8f566485`).
- What the guard does: a period-expired blocked-kick record keeps its draw weight at every quarter. If it is drawn at Q1 or Q3,
  the play blocks with a named status, because the next possession and spot are unknown.
- Verification on the integration base: `pytest test_game_state.py test_e1_transitions.py` gives **187 passed**.
  `test_period_expired_draw_weight_is_preserved_across_all_quarters` (`test_game_state.py:313`) checks the weight preservation.
  A numerical before-and-after comparison of draw weights has not been run.
- **Decision needed:** the integration base. Option A is local `dev` (`79e8e05d`), which holds the guard and 25 unpushed commits
  that are not reviewed for this work. Option B is `origin/dev` plus cherry-picks of `e133ab15` and `fee78a05`, which has not
  been tried. The integration branch is currently on option A. No merge has been made.

## 4. Integration plan and status

The integration instructions are in `docs/research/LP-EVENT-INTEGRATION-BASELINE-2026-10-28.md`. The plan has six phases.

| phase | content | status |
|---|---|---|
| 1 | Integration baseline: code inspection, the guard reconciliation above, a source-to-consumer manifest | **partly done**: guard verified; manifest generated; model-status and data-dependency review of key modules not complete; base decision pending |
| 2 | Cutoff-safe historical playbook export and adapter, built from eligible games only | not started |
| 3 | Versioned team and coach decision interface, separate from the try policy and fourth-down decisions | not started |
| 4 | Statistical QB and player decisions, with participants chosen before the event outcome | not started |
| 5 | Wiring the complete sequence through the existing reducer and clock machinery, with per-play and per-drive output | not started |
| 6 | Tests and historical evaluation against S0 and the 2025 drive reference | not started |

The plan's rules: no 2026 holdout reads; no push or merge to `dev`; no production default change; S0 unchanged with the same
inputs and seeds; any new behaviour behind an explicit research-only mode.

## 5. Source manifest (this session)

`scripts/nfl_sequence/build_source_manifest.py` (committed in this session on the integration branch) generates
`docs/research/LP-EVENT-INTEGRATION-SOURCE-MANIFEST-2026-10-28.{md,json}` at checkout `79e8e05d`. It covers 70 modules. For each
module the manifest records the git blob hash, the SHA-256, the last commit, the consumers and imports within the directory,
and the data paths it names. Key modules and their status are in the baseline document (section 3 of it).

Consumer graph, verified from the manifest:

- `reducer.py` is consumed by `e0_single_play`, `e1_drive`, `game_state`, and two tests.
- `game_state.py` is consumed by 13 modules, including `emit_game`, `e2_reference`, `game_survey` and `rules_matrix`.
- `e1_drive.py` is consumed by 14 modules, including `contextual_pool`, `e2_reference`, `game_state`, and the clock diagnostics.
- `game_stats.py` is consumed by `game_state` only, so changing participant selection is contained.

## 6. Cutoff-safety findings (this session)

- **2026 names in the code.** 32 modules under `scripts/nfl_sequence` contain the string `2026`. This is a name match, not a data
  read. Each needs an audit for defaults that would bring 2026 inputs into a historical run. That audit is Phase 1 follow-up.
- **The E1 pool includes 2025.** A game simulated earlier in 2025 must not draw from the 2025 pool after its own cutoff. The
  cutoff filters in `contextual_pool` and `pregame_context` are the mechanism. Their coverage is not verified.
- **Participant assignment happens after the event** (section 2).
- **Playbook priors.** The playbook decision model v1 is **not on this base**. It is on
  `origin/research/nfl-historical-splits-2026-10-27` at `scripts/nfl_sequence/splits/decision_model.py`. The base has no playbook
  integration: a search for "playbook" in `scripts/nfl_sequence` returns nothing.
- **Full-season priors cannot simulate earlier games.** The 2025 full-season playbooks cannot drive a game earlier in 2025. The
  priors must be rebuilt from games before each cutoff. A 2025 season can support retrospective work, but it is not a pristine
  independent holdout.

## 7. Earlier Legendary Picks history (cited from git, not re-verified this session)

Commits visible in this session's log of `dev`, cited by subject:

- Identity: `2b9cb97a` and `aadafc62` (the 2026-10-27 identity incident diagnosis), `b8c81080` (only roster rows refreshed this
  run take part in matching), `8b8dbcf6` and `9403784e` (spine_merge does not bind on name and club alone), `cedca71d`
  (Leagues Cup keys bind to their home-league player), `d7810fc0` (catch publisher double listings).
- Overtime: `2c2a03e1` and `20d40729` (regular-season overtime from observed drives under Rule 16), `db2c4d87` and `055c78f5`
  (300-seed overtime validity runs), `9a6c6bfa` (paired rules-only check).
- Blocked kicks: `33e5c2e1` and `b8231c3b` (sampling a blocked kick from states it covers; 300-seed validity run).
- Schedules and recap: `e4c64ee9` (NFL schedule every four hours), `c4cfb42b` and `892f9c81` (recap fallback when no model answers).
- NBA: `0cb44a3a` (stakes and standings on dev), `01dc4a5b` (NBA player box scores).
- The Week 8 frozen runs and their snapshot must not be modified (standing rule).

From the project memory index (not re-read this session): the data spine and coverage contract, the defect shapes, the
published-roster rules, and the NFL model-pick rules (`docs/MODEL-PICK-RULES.md`). Those documents are the authority for
their topics.

## 8. Rules in force for this work

- The 2026 holdout is sealed. Nothing from 2026 is read, including games, simulations, outputs and mixed-season files.
- No push, merge, or deploy to `dev` or `main`. Pushing the research branch needs the user's explicit authorisation, which has
  not been given for this branch.
- S0 must stay identical with the same inputs and seeds. New behaviour sits behind an explicit research-only mode.
- Do not change the authoritative reducer's legal transitions. Do not discard the uncommitted dev edits.
- No em or en dashes in replies, commits or documents.

## 9. Open items

1. Choose the integration base (section 3, options A and B).
2. Finish Phase 1: review the model status and data dependencies of the key modules, and audit the 32 modules that name 2026.
3. Decide whether the research branch may be pushed.
4. Confirm the draw-weight preservation numerically, before and after `e133ab15`.
5. Start Phase 2 only after items 1 to 3 are settled.

## 10. Index

- Baseline and integration plan: `docs/research/LP-EVENT-INTEGRATION-BASELINE-2026-10-28.md`
- Source manifest: `docs/research/LP-EVENT-INTEGRATION-SOURCE-MANIFEST-2026-10-28.md` (and `.json`)
- Generator: `scripts/nfl_sequence/build_source_manifest.py`
- Reducer and framework: `scripts/nfl_sequence/reducer.py`, `scripts/nfl_sequence/game_state.py`
- Guard tests: `scripts/nfl_sequence/test_game_state.py`, `scripts/nfl_sequence/test_e1_transitions.py`
