# NCAAF model integrity: handoff (2026-10-20)

Branch: `fix/ncaaf-model-integrity-2026-10-20`, forked from pushed `feat/ncaaf-model-page-2026-10-20` @ `651810a2`. **Not merged to dev or production.** This is a source review + implementation pass, **not a validated live run**: the development server / parquet files are not available in this environment.

## Changes already committed

1. `backend/fbs_model_runner.py`: prospective matches no longer inherit arbitrary historical-row conference labels, season metadata or kickoff properties from `events.iloc[-1]`. Resolve each team's conference from verified, same-season FBS-vs-FBS historical participants; omit unresolved fixtures instead of mislabeling them; fail closed if no verified FBS-FBS slate remains. Preserve real kickoff timestamp from ESPN throughout model prediction to store instead of manufacturing midnight UTC. The runner records the number of skipped teams in log messages.
2. `components/Leagues/FbsModelTab.tsx`: remove unsupported `Fair spread hint` (probability times 28 is not a score model); official Record list excludes late forecasts and rows with no valid pregame lock; show saved G2h ratings on a dedicated Ratings view.
3. Frontend and backend focused regression tests added for the above.

## BEFORE MERGE: run and validate

- Run `pytest backend/test_fbs_model_integrity.py` in repository environment and the existing FBS model tests. Fix any failures without weakening the assertions.
- Run FbsModelTab Jest suite (and NHL/NFL/Tennis suites). Confirm TypeScript build and mobile/desktop visual QA.
- Run `python backend/fbs_model_runner.py --parity` on the **correct frozen research ledger**. This must be a zero-row-diff gate on matched games before historical Brier numbers are attributed to the production model. Known inherited discrepancy: C2/G2h 28/2,397 rows differ at >1e-6, from drive-feature rebuild on 50 games. Do not declare parity just because aggregate Brier happens to be close.
- Run a dry-run slate for actual week 8/9 FBS-vs-FBS fixtures; confirm `kickoff_utc` matches ESPN's real ISO kickoff, that every included team has **correct current-season conference**, that neutral-site games stay neutral, and that the runner doesn't silently omit valid 2026 FBS teams simply because those teams had no FBS-FBS game so far. **Improvement required:** preferably use historical-season FBS membership from the archived schedules/team-info instead of inferring membership solely from prior completed FBS-FBS matchups. Treat this current patch as a fail-closed correction, not complete coverage.
- Verify all 3 models on cross-conference matchups after making that improvement.
- Check and migrate pre-existing records saved with a midnight UTC kickoff. They may already have incorrect `late` flags, lock eligibility and grades. **Do not rewrite historical predictions or convert late into legitimate locks.** If timestamp provenance is not provable, quarantine or label the rows rather than count them as official.
- Run `git diff --check` and compare with base branch. Do not push/merge a runtime-unverified feature straight into dev.

## Remaining backend work (not implemented here)

**P0** Model G2h has an additional unvalidated pregame-as-of concern: features are generated from the latest ratings table (not necessarily verified as-of each future fixture); confirm there are no post-cutoff results in team or conference features. The `g2_for_slate` method replays the archive and the `service.fit` call uses a time cutoff; verify both are strictly before each fixture.

**P0** The runner's `--run` path does not enforce the documented parity gate. Require a saved reproducible parity certification for its model/data version before locking, rather than silently adopting research scores. Add explicit coverage monitoring for skipped FBS teams, missing PBP and schedule failures.

**P0** The schema's `PRIMARY KEY(game_id,model)` currently stores the *first* forecast as a lock, potentially 10 days before kickoff. Separate renewable previews from an immutable T-90 (or other preregistered) pregame lock, with an operational lock runner and missed-lock accounting. Model-version metadata alone does not permit updating under the present key. Follow NHL, not the NFL picks rules.

**P1** Grading is from completed archive rows only. Ensure a schedule final-status check (rather than assumed score availability), update source snapshots, display freshness and score verification. The API needs clearer preview/locked/late/missed status and per-model freeze timestamps.

**P1** Fix team-rating `games_used`: presently counts every 2026 matchup in the dataframe regardless of outcome. Count completed games as of the rating cutoff, not future scheduled rows. Investigate stale `drop_duplicates(team_id)` mapping that can retain an old conference/name.

**P1** Frontend still hardcodes season 2026 and has no week selector, explicit previews, missed locks, team logos, or comparison to actual no-vig moneylines. Add these only with valid backend evidence. Keep bets/picks disabled while market snapshots and validated spread/total predictions do not exist.

## Acceptance criteria

1. All displayed upcoming matchups have the correct full UTC kickoff, verified team identity, current conference and source timestamps. No unknown FCS matchup silently becomes an FBS game.
2. G2 exact research parity; C2 and G2h either exact on the pre-registered population or transparently marked not production-equivalent, with numerical diff and per-row investigation.
3. Only immutable forecasts created **before actual kickoff** count toward official Record/Brier. Late/backfilled games are never represented as winning historical picks.
4. No arbitrary score/spread estimates. Show only adopted winner probabilities, actual model fair prices and verifiable grades.
5. Full test suite and live/browser visual QA passed before merging into `dev`. Do not push `dev` until these requirements are satisfied.

This branch was created and written through the GitHub connector, so the changed files are committed remotely. No local service, test runner or cloudflared tunnel was accessed.
