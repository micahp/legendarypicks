# ARI–DAL player workload tail audit

## Result

The immutable ARI–DAL run contains 10,000 unique seed outcomes and reconciled box scores: 9,479 regulation completions, 515 overtime completions, and 6 blocked games. The completed-game denominator is 9,994; 11 final overtime ties are included. The audit verified the source artifact checksums and the pinned 2025 PBP source hash. It did not modify the run.

The strongest findings are excessive team rushing volume for Dallas, highly concentrated game-level player shares, too many Jacoby Brissett rushing opportunities and yards, and a pre-fix player-eligibility defect that assigned thousands of carries to backup quarterbacks.

## Player distribution comparison

Actual figures are the `target_2026_w1_7` window in the pinned [workload-reference v3](../player-workload-reference-2026-10-30-v3/REVIEW.md). Player samples are seven games except Bam Knight (four). SLC figures use all 9,994 completed simulations. These actual windows are small pregame benchmarks, not independent holdouts.

| Player / metric | Actual mean | SLC mean | Actual P95 | SLC P95 | Actual max | SLC max | SLC tail finding |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Javonte Williams carries | 15.71 | 20.51 | 23.2 | 33 | 25 | 54 | 11 games with 46+; record 45 |
| Javonte Williams rushing yards | 67.43 | 84.39 | 137.9 | 165 | 155 | 300 | 1 game above record 296 |
| Michael Wilson targets | 9.43 | 13.57 | 15.8 | 22 | 17 | 36 | 15 games with 29+; record 28 |
| Michael Wilson receptions | 5.29 | 8.50 | 9.8 | 14 | 11 | 23 | 7 games with 22+; record 21 |
| Michael Wilson receiving yards | 53.57 | 96.70 | 93.2 | 176 | 95 | 303 | Opportunity and yards per target both elevated |
| George Pickens targets | 8.29 | 8.52 | 12.4 | 16 | 13 | 32 | 2 games with 29+; record 28 |
| Jacoby Brissett rush attempts | 3.71 | 5.14 | 6.7 | 10 | 7 | 19 | +38% in attempts vs. 2026 W1–7 |
| Jacoby Brissett rushing yards | 11.43 | 27.51 | 18.7 | 65 | 19 | 147 | 1,387 games with 50+ yards (13.88%) |
| Bam Knight carries | 6.25 | 12.11 | 13.8 | 26 | 15 | 42 | 207 games with 30+; four-game actual sample |

Every seed meeting those thresholds is listed in [`summary.json`](summary.json); the row-level lines, scores, team volumes, reconstructed shares, and fallback counters are in [`per_seed_player_tail_findings.csv`](per_seed_player_tail_findings.csv). The full backup-QB participation ledger is in [`backup_qb_participation.csv`](backup_qb_participation.csv).

## Exact maximum cases

Scores below are DAL–ARI. Team plays, dropbacks, and rush attempts are for the named player's offense.

| Seed | Player outcome | Score | Team plays / dropbacks / rushes | Credited player line | Prior share → reconstructed game share |
| ---: | --- | ---: | ---: | --- | --- |
| 8502 | Javonte Williams, 54 carries | 52–17 | 88 / 26 / 62 | 54 carries, 295 yards, 5 TD; 4 targets, 3 catches, 63 yards | 2025 carry share 56.1%; draw 70.0%, 95.3% within RBs; realized 87.1% of team carries |
| 8404 | Javonte Williams, 300 rushing yards | 44–24 | 86 / 32 / 54 | 46 carries, 300 yards, 2 TD; 3 targets, 2 catches, 19 yards | 2025 carry share 56.1%; draw 97.9% within RBs; realized 85.2% of team carries |
| 5428 | Michael Wilson, 36 targets | 30–26 | 88 / 58 / 30 | 36 targets, 23 catches, 234 yards, 2 TD | 2025 target share 20.5%; draw 96.5% within WRs; realized 62.1% of team targets |
| 3206 | Michael Wilson, 23 receptions | 16–31 | 92 / 50 / 42 | 29 targets, 23 catches, 218 yards | 2025 target share 20.5%; draw 97.8% within WRs; realized 60.4% of team targets |
| 8629 | George Pickens, 32 targets | 37–35 | 80 / 55 / 24 | 32 targets, 21 catches, 223 yards, 1 TD | 2025 target share 22.6%; draw 75.8% within WRs; realized 58.2% of team targets |
| 3741 | Jacoby Brissett, 147 rushing yards | 23–41 | 60 / 21 / 38 | 10 carries, 147 yards, 2 TD; 20 attempts, 14 completions, 134 passing yards | 2025 QB carry share 9.9%; draw 97.0% within QBs; realized 26.3% of team carries |
| 7893 | Bam Knight, 42 carries | 24–7 | 89 / 33 / 56 | 42 carries, 188 yards, 1 TD; 5 targets, 5 catches, 50 yards | 2025 carry share 22.8%; draw 83.6% within RBs; realized 75.0% of team carries |

The per-seed archive contains aggregate player box scores and playcall counters, but no ordered participant-selection trace. The game-level share draws are reproducibly reconstructed from the frozen snapshot hash, seed, team, role, and 2025 PBP counts; individual play assignments cannot be recovered from these artifacts. No play-by-play replay is claimed here.

