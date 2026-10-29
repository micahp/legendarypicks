# Player-level research models: adapters, 2026-10-29

Each research model is checked against what SLC needs per play. The adapter is built where a per-play probability exists.

| Model | Source | What it outputs | Per-play role in SLC | Status |
|---|---|---|---|---|
| Receiver target share | `nfl-receiver-target-share-dist-v1` (79523c00) | Player-game target counts, Monte Carlo | The target on a dropback: each rostered receiver's share of team targets | Prior-season shares via `player_shares.py`; SLC per-game Dirichlet-multinomial draw via `share_distributions.py`, behind `--playcall-dirichlet-shares` and off by default. The external Monte Carlo model is not ported |
| Rushing carries | `feat/nfl-rushing-carries-dist-v1` (24d793c6) | Player-game carry counts | The ball carrier on a run: each rostered back's share of team carries | Prior-season carry shares are adapted. SLC per-game Dirichlet-multinomial draw is behind `--playcall-dirichlet-shares` and off by default. The external carry-count distribution is not ported |
| Rushing participation | `feat/nfl-rushing-participation-v4` (fc6dba4b) | Snap or participation quantiles | None: participation is not a per-play decision in SLC | Not needed per play. Its output is a validation target for carries |
| QB opportunity | `feat/nfl-props-opportunities-propensity` (06cba41d) | Team attempts = plays per game x pass propensity x QB share | None: plays per game and the pass rate are produced by the engine itself (the play-call layer sets the dropback rate, and simulated plays set the volume). The starter QB is the passer | Not an input. Its projections are a validation target for simulated team attempts |

## Decisions

- The SLC Dirichlet-multinomial share draw uses the observed prior-season player shares as its mean and fits its concentration by
  maximum likelihood. A chronological 2024 fit and 2025 held-out score is recorded in
  SLC-PLAYER-SHARE-VALIDATION-2026-10-29.md. The external models' full distributions remain separate.
- The QB opportunity model is not adapted as an input, because SLC generates its inputs. It becomes a check on simulated attempts.
- Participation is not drawn per play. It is a check on carry shares.

## Not done

- Porting the external models' original Monte Carlo target and carry-count distributions. SLC currently uses a separate fitted Dirichlet-multinomial share model.
- Using simulated attempts and carries as an evaluation against those models' projections, on eligible seasons only.
