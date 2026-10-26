# v0.2 alpha1 diagnostic artifacts — do not use as forecasts

These files are preserved to document a defect found after the 500-seed run.

The alpha1 shift-boundary gate rejected OT periods ending in goals because it
validated the terminal goal boundary and later shift-chart boundaries as if play
continued beyond the game-ending goal. A read-only scan of the 2019–2020
eligible training corpus found 440 OT templates, 290 with an OT goal (66%). The
alpha1 donor gate rejected all 290 goal-ending templates in the diagnostic
sample: 279 for lineup counts at or after the terminal-goal boundary, 10 for
overlapping intervals, and 1 for an invalid interval. As a result, every tied
generated game continued to a shootout (COL–NSH 98/98; MIN–VAN 82/82).

The alpha1 win probabilities and score distributions are invalid as matchup
forecasts. The artifacts are retained for audit only. Alpha2 truncates OT shift
eligibility and player TOI at the terminal goal and validates only the selected
period before a new evaluation run.
