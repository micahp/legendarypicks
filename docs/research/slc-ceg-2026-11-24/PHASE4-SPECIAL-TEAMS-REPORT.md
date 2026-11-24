# SLC-CEG Phase 4: special teams, tries, penalties, overtime decisions, returns

Date: 2026-11-24. Pre-registration: `PHASE4-PREREGISTRATION.md` (`b56da5f8`, amended `aa3dc7d5` before any score).
Code: `scripts/nfl_sequence/ceg_special.py`. Results: `phase4/tune_2024.json`, `phase4/final_2025_2026.json`. Regular
season. Phases 2 and 3 unchanged.

## Result

1. **C beats B in 2025 on 7 components** (interval below zero): kickoff result (regime-adapted, -0.365), penalty type
   (-0.145), onside choice (-0.054), try choice (-0.037), interception return (-0.031), live foul (-0.010) and pre-snap
   foul (-0.007).
2. **No gain:** punt result (-0.016, interval reaches +0.001; in 2026 -0.039 with the interval below zero), field goal
   (+0.003, n.s.), fumble return (-0.052, n.s., 216 returns). Onside recovery and try success are B only.
3. **Kickoffs need in-season adaptation, not more history.** The touchback share fell from 0.642 (2024) to 0.207 (2025)
   with the rule change. Adapting inside 2025 gains 0.365 per kickoff. In 2026, with the regime unchanged from 2025, the
   prior season is already right and adaptation adds nothing (+0.007, n.s.).
4. **v2's overtime 4th-down rule is wrong.** On 93 overtime 4th downs (2022 to 2025), teams punted 48 times and kicked 25
   field goals; v2 kicks at 0.9 whenever it can. The Phase 2 intent model scores 0.555 against the rule's 1.014 (-0.460,
   -0.630 to -0.267).
5. **Pre-snap penalty enforcement reconciles.** For 11,338 of 11,393 pre-snap fouls (99.5%) the next snap is exactly
   the line moved by the published penalty yards, including the 1,596 in half-distance range (nflverse's penalty yards
   already apply half the distance).

## 2025 confirmation (log loss per opportunity)

| component | n | B | C | C minus B (95%) |
|---|---|---|---|---|
| K2 kickoff result (B prior regime, C regime-adapted, k 300) | 2,445 | 3.527 | 3.162 | -0.365 (-0.404 to -0.326) |
| K9 penalty type (k 3) | 3,461 | 1.733 | 1.588 | -0.145 (-0.161 to -0.131) |
| K1 onside (k 1) | 2,493 | 0.094 | 0.040 | -0.054 (-0.070 to -0.039) |
| K6 try choice (k 30) | 1,373 | 0.302 | 0.265 | -0.037 (-0.053 to -0.022) |
| K11 interception return (k 100) | 361 | 2.821 | 2.790 | -0.031 (-0.051 to -0.009) |
| K8b live foul (k 300) | 40,536 | 0.135 | 0.125 | -0.010 (-0.011 to -0.008) |
| K8a pre-snap foul (k 300) | 43,051 | 0.256 | 0.249 | -0.007 (-0.008 to -0.006) |
| K4 punt result (k 300) | 1,757 | 3.582 | 3.566 | -0.016 (-0.035 to +0.001) |
| K12 fumble return (k 1) | 216 | 0.467 | 0.415 | -0.052 (-0.109 to +0.013) |
| K5 field goal (k 300) | 1,084 | 0.422 | 0.425 | +0.003 (-0.006 to +0.011) |
| K3 onside recovery (B only) | 47 | 0.352 | | |
| K7 try success (B only) | 1,373 | 0.219 | | |

Left out and counted: 8 kickoffs and 1 punt whose result could not be read from the next snap.

## Exit check

All 99 punt spots and all field-goal distances from 18 to 75 yards get a distribution that sums to 1 over legal
outcomes only (a receiving start yardline 1 to 99, touchback, block, return touchdown, kicking-team recovery; made,
missed, blocked). 0 refusals.

**Found:** the arm C field-goal make probability is not monotone in distance at 1-yard detail: it goes up from one yard
to the next on 51% of steps. The 1-yard cells are noise on top of the 5-yard trend. A distance-monotone model (backlog
E11) should replace the 1-yard level before C is used for field goals; B (5-yard bins) is used until then.

## Selective composition for Phase 5

C where C beat B in 2025 (K1, K2 regime-adapted, K6, K8a, K8b, K9, K11, the Phase 2 intent model in overtime), B
elsewhere (K4, K5, K12, K3, K7). Blocked-kick recovery, safety free kicks and penalty enforcement use documented priors and
the rules core, not evaluated components.
