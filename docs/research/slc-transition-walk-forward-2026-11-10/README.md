# Transition strength weekly walk-forward diagnostic — 2026-11-10

This offline diagnostic scores observed plays. It runs no simulations. The historical baseline and league situation distributions use 2022–2024 for 2025, and 2022–2025 for 2026. Current-season updates use strictly earlier weeks, never the target week. This conservative weekly freeze excludes earlier games in the same week. The source files and SHA-256 digests are recorded in `results.json`.

| Evaluation | Arm | Plays | Mean log loss | Multiclass Brier |
|---|---|---:|---:|---:|
| 2025 | League situation | 32,732 | 1.9920 | 0.8135 |
| 2025 | Historical team strength | 32,732 | 2.0576 | 0.8254 |
| 2025 | Current-season only, approximate | 32,732 | 2.0292 | 0.8217 |
| 2025 | Blend, N0=2 | 32,732 | 2.0240 | 0.8201 |
| 2025 | Blend, N0=4 | 32,732 | 2.0230 | 0.8196 |
| 2025 | Blend, N0=8 | 32,732 | 2.0244 | 0.8195 |
| 2026 | League situation | 12,478 | 1.9811 | 0.8103 |
| 2026 | Historical team strength | 12,478 | 2.0450 | 0.8217 |
| 2026 | Current-season only, approximate | 12,478 | 2.0063 | 0.8155 |
| 2026 | Blend, N0=2 | 12,478 | 2.0103 | 0.8158 |
| 2026 | Blend, N0=4 | 12,478 | 2.0142 | 0.8164 |
| 2026 | Blend, N0=8 | 12,478 | 2.0208 | 0.8175 |

Lower is better. Current-season evidence improves this candidate against its historical-only version, but none of the tested arms beats the league situation baseline. These results do not validate or reject the complete intended strength framework, or establish a game-winner Brier result.

The current-only arm uses `adapt` with N0=1e-9 and a neutral team profile. It is an approximation: current counts are still smoothed toward historical league cells with a 50-play prior. Week 1 uses the historical team prior for all team arms. Cells with no current evidence fall back to league ratios. The blended arms use the implementation's existing per-cell smoothing and team-game weights.

The 2025 sample includes postseason weeks and the 2026 snapshot covers seven weeks. Rows with unknown or positive penalty flags are excluded after ordered-play classification. Transition support comes from historical cells; outcomes outside support are scored with a 1e-15 probability floor. The pregame acquisition time and revision history of the source parquet are not verified, so this is a retrospective walk-forward diagnostic, not proof that every source value was available at the time. It does not include clustered uncertainty, matchup strength tiers, alternative transition priors, or a bounded V1.5 winner test. N0 values were examined on these same evaluation seasons and are not independently selected or validated.

Reproduce with `/root/legendarypicks/backend/venv/bin/python docs/research/slc-transition-walk-forward-2026-11-10/audit.py` from the repository root, with the source files at the path in the script.
