# NHL full-game simulation delivery plan

**Date:** 2026-10-25  
**Status:** Research plan; first deliverable is the statistical event-stream model.  
**Legendary Picks base:** `2c7c36ce2f77307a11a70c1ad3ec3cd2e27349e8` (`origin/dev`)  
**Gridiron Physics references:** main `37b01a764e69669e457c70367ecf5ba26ec31825`; hockey movement research `c35d1ba7e395f2a0a93f493b441cfe40ed21ba1f`.

> **Pre-fit source-quality correction (2026-10-25):** the initial 2018–2020 training window below is superseded. NHL `sortOrder`-ordered PBP clocks in start season 2018 fail chronology: 1,268/1,271 games contain 13,394 event-level clock reversals, with a maximum of 1,200 seconds. The same audit found no clock reversals in start seasons 2019–2021. Exclude 2018 from the model until its event ordering can be independently repaired. The statistical model now trains on eligible 2019–2020 games and develops on 2021. The first generated sample, created before this correction, is discarded and is not evaluation evidence.

## Objective

Build the NHL counterpart to the three separate football systems documented in Gridiron Physics:

1. **Observed-game replay:** reconstruct a historical game from its actual NHL play-by-play.
2. **Statistical full-game simulation:** generate a complete hypothetical event stream and score from learned statistical patterns, then let a viewer display those generated events.
3. **Movement/physics simulation:** generate player movement from sport-specific policies, roles and supported player attributes; physical execution may later determine selected event outcomes.

These are different data products. A historical replay may show what happened. A statistical game is a hypothetical sampled script. A movement simulation is not an outcome model merely because it is displayed in 3D. Do not label generated events as observed or imply that a renderer caused their outcomes.

The first implementation is the statistical full-game model. It is research-only and does not change NHL forecasts, the NHL V3 shot model, production databases, NFL code, or the NFL `GRIDIRON-CONTRACT-v1`.

## Existing work and boundaries

| Track | Existing evidence | What it does not establish |
|---|---|---|
| Historical event data | A local, hashed archive of official NHL GameCenter play-by-play; see the verified manifest below. | The archive is not currently a production database table or a prospective game model. |
| NHL score model | The NHL model-call research includes an aggregate period simulator with a score-state effect and explicit OT/shootout resolution. | It does not emit a chronological play-by-play event record. |
| NHL V3 | A shot-process simulator with generated shot attempts and outcomes. | It is not a complete game event stream and its exposed 2022 scoring results are not a fresh evaluation set. |
| Gridiron hockey movement | The hockey adapter at the referenced research commit executes learned, interaction-aware 2D movement from ordinal observations. | It has no verified cross-game athlete identities, player ratings, calibrated timebase, validated possession, or physical contact mechanics. It is not a full-game play generator. |
| Gridiron game viewer | Gridiron's NFL record contract and event viewer establish the LP-owned-result / Gridiron-owned-display boundary. | The NFL contract and football play payload are not NHL schemas and must not be reused as if hockey events were football plays. |

The new code is needed because the existing NHL score and shot models do not emit a complete, ordered game event stream. Use NHL-published event and scoreboard fields from the archived source. Do not recreate published event meanings where the source already provides them.

## Data inventory and eligibility

The source is the read-only local cache at:

`/root/lp-data/nhl-fullframe-event-audit-2026-10-21`

The hardened PBP manifest is `manifests/hardened-v1/pbp_verified_manifest.csv`, SHA-256 `d87e40a3387f014429377cc8dfb010cec8ca2d0e4d03d0b5bdbfacd8de9ca990`. Its source-list summary records 4,876 regular-season games across start seasons 2018–2022, including 343 games in the partial 2022 slice. The sequential audit verified all 4,876 local compressed-body sizes and hashes and read 1,510,104 PBP events. Raw source data and derived period templates stay outside Git.

The first model uses a time-separated development design:

- **Training:** start seasons 2019–2020, after source-quality quarantine.
- **Development:** start season 2021.
- **Source-quality quarantine:** start season 2018, pending resolution of the measured chronology failures above.
- **2022:** excluded from fitting and selection. Earlier NHL V3 work exposed this slice; it is not a new holdout. Its 343 archived games are also partial-season coverage.
- **Later-season/prospective evaluation:** not available in this archive. No adoption claim is allowed until an independent later-season or prospective population is acquired and frozen.

Data-quality audit over 2018–2021 (4,533 games) cross-checked the PBP archive against a separate local NHL GameCenter `/boxscore` archive. The boxscore manifest SHA-256 is `0ba44bcebefecb0a8eefbea995e8f5370583600eec77d0be12be574f308d71a2` and covers 4,876 records: 4,576 `official_gamecenter` plus 300 carried forward from a prior official audit cache. Every one of the 4,533 selected PBP and boxscore compressed bodies passed manifest size/hash verification; game and home/away team IDs matched. There were zero PBP-versus-boxscore final score or team SOG field disagreements. PBP goal events also reconciled to the separate final score in all games after applying the NHL shootout convention: the shootout winner receives one official final-score goal, while shootout attempts are not player goals. Event-derived SOG (`shot-on-goal` plus regulation/OT goal events) disagreed with boxscore SOG in 60 games (2018:12, 2019:17, 2020:11, 2021:20). The cause is not established. Quarantine those games from the complete-event template pool; do not silently “correct” the source. Score, SOG, chronology and other event components retain separate eligibility flags. The `sortOrder`-ordered clock audit found 13,394 backward timestamp transitions in 1,268/1,271 start-season 2018 games (maximum 1,200 seconds), versus none in start seasons 2019–2021. The 2018 timeline is therefore ineligible for this model even where score and SOG reconcile.