## Root-cause decomposition

The team comparison uses the same 2026 W1–7 cutoff as the player reference. SLC values are from the published ARI–DAL results.

| Team | Measure | Actual W1–7 | SLC | Difference |
| --- | --- | ---: | ---: | ---: |
| ARI | Plays | 68.43 | 64.03 | −6.4% |
| ARI | Pass attempts | 40.43 | 33.94 | −16.0% |
| ARI | Rush attempts | 25.86 | 29.09 | +12.5% |
| DAL | Plays | 62.86 | 67.72 | +7.7% |
| DAL | Pass attempts | 39.00 | 35.85 | −8.1% |
| DAL | Rush attempts | 22.86 | 31.35 | +37.1% |

- **Javonte Williams mean carries:** SLC carries imply a 65.4% team share; his observed 2026 share is 68.7%. Replacing only SLC team carries with DAL's observed 22.86 gives 14.95 carries. Replacing only the SLC share with the observed share gives 21.55. The mean excess is driven by Dallas's run volume; player-share dispersion explains the extreme single-game tails, not the mean overage.
- **Michael Wilson targets:** SLC's 13.57 targets on 33.94 ARI attempts imply a 40.0% share; the pregame reference is 9.43 on 40.43 attempts, or 23.3%. Fixing only team pass volume while keeping SLC's share gives 16.16 targets; fixing only Wilson's share gives 7.92. Both the underpredicted team pass volume and overallocated player share must be corrected. SLC receiving yards per target are 7.13 versus 5.68 actual, adding a separate outcome-efficiency excess.
- **Jacoby Brissett:** SLC implies 17.7% of ARI carries versus 14.4% observed. Fixing only team carry volume gives 4.57 attempts; fixing only his share gives 4.18, versus 5.14 simulated and 3.71 actual. SLC yards per carry are 5.35 versus 3.08 actual. Seed 3741 reached 147 yards on 10 carries (14.7 yards per carry), so this tail combines opportunity and player-conditioned run efficiency.
- **Other player-share tails:** In maximum cases, the reconstructed within-position game shares reach 95.3% for Williams, 96.5% for Wilson, and 75.8% for Pickens. None of these named players used the 1% prior-share floor. The share model is therefore concentrating existing player support in particular games, rather than creating these examples through a no-history floor fallback. The separate chronological holdout found predicted share variance of 1.51–1.74× observed for RB carries and 1.37–1.46× for WR targets; the pooled candidate still had 1.77× and 1.40× variance, respectively.

The audited run uses the 2025-fit Dirichlet share model (`dirichlet-multinomial-mle-v2`; fitted concentration φ=8.366 for carries and φ=24.831 for targets). The later position-conditioned holdout shows that this global fit still leaves too much game-level variation in RB and WR shares.

## Eligibility and metadata defects in this archived run

All 360,000 exported player rows say `starter: false`, including both QB1s. The same audit found 10,440 carries assigned to three depth-chart backup quarterbacks across 4,762 backup-QB player-games, without an in-game replacement event. They were incorrectly admitted to the ordinary carry pool. There were also 351 backup-QB targets through the producer's low-rate trick-target branch.

These are defects in the archived producer output, not legitimate workloads to calibrate around. The corrections are present in the source used by the current six-matchup run: commit `8b7d5a2e` descends from `2a1022a5`, which restricts ordinary QB carries to the available QB1 and derives QB1 starter metadata from depth-chart rank and availability. Focused tests for backup-QB run/target eligibility and starter metadata pass. Verify these fixes again against the finished six-matchup artifacts.

## Recommended order

1. Keep QB1-only ordinary run eligibility and correct starter metadata as hard gates; confirm with the current run's final ledgers and box scores.
2. Correct team-level run/pass opportunity generation, especially DAL's +37% rush-attempt gap. This explains more of Williams's average carries than his mean share does.
3. Refit role-conditioned player shares and dispersion. The current game-level draws create severe within-position concentrations despite ordinary prior shares.
4. Fit QB-run decisions to the named QB's role and separate rushing opportunity from yards per carry. Brissett's attempts and efficiency both exceed his seven-game pregame reference.
5. Evaluate player-conditioned receiving and rushing outcomes after opportunity and share effects are fixed. Do not hard-cap legal rare outcomes.

SLC defaults and the source 10K remain unchanged. A same-seed full-stack ablation is still required before adopting calibration changes.

## Provenance and limitations

- Source run: ARI–DAL, 10,000 seeds, producer commit `52c59c10`, cutoff `2026-10-29T00:02:21Z`.
- The audit verified every input artifact listed by the run's `SHA256SUMS.txt` and matched `pbp_2025.csv.gz` to the pinned workload-reference manifest.
- The producer recorded SQLite SHA256 `feb5179f1c6c2f8cd2265a25ff68f3552d6e68bbba00354e0688f22505aa028f`; the SQLite file was not available for an independent byte-for-byte check during this audit. The share draws were reconstructed from the hash-pinned published PBP source.
- Actual 2026 comparison windows are only seven games (four for Bam Knight) and are pregame reference evidence, not holdout calibration.
- Exact per-play participant decisions were not archived; a frozen-input replay with decision-level instrumentation is needed to attribute every play in an extreme game.
