# SLC-CEG team-strength candidates

The register of team-strength candidates. A failed candidate stays here, with its code and results, so it is not
built again by accident.

| candidate | definition | code | result | status |
|---|---|---|---|---|
| C | no team terms | `ceg_generator.py` | baseline | baseline |
| E6 | dropback outcome offense ratio (k 300); targeted outcome defense ratio (k 1,000) | `ceg_team.py` | Phase 6: two small per-play gains on 2025; Phase 8 H2 drive points vs C -0.060 (-0.194 to +0.072), offense r 0.04 | in the frozen week 12 forecast `ada09944` |
| E8 | E6 plus run yards and YAC hazard shifts, offense and defense, lambda 1,000, tuned per play | `ceg_gainteam.py`, generator `gain_team` | Phase 8: four per-play terms count on 2025; H2 drive points vs C -0.123 (-0.284 to +0.040), offense r 0.19 against R 0.67 | **failed research candidate** (not useful at drive level). Kept unchanged as a comparison arm |
| E9 | offense and defense strength tuned separately on 2024 drive points (chosen O10 D1000) | `ceg_phase9.py` | Phase 9: 2025 drive points vs C +0.008 (-0.168 to +0.199); offense r 0.38 (0.68 on 2024) | **failed research candidate** |
| E-R | offense shifts calibrated to cutoff-safe R (slope 2.21 points per drive per logit, 2024) | `ceg_phase9.py` | Phase 9: 2025 vs C -0.103 (-0.260 to +0.056); vs R -0.262 (beats R); offense r 0.48 | **not significant against C; best candidate**; prospective test on 2026 week 12+ drives pending |