MoneyPuck is not used: commercial/model-training permission is unresolved in the existing NHL source notes. No ESPN requests or new provider acquisition are part of this work.

## First deliverable: statistical PBP simulation v0.1

### Frozen model definition

Implement an **empirical period-template bootstrap**. For a fixed seed, independently draw one complete regular-season event period for each of the three regulation periods from eligible 2019–2020 source periods. Do not reuse a donor game within a generated game. Map source home/away event ownership to the requested synthetic home/away labels, preserve event order and source game clock, strip source player identities and source coordinates, and derive the generated score only from generated goal events.

If regulation ends tied, sample a complete five-minute overtime period from the eligible training pool. An overtime goal ends the game immediately. If overtime expires tied, use that same donor game's shootout sequence and winner; represent shootout attempts as attempts, not player goals, then apply the NHL one-goal final-score convention to the winner. A generated record must not end tied.

This is an intentionally simple statistical baseline. It resamples observed event sequences at the period level; it is not a learned next-event state machine, a team-strength matchup forecast, or a physical simulation. Its purpose is to provide a complete, reproducible PBP-shaped game record that can be measured before adding conditional complexity.

### Output record

The LP-owned immutable JSON record carries:

- NHL-specific schema and mode labels (`hypothetical_statistical_simulation`).
- Synthetic simulation ID, requested home/away display labels, model version, seed and source-manifest hash.
- Ordered events with game sequence, period type, elapsed/remaining clock, event type, home/away side, safe whitelisted non-identity event details, and score before/after.
- A generated event log and derived summary for regulation/OT goals, SOG event counts, shootout winner and official final score.
- Explicit source period references for audit, kept out of event display text; source athlete IDs, names and coordinates are removed from the emitted play records.
- Eligibility, quarantine and validation metadata. Unknown event owners, bad hashes, invalid clocks, missing periods or unresolved tied finals fail generation rather than falling back silently.

The model itself does not provide motion or an exact rink replay. A future Gridiron NHL viewer should display the event sequence and state as a **hypothetical statistical simulation**. The displayed event is the model's event record; any later animation is a separate visualization and cannot change the result.

### First-deliverable gates

1. Only verified, eligible training source periods are sampled; data eligibility and exclusions are reported.
2. For a fixed interpreter/runtime, seed and input labels, output is deterministic.
3. Every regulation period is 20:00; overtime is at most 5:00; shootout occurs only after a tied overtime; the game reaches a winner.
4. Final score is recomputed from generated goal events plus the single shootout deciding-goal convention. Shootout goals do not become player goals.
5. Event order, period clock, score transitions, shot counts and summary agree arithmetically; no source player IDs or coordinates leak into generated event records.
6. Run a 2021 development-only distribution diagnostic for score, margin, SOG and event counts. Report uncertainty and limitations; do not tune against 2022.
7. No raw PBP or derived template cache is committed; no production DB writes, forecast changes, merge or push.

## Delivery phases

| Phase | Deliverable | Gate |
|---|---|---|
| 1. Statistical event stream (current) | Period-bootstrap generator, NHL-specific JSON shape, one reproducible sample game, development diagnostic and report. | Complete game accounting, data provenance, quarantine and fixed-seed repeatability. |
| 2. Gridiron event viewer | Read-only event timeline/scoreboard consumer in a separate NHL schema and worktree. Preserve the LP result byte-for-byte and label the screen hypothetical. | Real generated record loads; event order, clocks and score display match LP JSON. No implied physical causality. |
| 3. Conditional statistical model | Compare a state-conditioned event process and forward-only team attack/defense effects against the frozen v0.1 bootstrap and score-only baselines. | Preregister candidate and metrics; train on prior seasons, select on 2021 development, preserve 2022 as historical diagnostics, then require independent later data for adoption. |
| 4. Role-based movement and physics | NHL policy/role decisions with player attributes only where identity, source time and ratings are independently verified; optional constraints remain hockey-specific. | Independent tracking games, no target-game future input, movement and event outcomes evaluated separately, no NFL solver reuse by assumption. |

## Separate movement-model requirements

The longer-term hockey system should have sport-neutral execution interfaces and hockey-specific behavior/configuration. Its first useful model can combine deterministic role policies with player ratings only when player identities and rating provenance support them. Keep observed tracking, generated movement and statistical PBP events visually distinct. The ten Stathletes games remain development-only; their ordinal observation index is not physical time, and prior event-to-tracking alignment failed its gate. They cannot validate NHL-wide forecast probabilities or time-calibrated speed, acceleration, reaction, possession or collision mechanics.

Do not require a physics solver to complete the statistical event generator. Conversely, do not call a statistical PBP viewer a physical hockey simulation.

## Decision rule

Keep v0.1 as a research prototype unless a frozen, independent later-season or prospective evaluation shows that a more conditional model improves the predeclared game/event metrics without breaking arithmetic, reproducibility, or the existing SOG advantage. Until then, do not promote it into Legendary Picks forecasts or present it as a validated NHL game simulator.
