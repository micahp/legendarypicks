# Player-level research models: adapters, 2026-10-29

Each research model is checked against what SLC needs per play. The adapter is built where a per-play probability exists.

| Model | Source | What it outputs | Per-play role in SLC | Status |
|---|---|---|---|---|
| Receiver target share | `nfl-receiver-target-share-dist-v1` (79523c00) | Player-game target counts, Monte Carlo | The target on a dropback: each rostered receiver's share of team targets | Adapted as the prior-season target-share adapter (`player_shares.py`), with the floor for players without history. The Monte Carlo distributions are not ported |
| Rushing carries | `feat/nfl-rushing-carries-dist-v1` (24d793c6) | Player-game carry counts | The ball carrier on a run: each rostered back's share of team carries | Adapted as the prior-season carry-share adapter. Carry-count distributions not ported |
| Rushing participation | `feat/nfl-rushing-participation-v4` (fc6dba4b) | Snap or participation quantiles | None: participation is not a per-play decision in SLC | Not needed per play. Its output is a validation target for carries |
| QB opportunity | `feat/nfl-props-opportunities-propensity` (06cba41d) | Team attempts = plays per game x pass propensity x QB share | None: plays per game and the pass rate are produced by the engine itself (the play-call layer sets the dropback rate, and simulated plays set the volume). The starter QB is the passer | Not an input. Its projections are a validation target for simulated team attempts |

## Decisions

- The adapters use each player's observed share, the quantity the research distributions are built on. This is a first adapter; the
  distributions themselves are not ported, and that remains open.
- The QB opportunity model is not adapted as an input, because SLC generates its inputs. It becomes a check on simulated attempts.
- Participation is not drawn per play. It is a check on carry shares.

## Not done

- Porting the Monte Carlo target and carry distributions into the pre-event draw.
- Using simulated attempts and carries as an evaluation against those models' projections, on eligible seasons only.
