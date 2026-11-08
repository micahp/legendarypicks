# Paired workload experiment: ARI–SEA, 2026-11-08

**Exploratory research; not a production default or a forecast-skill claim.** One frozen week 9 matchup, 100 matched seeds per arm. The snapshot was made at 4:16 p.m. Central on November 7, not at the official game-day inactive cutoff. Its roster eligibility is unknown. The frozen workload extract was acquired later and its original acquisition times and historical position mapping are unverified. Do not infer that a player was inactive from zero recorded touches.

The simulator code was commit `1c1afaa0`. The research branch includes `slc-v2` through `a19b7d7c`. All arms used the same snapshot, full-stack play-calling configuration, participation-field lineup model, five ordinary blocker fixes and RNG-v2 control root; none used full season adaptation. The field used prior-season group and substitution fits; no current-season snap-count update was supplied. Modeled snaps cover the starting QB and skill-lineup appearances, not a complete 22-player or special-teams snap ledger.

| Arm | Share means | Concentration | Valid and reconciled | Overtime |
|---|---|---|---:|---:|
| C | Previous season | Existing C fits | 100/100 | 3 |
| D1 | Prior/current blend, weight 4/(4+earlier games) | Existing C fits | 100/100 | 3 |
| D2 | Same adaptive means as D1 | Fitted D values for available groups; C values for other groups | 100/100 | 4 |

The earlier three-seed smoke at `5496f046` passed in all arms. The final 100-seed run included a later manifest correction: D2's reported concentrations now match its actual fitted values. The pairing gate checked the control header, pregame and non-workload inputs, and all other layer hashes before binding D1 and D2 to the control root. The report generator independently checked the same binding and all **300 per-seed stream manifests**. All 100 seed IDs were present in each arm; no seeds were excluded. The common root was `a7234c44d4c24de609f136c541a96a7b7c587bae34fea7006413916275f02c1f`. Matching roots establish the named stream identity, not identical realized plays after the interventions.

## Player workloads

Numbers are simulated opportunities per game: mean; median; central 80% simulation interval (10th–90th percentiles). They are simulation distributions, not confidence intervals. Observed values are from the frozen database extract for **weeks 1–8**, divided by eight team-games, and are context rather than this game's actual results.

| Player / metric | C | D1 | D2 | Observed weeks 1–8 |
|---|---|---|---|---|
| Michael Wilson targets | 16.71; 16; 10.9–23.1 | 14.64; 14; 10–19 | 14.98; 14; 9.9–21 | 81 targets, 10.125/team-game; 25.9% of team targets |
| Michael Wilson modeled snaps | 57.44; 58; 47–67 | 57.15; 57; 47–67.1 | 57.64; 58; 47–67 | Not evaluated here |
| Zach Charbonnet carries | 15.67; 15; 8–24 | 15.51; 15; 7–23 | 15.52; 15; 7–23 | 6 carries, 0.75/team-game; 2.7% of team carries |
| Zach Charbonnet modeled snaps | 40.44; 40; 29–53 | 40.82; 40; 29.9–53.1 | 40.33; 39.5; 29.9–54 | Not evaluated here |

Wilson's mean simulated target share changed from 44.4% (C) to 39.2% (D1) and 39.7% (D2). Charbonnet's mean simulated carry share was 52.2%, 52.1% and 51.3%. D1 moved Wilson toward his prior observed team share, but he remained above it; Charbonnet barely moved. The observed team-game denominator does not establish how many games either player was eligible to play.

For paired seed differences, D1 minus C averaged **−2.07 Wilson targets** (median −1; central 80% −6 to 0) and **−0.16 Charbonnet carries** (median 0; −1.1 to 2). D2 minus D1 averaged **+0.34 Wilson targets** (median 0; −2.1 to 3) and **+0.01 Charbonnet carries** (median 0; −1 to 1). These are descriptive differences across the 100 paired simulation seeds, not confidence intervals or evidence of real-world predictive improvement.

## What the selection trace shows

These counts cover instrumented Dirichlet pre-event selections, not necessarily realized targets or carries; a later play outcome can change whether an opportunity is recorded. For ARI receiving selections, the WR position set was chosen on 2,073/3,858 traced decisions in C, 2,055/3,841 in D1, and 2,060/3,864 in D2. For SEA carries, the RB-only set was chosen on 2,309/2,925, 2,278/2,880 and 2,327/2,931 respectively. Other position sets are retained in the JSON; this is the simulated chooser, not an observed group-frequency substitution.

For Wilson, the mean game-level pre-lineup weight when represented in the selected population was 0.791 in C, 0.602 in D1 and 0.641 in D2. His mean normalized post-lineup candidate weight when eligible was 0.927, 0.837 and 0.853. He was a candidate on 1,834 / 1,805 / 1,817 traced receiving selections and chosen on 1,707 / 1,500 / 1,539.

For Charbonnet, mean pre-lineup carry weight changed from 0.822 to 0.181 and 0.164, but his mean normalized weight when he was a candidate remained 0.999 / 0.986 / 0.986. He was the **only candidate** on 1,512 of 1,568 C selections where he was a candidate, 1,516 of 1,570 D1 selections, and 1,520 of 1,574 D2 selections. Thus the trace supports lineup filtering as a strong constraint on this particular workload; it does not establish that the lineup model or roster is realistic.

## Provenance and limits

- Source snapshot file SHA-256: `cc44c5e0f0e3216a6785d2b79af65174a27b95133e8600da07d412237338e475`. The snapshot's sealed identity and all layer identities are in [results.json](results.json).
- Play-call artifact SHA-256: `c8f16540931f6fddc61b6e62797ecd71dfff11897c393c531033eef623328ce5`; streak file: `50490140dac78836c135226096b9101fc4f1a44e22837aba04174d921a065c78`; lineup field: `9aaf7e57ce45bc525393de105c2b803673d441b589588a279a28e57ce2880a41`.
- Frozen workload extract SHA-256: `cec16cb2462ef71eaf0fc5d300ce6729e57c915b114dd8615f8e7d924986a618`; D2 concentration file: `030856e02f58f100a91791014de937464465d751876ac6eb51390f86d72316d1`. The C and D1 RB-carry / WR-target concentrations were 3.072557 / 8.222426; D2 used 1.412538 / 3.527768. D2's QB carry fit hit its lower grid boundary. The offline fit reserves 2% mass for unseen players, while the simulator draws over its eligible roster without a separate OTHER category, so the fitted concentrations are experimental and have not been validated as live-selection calibration.
- [results.json](results.json) contains per-player means, medians, central 80% intervals, paired deltas, modeled shares and snaps, observed prior-week counts, selection-group counts, source identities, eligibility values, and ledger hashes. [focused-traces.jsonl.gz](focused-traces.jsonl.gz) contains 15,821 Wilson/Charbonnet-related selection records, including population and candidate weights; SHA-256 `a99bc89951e5aeca443f0c75b5a73bfd29d13a064a64a8a0dddc6f4d336ac385`.
- Raw batches, ledgers, box scores, logs and failure directories remain on the fast host at `/root/ot-sim-out/slc-workload-d-ari-sea-1c1afaa0-100/`. The source application database was opened read-only but was not frozen or fully hashed; its reference data and other layer hashes are recorded in each ledger. The separate 244-versus-242 position-breakdown population discrepancy remains unresolved as documented in the frozen-evaluation report.
- Fallbacks remain frequent (57,438 control events over 100 games); multiple events can occur per play. This one matchup and its 100 seeds do not establish league-wide performance or uncertainty calibration. No additional matchup has been run for this intervention.
