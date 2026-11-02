# SLC play-calling and opportunity task (2026-11-02)

Status: task specification, not yet approved for execution. Owner: manager. Executor: hermes2 (Codex).
Rule for every step: do not assume. If a definition, input, cutoff, join, threshold, or split is missing or
ambiguous, stop, record the exact question in the milestone reply, and wait for the manager's answer.

## 1. Goal

Formalize offense and defense play calling as explicit decisions inside the SLC model, so team opportunities
(plays, runs, dropbacks, drives), player opportunities (carries, targets, participation), and outcomes come from
football decisions in the correct order. Do not add hard workload caps. Do not change any default model until the
gates in section 5 pass.

## 2. Scope

In scope (research only, branch work in the LP research checkout):

- Opportunity generation: team run/pass choice, drive and possession volume, plays per drive.
- Participant allocation: which players are eligible and on the field, then carrier and target choice.
- Defensive responses: coverage, front, and blitz labels as conditional response proxies.
- Personnel and formation as decisions, using only verified pregame inputs.

Out of scope in this task:

- Hard workload cutoffs. Decided: not used.
- Simulated in-game injuries. Decided: not used as a workload correction. Later task only.
- Fatigue. Gate 6, starts only after the participation model passes gate 3.
- Coach-specific policy. Decided: deferred until a dated team/coach join is verified (gate 4 precondition).
- Named defensive playbook calls. Decided: not required. Labels are proxies (see section 4, WP4).
- Gridiron Physics changes. Gridiron stays responsible for movement. Its fixed-lineup builder is a later
  consumer, handled after the LP decision contract exists.

## 3. Verified facts (checked 2026-11-02 in the repos named)

| Fact | Where verified |
| --- | --- |
| SLC profile `v1_full_stack` exists and turns on `playcall_playbook` (2025 team playbook priors) | `scripts/nfl_sequence/slc_config.py` (V1_OPTIONS, profile resolver) |
| Decision, defense, formation, playbook, and pre-event modules exist | `scripts/nfl_sequence/decision_layer.py`, `defense_layer.py`, `formation_layer.py`, `playbook_prior.py`, `pre_event.py` |
| Holdout exposure record exists and names what has already been examined | `docs/research/HOLDOUT-EXPOSURE-RECORD-2026.md` |
| SLC calibration audit exists | `docs/research/SLC-LAYER-CALIBRATION-AUDIT-2026-10-29.md` |
| Play-call evaluation v2 exists | `docs/research/PLAYCALL-EVAL-v2-2026-10-28.json` |
| Participation data for 2022 to 2025 exists | `/root/gridiron-playbooks-research/data/raw/pbp_participation_{2022,2023,2024,2025}.csv` |
| Gridiron lineup builder fixes the offense to five OL, one QB, one RB, one TE, three WRs | `web/prototype-model.js` (Gridiron repo, branch `research/min-det-realism-seed-viewer-2026-11-01`) |
| Gridiron branch is 24 commits ahead of `origin/main`, head `a79f94f` | git, Gridiron repo (the write-up said 22 and `a147b80d`; both are out of date) |

## 4. Claims from the source write-up that are NOT yet verified

Each must be re-derived from a source artifact before it is used as an input or a stated result. Record the
source file and the recomputed value for each.

- Dallas simulated 31.35 runs per game vs 22.86 observed.
- Arizona: Michael Wilson 40% of simulated targets vs 23.3% observed.
- RB carry variance 1.77x observed; WR target variance 1.40x.
- Jacoby Brissett 5.35 simulated rushing yards per carry vs 3.08 pregame reference.
- Javonte Williams 20.51 simulated carries vs 15.71 observed; carry share 68.7% observed vs 65.4% simulated.
- Dallas team rush attempts 22.86 observed vs 31.35 simulated (same numbers as above; verify once).
- Seed 3397 scores 22.95 of 25 on player-workload realism. CONFLICT: the seed shortlist report
  (pushed at `33337584`, legendarypicks branch `research/slc-week8-missing-10k-2026-10-29`) lists seed 3397 at
  77.40 realism. These may be different metrics. Resolve before quoting either.
- "Several otherwise attractive seeds score under 5." Unverified.
- Gridiron tracking: 9,333 live plays, 205K player-plays, 2022 W1-5 (the reference doc says 9,333 and 205,326;
  verified in `docs/NFL-ROLE-MOVEMENT-REFERENCE-2026-11-01.md`).
- BDB replay 1.93 m error at 1.0 s vs 1.05 m constant velocity (from the Gridiron context doc; re-check the
  source numbers before quoting).

## 5. Open decisions the owner must answer before WP1 and later run

- D1. Status of 2025. The holdout record says 2025 has already been examined in prior SLC holdout reports. The
  write-up calls 2025 an "untouched 2025 holdout". Which is true? Proposed reading to confirm: 2025 is a known
  validation fold, and no untouched test exists until a new sealed period is named. Answer required.
