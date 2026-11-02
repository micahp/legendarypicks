# SLC v2 Milestones 4, 6 and 7: ablation summary, 2025 retrospective and adoption decisions, 2026-11-02

Status: research record. Development seasons 2023 and 2024 for Milestone 4. The 2025 retrospective run is Milestone 6, under the freeze in `SLC-V2-M6-FREEZE-2026-11-02.md`, and it is previously exposed. Research decisions only: no SLC default change, no simulator run, no production change, no 2026 result read. Research ADOPT is not production adoption.

## 1. Milestone 4: predictive ablation, each arm alone (development, 2023 and 2024)

Each component is evaluated alone against its frozen comparator before any combination. Intervals are game-clustered, 10,000 draws, seed 20261102. Positive means the component has lower squared error than its comparator.

| Arm | Target | Primary comparator | 2023 improvement (95% CI) | 2024 improvement (95% CI) |
|---|---|---|---|---|
| P1 pass share | team pass share per game | coach-era prior, no in-season update | +0.00066 (+0.00013 to +0.00118) | +0.00088 (+0.00031 to +0.00147) |
| P1 pass share, reference | | league prior-season mean | +0.00029 (-0.00049 to +0.00103) | +0.00110 (+0.00040 to +0.00181) |
| P1 tempo | plays per game | coach-era prior, no in-season update | +2.79 (-0.59 to +6.34) | +0.46 (-2.90 to +3.76) |
| P1 tempo, reference | | league prior-season mean | -2.67 (-6.40 to +1.11) | -3.65 (-6.76 to -0.56) |
| P1 fourth-down go rate | go rate per team-game | coach-era prior, no in-season update | -0.00071 (-0.00164 to +0.00025) | -0.00045 (-0.00156 to +0.00066) |
| P2 target share | target share per player-game | prior-only, no in-season update | +0.00039 (+0.00036 to +0.00043) | +0.00046 (+0.00041 to +0.00051) |
| P2 target share, reference | | position-group prior-season mean | +0.00116 (+0.00107 to +0.00124) | +0.00114 (+0.00106 to +0.00121) |
| P2 snap share (off_pct) | snap share per player-game | prior-only | not run: coverage 0.0000 (2023), 0.2947 (2024) | not run |
| P3 receiving WR | yards per target allowed | league prior-season rate | +0.31 (-0.09 to +0.71) | -0.23 (-0.59 to +0.11) |
| P3 receiving TE | yards per target allowed | league prior-season rate | -0.55 (-1.10 to -0.00) | +0.16 (-0.57 to +0.89) |
| P3 receiving RB | yards per target allowed | league prior-season rate | -0.73 (-1.29 to -0.20) | -0.02 (-0.76 to +0.75) |
| P3 rushing RB | yards per carry allowed | league prior-season rate | -0.01 (-0.13 to +0.11) | -0.08 (-0.19 to +0.03) |
| P3 passing QB | yards per attempt allowed | league prior-season rate | +0.07 (-0.16 to +0.30) | +0.05 (-0.21 to +0.31) |
| PBV1 sampler | package per play (log likelihood) | marginal package distribution | +0.0594 (+0.0536 to +0.0652) | +0.0667 (+0.0614 to +0.0721) |

Reading: P1 pass share and P2 target share improve on their primary comparators with intervals above zero in both seasons. P1 tempo and fourth-down go rate do not. P3 has no outcome that clears zero in both seasons. PBV1 improves on its marginal comparator in both seasons.

## 2. Milestone 6: 2025 retrospective, frozen candidates only

| Candidate | Comparator | 2025 improvement (95% CI) | Category (predeclared) |
|---|---|---|---|
| C1 P1 pass share | coach-era prior, no in-season update (identical to the team prior in 2025; see note) | +0.00121 (+0.00060 to +0.00185) | ADOPT (research) |
| C1, reference | league prior-season mean | +0.00009 (-0.00058 to +0.00073) | not a frozen comparator |
| C2 P2 target share | prior-only, no in-season update | +0.00041 (+0.00038 to +0.00045) | ADOPT (research) |
| C2, reference | position-group prior-season mean | +0.00120 (+0.00112 to +0.00128) | not a frozen comparator |
| PBV1 sampler (pre-specified) | marginal package distribution | +0.0691 (+0.0627 to +0.0752) | ADOPT (research), per the PBV1 spec |

Note: in 2025, every head coach worked for one team in 2024 (`coach_era rows where coach prior == team prior: 432 of 432`). So the coach-era comparator and the team comparator are identical in 2025. The value of the coach-era prior is therefore not tested in 2025. Its development evidence is mixed (its sign against the team prior flips between 2023 and 2024), so the coach-era prior is not claimed as a benefit.

Frozen code hashes and the run rules are in `SLC-V2-M6-FREEZE-2026-11-02.md`. Both candidates were run once with the frozen code. No threshold changed after the 2025 result.

## 3. Milestone 7: adoption decisions

| Component | Decision | Basis |
|---|---|---|
| PBV1 package sampler | ADOPT (research) | Passes the pre-registered rule on both development folds, and beats the marginal distribution on the retrospective fold. |
| P1 team pass share (C1) | ADOPT (research) | Positive in development (both seasons, coach-era comparator) and in 2025 (frozen comparator). Limit: the coach-era prior's own value is untested in 2025, and mixed in development. |
| P2 target share (C2) | ADOPT (research) | Positive in development (both seasons) and in 2025 (frozen comparator). |
| P2 depth-chart adapter (ruling B) | ADOPT as a data loader (research) | Temporal, identity, duplicate and staleness rules tested (25 passing), and every 2025 state is at or before its cutoff. Not a model. |
| P1 tempo | REJECT (not carried to 2025) | Worse than the league baseline in 2024 with an interval below zero, and no gain over the coach-era prior in either season. |
| P1 fourth-down go rate | REJECT (not carried to 2025) | No gain over the coach-era prior in either season; both intervals include zero, with negative point estimates. |
| P2 snap share (off_pct) | INCONCLUSIVE (not evaluable) | Coverage 0.0000 in 2023 and 0.2947 in 2024 in the published logs, below the 0.95 requirement. The 2025 coverage is near complete, but there is no development result to freeze against. |
| P3 defensive matchup | REJECT | No outcome beats the league baseline in both development seasons with an interval above zero. Receiving TE and RB are significantly worse in 2023. |

Decision count: 3 ADOPT (research) components, 1 ADOPT (data loader), 2 REJECT, 1 INCONCLUSIVE, and PBV1 counted with the ADOPTs.

## 4. What the decisions do not mean

- Research ADOPT is not production adoption. Production adoption requires an independent final evaluation (the strategy document, Phase G), and no production change was made.
- The 2025 fold is previously exposed. The 2025 results are retrospective, not an untouched test.
- The components are not combined. Combination (P5) is a Milestone 5 question, and it is not done.
- The 10-hour availability lag for play-by-play and the weekly logs is an assumption, recorded in every manifest.
