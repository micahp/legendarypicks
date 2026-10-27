# Dallas–Philadelphia 10,000-Run Ledger

**Game:** Dallas Cowboys at Philadelphia Eagles (`2026_07_DAL_PHI`)  
**Scheduled kickoff:** 2026-10-27 00:15 UTC  
**Report date:** 2026-10-26 (America/Chicago)

## Scope

Three complete 10,000-seed batches are available: the original unconditional S0 run, the first contextual S1 run with offense and defense conditioning, and the later integrated S1 rerun with blocked-kick and overtime support. A separate serial attempt on the corrected code stopped at seed 1,000; it did not produce a 10,000-run result.

Score and win summaries use only complete, untied games that passed that run's validity gate. They are therefore conditional on simulator coverage. For the integrated S1 run, the manifest verifies 10,000 unique seed rows, but the archived JSON artifacts do not include a per-seed outcome ledger.

## Results at a glance

| Run | Model and code | Valid games | Blocked outcomes | Errors | Valid-game mean: PHI / DAL | Mean total | PHI win rate |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| S0 | Unconditional historical play pool; dirty producer based on `90c74641` | 7,993 (79.93%) | 1,948 | 59 | 20.4146 / 20.4886 | 40.9032 | 49.87% |
| S1 | Context mode `both`; clean producer `15e5eb20` | 8,825 (88.25%) | 1,175 | 0 | 19.8774 / 20.5467 | 40.4241 | 48.56% |
| S1 integrated | Context mode `both`; clean producer `709fb759` with integrated blocked-kick and overtime rules | 9,820 (98.20%) | 173 | 1 | 19.9695 / 20.8081 | 40.7776 | 47.54% |

The first S1 produced 832 more valid games than S0, an 8.32 percentage-point coverage increase. The integrated S1 produced 995 more valid games than the first S1, a 9.95 percentage-point increase. Neither is an isolated estimate of contextual conditioning or a single rules fix: producer revisions, special-teams references, and snapshot/reference digests changed. The batches are not paired ablations, even though they use seeds 1–10,000.

## S0: unconditional baseline batch

S0 sampled from the historical play pool without matchup conditioning. Its original detailed report is [Dallas–Philadelphia: 10,000-game statistical batch](nfl-dal-phi-statistical-batch-2026-10-26.md).

Among its 7,993 valid games, mean points were PHI 20.4146 and DAL 20.4886; mean total was 40.9032 and mean PHI-minus-DAL margin was −0.0739. Dallas won 4,007 valid games and Philadelphia won 3,986. The score intervals were 10–32 points for each team and 27–56 combined points at the 10th–90th percentiles.

Coverage accounting: 7,993 complete, untied games; 334 regulation ties requiring overtime; 1,614 games blocked before the end of regulation; and 59 retained simulation errors. The errors were chiefly out-of-bounds return/recovery endpoints and offensive-touchdown reconciliation failures. The detailed S0 report lists the guarded transitions and error counts.

**Provenance:** seeds 1–10,000, run as six non-overlapping shards; source base commit `90c74641effc24986eec8dbb55170b10242ac0b5`; producer worktree dirty. The runner file used for the run is separately pinned in the S0 report. Result SHA-256: `327aff0095f46eb90c8f977411fbb7838a5a927efcf5eb9494f45b833f963538`. S0 manifest SHA-256: `8911873d8605e25f40de05c724da2b0878589548aaefa70e8f09e746246b1f4e`.

## S1: contextual offense-and-defense batch

S1 used the `both` context mode: an opponent-adjusted, cutoff-filtered Gaussian-kernel pool conditioned on team offense and defense ratings. The bandwidth was 1.0 source-rating standard deviations, the minimum effective source-game threshold was 10, and same-week games were excluded. The eligible historical play pool contained 137,373 plays. S1 also used the observed 2022–2025 safety free-kick table.

Among its 8,825 valid games, mean points were PHI 19.8774 and DAL 20.5467; mean total was 40.4241 and mean PHI-minus-DAL margin was −0.6693. Dallas won 4,540 valid games (51.44%) and Philadelphia won 4,285 (48.56%). The 10th–90th percentile ranges were PHI 9–31, DAL 10–32, and 26–55 combined points. The most frequent valid exact score was DAL 20, PHI 17, occurring 56 times (0.63%).

Of all 10,000 attempts, 8,825 were valid complete, untied games; 369 ended regulation tied and were blocked pending overtime; 806 were blocked before regulation ended; and zero were simulation or validation errors. The two blocked categories total 1,175. This run included the observed safety free-kick table, but predates the later blocked-kick classification and overtime-drive implementation.

