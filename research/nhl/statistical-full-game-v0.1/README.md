# NHL statistical full-game PBP model v0.1

Research-only empirical period-template bootstrap. It generates a complete hypothetical regular-season event record by sampling ordered historical periods, remapping event ownership to synthetic home/away labels, stripping player identifiers and coordinates, and recomputing score from generated goals. It does not generate player decisions or movement and is not matchup-specific.

The source is the external, read-only NHL GameCenter PBP archive. Before use, each selected PBP body and its separate GameCenter boxscore body are checked against frozen manifests and compressed-body hashes. The boxscore archive manifest contains 4,576 `official_gamecenter` records and 300 records carried forward from a prior official audit cache. No raw PBP, boxscore, or period cache is stored in this repository. Training uses eligible 2019–20 periods; 2018 is excluded for measured event-clock reversals, 2021 is development-only, and exposed/partial 2022 is excluded.

## Generate one game

From the LP worktree root:

```bash
python research/nhl/statistical-full-game-v0.1/nhl_statistical_game.py generate \
  --home-team HOME --away-team AWAY --seed 31415 \
  --out research/nhl/statistical-full-game-v0.1/examples/nhl-statistical-game-v0.1-seed-31415.json
```

`HOME` and `AWAY` are display labels only. They do not alter sampling. The output includes seed, model version, source-manifest hash, donor-period audit references, event-level score states, and explicit limitations. It is labelled `hypothetical_statistical_simulation`; do not describe it as a real fixture or a physical play reconstruction.

## Development diagnostic

```bash
python research/nhl/statistical-full-game-v0.1/nhl_statistical_game.py evaluate \
  --seed 20211025 --simulations 10000 \
  --out research/nhl/statistical-full-game-v0.1/results/nhl-statistical-game-v0.1-development-2021.json
```

The diagnostic fits period templates only on 2019–20 and evaluates the same league-level distribution over eligible 2021 games. It reports goal CRPS, official-score CRPS and energy, winner Brier, SOG CRPS, count calibration and game-resampled uncertainty intervals. This is development evidence, not a fresh adoption test. Because v0.1 ignores team identity, every 2021 game receives the same home/away score distribution.

The model requires verified PBP and boxscore bodies, matching game/team identity and scoreboard fields, three complete regulation periods, and valid source clocks. Event-derived SOG is checked against independent boxscore SOG; games that fail are quarantined from the complete-event template pool. The audit found zero PBP-versus-boxscore team score/SOG disagreements and zero goal-event/final-score mismatches over 4,533 games in start seasons 2018–2021, after the shootout score convention. Event-derived SOG differs from the independent boxscore in 60 games; the cause is unresolved and these games are quarantined. Shootout attempts are events but not player goals; the shootout winner's one-goal official-score adjustment is recorded as a separate `shootout-decision` event.

The shootout-path example uses seed 8 selected from the first seed range searched solely to exercise the tied-regulation/tied-overtime/shootout branch. It is a code-path demonstration, not an unbiased sample or model-performance evidence.

## Viewer boundary

The record is the LP-owned statistical outcome. A later Gridiron NHL viewer should read it without mutation and display a hypothetical event timeline and scoreboard. The NFL contract remains NFL-specific. No hockey 3D motion, roster identities, player ratings, possession mechanics or physical causality are claimed by this v0.1 output.
