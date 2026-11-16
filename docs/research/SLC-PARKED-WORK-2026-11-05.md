# Parked work (draft)

Plan for the work that is not finished, kept here so it can be picked up later. Nothing in this PR is for merge.
Done work is pushed to slc-v2.

## Where the parked work lives now

- Non-NFL team-code interface: draft PR #33 (22 modules and tests, as they stand in commit ef9e8346). slc-v2 reverted them in
  97197558.
- Kept on slc-v2: the NFL interface code, and the shared settlement, props and team_codes code that NFL also uses, including
  settlement/ncaaf_settle.py. These still hold non-NFL code paths and need a per-league split before they can move.

## NFL, SLC v2

- Ablation (A control, B lineups, C snap counts, D kicker table): 255 of 484 batches at 02:44 UTC, 0 failed. When it
  completes: score the four arms, write up on slc-v2, log exposure row 27, push.
- 2025 realism run: armed to start after the ablation. Status and checks: docs/research/SLC-2025-REPLAY-RUN-PREP-2026-11-05.md
  on slc-v2.
- Gate scorer: not built. Metrics 1 to 13 against the extended realism draft (pi's file, not reviewed in this repo).
- Thursday JAX-BAL: deferred by decision. The pregame capture window closes 23:45 UTC on 2026-11-05, so a prospective record
  for this game is lost if it is not taken before then.

## Timestamped injury reconstruction (planned, not started)

- Why: the 2025 injury file has no timestamps, and the engine uses Out and Doubtful designations for eligibility
  (pre_event.py, through share_distributions.eligible_players). Until a time-safe source exists, replays exclude game-week
  designations (the default; --include-injury-report restores them).
- Evidence tiers:
  1. Verified before the cutoff: an archived official report, or a contemporaneous source with a trustworthy time. Only tier 1
     enters the cutoff-safe injury-aware replay.
  2. Dated but not verified: a team article from before kickoff that may have been updated later. Corroboration only, or a
     labelled exploratory analysis.
  3. Retrospective only: a final dataset with no usable time. Hindsight-only comparison, never the primary replay.
- Steps: audit 2025 official archives and team announcements; match each item to game, GSIS id, publication time and version;
  measure coverage first (games with verified reports, identities matched, Out and Doubtful exclusions recovered, starter
  changes recovered, unresolved); compare arms on identical games and seeds: injury-excluded (current), injury-aware (tier 1
  only), hindsight-only.
- Missing evidence keeps its uncertainty. Test a probabilistic availability fallback built from injury history and role,
  using no target-game outcomes. Do not treat a missing report as a healthy player.
- Tests: a post-cutoff injury change must not change a pregame run.
- Prospective 2026: capture official reports, inactives, transactions and announced starters as they appear, with original
  timestamps and hashes.
- Not verified yet: the 2025 49ers and Rams report examples cited in the review. The audit step checks them.
- The 2025 retrospective ACT roster and kicker assignments can reflect game-day information. Reconstructing injuries does not
  fix that.

## Readiness manifest

- The week 8 readiness manifest says the injury report is captured but not used. The code uses it whenever rows exist. For the
  locked CAR-GB forecast, no Out or Doubtful player is on the depth roster, so its eligibility is unchanged. The manifest
  wording needs correcting.

## Owner decisions open

1. Injury designations in replays (current default: excluded until a time-safe source exists).
2. NHL vocabulary and migration.
3. FCS and GDL registration.
4. Yahoo data source for the ESPN vs Yahoo projection comparison.
5. Per-league split of the shared settlement, props and team_codes code (needed before those parts can move).

## Fantasy projections: ESPN vs Yahoo

- Question: are ESPN and Yahoo fantasy projections the same?
- Not testable yet. The repo has no Yahoo projection data, code or credentials. ESPN weekly projections are stored
  (espn-weekly, 15,540 rows, 2025 and 2026).
- Plan once a Yahoo export or API access exists: match players and weeks, compare the stat projections, report differences and
  coverage. Use stored ESPN rows only, with no new ESPN requests. The owner does not want ESPN used for fantasy work.

## Not planned

- ESPN projections backfill for the LAR and WSH rows: needs ESPN calls and database writes.
- Esports and World Cup codes: outside the registry.
