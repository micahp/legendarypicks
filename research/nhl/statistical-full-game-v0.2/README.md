# NHL statistical full-game v0.2 alpha2

Research-only matchup sampler layered over the frozen v0.1 source audit. It uses the verified 2019–2020 PBP and shift archives, a read-only as-of roster snapshot, prior player/goalie rates, and the frozen pregame B3 Elo goal model. Generated event and shift records are written under `examples/`; raw archives and databases stay outside Git.

## Run a frozen slate

```bash
python research/nhl/statistical-full-game-v0.2/run_slate.py \
  --slate research/nhl/statistical-full-game-v0.2/examples/tonight-slate-2026-10-25.json \
  --out-dir research/nhl/statistical-full-game-v0.2/examples/tonight-2026-10-25-alpha2 \
  --simulations 500 --base-seed 31415 --verify-reproducibility
```

The runner loads the verified training corpus once, then reuses it for each matchup. `--verify-reproducibility` regenerates the first full record from its frozen input and seed and checks exact JSON equality. Every generated game runs score, SOG, player, goalie, clock, lineup, and shift-ledger accounting validation.

Run the independent artifact audit after generation:

```bash
python3 research/nhl/statistical-full-game-v0.2/audit_distribution.py \
  research/nhl/statistical-full-game-v0.2/examples/tonight-2026-10-25-alpha2/COL-NSH-20261025-v0.2-alpha2.json \
  research/nhl/statistical-full-game-v0.2/examples/tonight-2026-10-25-alpha2/MIN-VAN-20261025-v0.2-alpha2.json
```

The audit uses only Python's standard library and independently recomputes the archived example
game's clock/state progression, score, shot attempts, SOG, player attribution, goalie accounting,
eligible identities, and TOI-to-shift-ledger reconciliation. Each of the 500 generated games is
also validated during simulation; only the first game record per matchup is retained in each
distribution artifact.

## Current model boundary

- Pregame team goal means come from the frozen Elo model. Expected SOG combines prior-season skater rates with prior goalie shots-against rates.
- Eligible current-roster players are sampled by role and prior usage. Shooter, faceoff, penalty, hit, assist, and goalie participation are sampled from prior evidence with shrinkage.
- Verified donor shift intervals are remapped to the target roster. Donor-derived goalie changes appear as explicit personnel events.
- Shift eligibility is component-scoped to the selected source period. OT-winning periods stop at the terminal goal for shift TOI and personnel validation; if the exact goal second falls on the source shift interval boundary, the preceding second's lineup is used and the adjustment is recorded on the event.
- Regulation 5v5 shot attempts receive sampled miss/block/on-target results and shot-conditioned goals. Other strength states retain verified training-template outcomes.
- Event clocks, non-shot events, special-team transitions, and much of the period chronology still come from historical templates. Score-state tactics and goalie pulls are not regenerated from the simulated score.
- Team IDs are meaningful in this alpha, but the output is not an independently evaluated prediction model or a physical hockey simulation.

The full implementation specification is in [`NHL-FULL-GAME-SIMULATION-TEAM-PLAYER-GOALIE-SHIFT-MODELS-2026-10-25.md`](../../../docs/research/NHL-FULL-GAME-SIMULATION-TEAM-PLAYER-GOALIE-SHIFT-MODELS-2026-10-25.md). Results and the development-data limitations are in the dated implementation report in `docs/research/`.

The alpha1 slate artifacts are retained under `examples/diagnostics/` and marked invalid after a diagnosed OT-template selection defect. Do not use those files as forecast distributions. Alpha2 is the corrected research run.