- D2. Fit and test split. The write-up proposes fit 2022-2024 and test 2025. This depends on D1. Answer required.
- D3. Advance thresholds. No numeric thresholds exist in the write-up. The gate text says "improve", "reduce",
  "better". Proposed values must be supplied by the owner. Until then no arm can be advanced.
- D4. Which data defines "eligible players": the participation files, the SLC records, or both? Answer required.
- D5. Gate 7 scope: which matchups are the "contrasting matchups"? Answer required.

## 6. Work packages

Read-only until section 5 is answered for the package's dependencies. WP0 may start now.

WP0. Freeze baseline and definitions (gate 1). Read only.
- Inputs: the SLC reports and records named in section 3; the participation files.
- Output: one table per season and team: plays, runs, dropbacks, drives, plays per drive, player targets and
  carries, with the definition used for each column written next to it.
- Acceptance: each number in section 4 is either reproduced from a named source file (with the value and file)
  or marked not reproduced. Realism scoring is kept separate from seed selection.

WP1. Opportunity-generation ablation (gate 2). Needs D1, D2, D3.
- Arms: the current score-clock play-call model (frozen, from `slc_config.py` and `decision_layer.py`) and at
  most two alternatives fit on the fit split only. One mechanism changes per arm.
- Metrics: held-out play-call log loss; team rushes, dropbacks, drives, third and fourth down decisions, clock
  behavior, scoring; per-game bias against the held-out season.
- Matched seeds and frozen inputs for every arm.
- Acceptance: an arm advances only if the held-out decision score improves and team opportunity bias drops
  without worsening the other opportunity categories. Thresholds from D3.

WP2. Participant allocation (gate 3). Needs D1, D2, D3, D4.
- Arms: fixed shares; current Dirichlet shares (`share_distributions.py`); position-conditioned shares; a
  state-conditioned participation model.
- Eligibility must come from pregame roster and depth-chart information only. Actual held-out participation must
  not be an input (this is the write-up's own rule).
- Metrics: player-level likelihood; zero rates by position; RB carry share variance and WR target share variance
  against observed (current reference: 1.77x and 1.40x, to be re-derived in WP0); P95 and P99 of player lines.
- Acceptance: better player-level likelihood and better zero rates and variance ratios, on the test split.

WP3. Personnel and coaching decisions (gate 4). Blocked until a dated team/coach join is verified.
- Step 1 (allowed now): check whether the participation files carry personnel groups by play, and list the
  count of plays per personnel group per team-season. Report only; do not model.
- Step 2 (blocked): coach-specific policy. Do not start until the join is verified and the owner approves.
- Acceptance for step 1: a table of personnel-group counts with the source columns named.

WP4. Defensive responses (gate 5). Needs D1, D2.
- Labels are proxies only (manager decision): coverage, box count, blitzers, pass rushers, as they exist in the
  data. Do not invent named defensive calls.
- For each label: count per season, support count, and the fallback used when support is low.
- Metrics: held-out decision probabilities; resulting completion, sack, rushing efficiency, conversion, turnover
  distributions, measured separately from the decision.
- Acceptance: retain a mechanism only with out-of-sample gain.

WP5. Fatigue, then injuries (gate 6). Not started in this task. Listed so it is not forgotten.

WP6. Combined model verification (gate 7). Only after WP1 and WP2 advance something.
- Execution smoke, then paired-seed comparison across the contrasting matchups from D5.
- Checks: determinism, accounting (team totals equal the sum of player lines), opportunity counts, workloads,
  game-level scores.
- Acceptance: no default change. The work stays research-only.

## 7. Milestones and checkpoints

M1. Design note, in `docs/research/`. Must record: the decisions in sections 2 and 4 (proxies, coach deferral),
the open decisions D1 to D5 with the answers given, the interface between game state, play family, personnel,
eligible players, target or carrier, and outcome. First milestone reply: the note's path and this sentence:
"Open decisions: D1 to D5 (list which are answered)."

M2. WP0 baseline table, with the recomputed section 4 values and the mismatch list.

M3. WP1 ablation specification (arms, metrics, folds, thresholds), sent to the manager for approval before any
run. No run starts before approval.

## 8. Rules

- No caps, no hard workload limits, no injuries as a workload fix.
- 2026 stays sealed. 2026 is evaluated only where valid pregame provenance exists, and only after the owner says so.
- Held-out participation is never a model input.
- No push, no commit, and no changes to dev or main unless the manager asks.
- Every assumption must be written down and confirmed before it is used.
- Stop and report on any ambiguity. Do not fill gaps.

## 9. Deliverables

- M1 design note, M2 baseline table, M3 ablation spec, all in the LP research checkout.
- A milestone reply in the hermes2 pane after each one, with the file path and the open questions still pending.