The S1 run's recorded v1 reference projected PHI 23.1840 and DAL 23.1421 points, with a 46.3261 total. It was reconstructed from 93 prior games. The run manifest classifies it as `exploratory_reconstructed_fit`, not an authentic immutable v1 projection locked at the same information cutoff. It must not be presented as a fair predictive-accuracy comparison. No actual game result was attached to the batch.

**Provenance:** run ID `dal-phi-s1-context-both-safety-2026-10-26`; seeds 1–10,000, six shards; branch `research/nfl-contextual-simulation-agent2-2026-10-26`; clean producer commit `15e5eb20ba5679a6770085fa7f1a1b0570a97911`. Pregame cutoff `2026-10-26T17:21:52Z`; scheduled kickoff `2026-10-27T00:15:00Z`. The source snapshot SHA-256 is `d5c106ad5db47a01e809f7999cc4b130fcc8569ebc5395ac24ad8ef039873db1`; the resealed run snapshot SHA-256 is `c2cfa67452cea59b85b0da64ca4facfea1913d0c0ee89fd7d74a92e8bcd6fb1e`; observed-reference SHA-256 is `9b6c6e35fe800fdc3fa35f2dc41426a9a89b2925fb55f455a50878471ceb70e4`; contextual-pool SHA-256 is `0c1f720b2c128ee56c21c494c1d8d0dac7aedc7e870707e4af8bd1f05105f962`.

The completed S1 result is retained on the faster host at `/root/nfl-dal-phi-s1-contextual-2026-10-26/results-s1.json` (SHA-256 `496dd36da2f2f070fc4d2edd6d7caa0919164aa1c2d8a7976192c2d12bfa8db5`). Its input manifest is `manifest-s1.json` (SHA-256 `cea4142c6faf06803802459d239c262b5ec701bba593e8a08e46ca23a6653cce`); `run-manifest.json` (SHA-256 `05935c89116addb023cfecd2700454e0efbe22ab768baffc0047bdd84bd6906a`) records the six shard checksums and verifies exact, unique seed coverage.

## S1 integrated: corrected rules-engine rerun

The integrated S1 result completed all seeds 1–10,000. Of these, 9,820 were valid complete, untied games (98.20%); 9,449 completed in regulation, 377 completed in overtime, 173 were blocked, and one ended in a simulation or validation error. The valid-game means were PHI 19.9695 and DAL 20.8081, with a 40.7776 mean total and a 47.54% PHI win rate. DAL won 5,152 valid games (52.46%). The full report, including guarded-transition counts and provenance limitations, is [Dallas–Philadelphia S1 integrated 10,000-run report](nfl-dal-phi-s1-integrated-10k-2026-10-27.md).

The input cutoff was 2026-10-26 22:45:01.400 UTC, before the 2026-10-27 00:15 UTC scheduled kickoff, but the merged batch output was frozen at 03:04:50.891 UTC, after kickoff. This run was not available as a pre-kickoff forecast. Its v1 reference is also marked `exploratory_schedule_unverified`; it is not a fair accuracy comparison.

**Provenance:** branch `research/nfl-contextual-batch-run-2026-10-26`, clean producer commit `709fb75959c16adc74baf42e986d4fb85974e0cc`; run manifest SHA-256 `20963de4e8be84e4adc95e985f2fe6a3f0d39b4bd9d0a9a6d5e96e82e8248e4d`; merged result SHA-256 `a8772289b9d1378ae5ca7fde79decdc6e8ca9bff561db691fd9a42f07fea8efa`. The six shard outputs and merged result remain on the faster host under `/root/nfl-dal-phi-s1-integrated-2026-10-26/`.

## Comparison limits

- The 8.32-point coverage increase from S0 to S1 is descriptive. It cannot be attributed to the context kernel alone because code, reference inputs, and run digests differ.
- Valid-game score and win summaries omit blocked runs. Coverage losses can bias each distribution; preserve blocked outcomes when evaluating model quality.
- An identical integer seed does not establish common random numbers when the reference or snapshot digest changes. Treat S0-versus-S1 differences as independent Monte Carlo results.
- All three runs are research simulations. More seeded games reduce Monte Carlo noise; they do not establish calibration or better real-world prediction.
- The roster snapshot used for these runs had 18 Dallas and 23 Philadelphia skill-position rows, without jersey numbers or starter flags. Player totals are role allocations, not player-specific forecasts.
