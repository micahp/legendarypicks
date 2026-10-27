# NHL Projected Roster and Shootout Eligibility Data Gap

- **Date:** 2026-10-26
- **Branch:** `research/nhl-shootout-roster-2026-10-26`
- **Base:** `a23d08b54bf1bb1939a4842d0e6c9f94acd785ec`
**Scope:** research-only roster projection and independent validation; no production forecast, database, or frozen Phase 2A changes.

## Finding

The historical archive contains overtime and shootout evidence. The frozen behavior audit records 160 shootout terminal events among 1,921 training games (2019–20) and 96 among 1,292 development games (2021). It also confirms GameCenter `rosterSpots` are available retrospectively. Those target-game lineups are not valid pregame inputs.

The generated record previously carried a broad prior-player pool rather than a declared simulated game roster. The independent validator therefore could not determine whether simulated shootout shooters belonged to the simulated team’s eligible roster or whether an active 10-minute misconduct exclusion applied.

## Change

Both the archive-backed historical adapter and the Legendary Picks database-backed input path now create a deterministic **pregame projected game roster** from cutoff-valid inputs:

- 12 forwards and 6 defensemen ranked by prior average ice time, then shots and NHL ID.
- Up to 2 goalies ranked by prior starts, shots faced and NHL ID.
- Player-profile hashes include the selected game-roster IDs.
- Shift remapping, on-ice replacement, goalie sampling, player totals and shootout selection use only projected-roster IDs.
- Shootout shooters exclude players in an active modeled 10-minute misconduct. A player cannot repeat until all eligible projected-roster players on that team have attempted. Goalies remain eligible under Rule 84.4.

The independent validator now checks projected-roster size and positions, identity/side consistency, event participation and totals. It independently reconstructs active modeled misconduct exclusions for the shootout and checks shooter eligibility and rotation. Projected-roster consistency is a supplementary diagnostic; it is not in the required structural-check set. The existing Gate 1 acceptance set is unchanged.

The record marks this as a projection and explicitly records that no target-game lineup was used. The separate official `game_lineup_eligibility` check remains `NOT_ASSESSED`: a projected roster cannot prove who was officially dressed for a historical target game. The simulator also does not model game or match misconduct, injuries, or lineup changes that would alter actual Rule 84.4 eligibility.

## Legendary Picks database coverage

A read-only audit used the latest roster snapshot available by the frozen cutoff, snapshot 815 (`nhle.com:roster`, published `2026-10-26T22:58:18.879156Z`, source checksum `2f9de2cf8bb56e878bb11f7cf55dd50b9b8587112f4f6a8f3345ab40a28ce66c`). All 32 teams produced a 20-player projection with 12 forwards, 6 defensemen and 2 goalies; there were no projection failures. The audit uses SQLite `mode=ro` and `PRAGMA query_only=ON`.

The database audit is recorded in [`pregame-roster-db-2026-10-26.json`](../../research/nhl/game-rules-gate1/results/pregame-roster-db-2026-10-26.json). Its command is:

```bash
python research/nhl/game-rules-gate1/audit_pregame_roster_db.py \
  --game-date 2026-10-27 \
  --cutoff 2026-10-26T23:00:00Z \
  --output research/nhl/game-rules-gate1/results/pregame-roster-db-2026-10-26.json
```

Historical backtests continue to use prior eligible GameCenter box scores, not the current Legendary Picks database, whose NHL historical logs do not cover the 2019–2021 evaluation populations.

## Frozen 120-record diagnostic

The same six 2021 development matchups and 120 seeds were rerun in a new output directory. Seeds follow `202610260001 + target_index * 100 + draw_index`. These games are already exposed development evidence, not an untouched evaluation set. The runner generated all 120 games with zero generation errors. A second process re-ran the independent validator against every saved record; all 120 stored audit hashes and check results matched.

| Check/result | Before projected roster | Projected roster v1 |
|---|---:|---:|
| Generated games / generation errors | 120 / 0 | 120 / 0 |
| Structurally valid games | 109 | 115 |
| Overtime/shootout check `PASS` | 112 | 120 |
| Overtime/shootout check `NOT_ASSESSED` | 8 | 0 |
| Penalty/manpower `QUARANTINED` | 3 | 5 |
| Simulated-roster consistency check | absent | 120 `PASS` |
| Official target-lineup check | 120 `NOT_ASSESSED` | 120 `NOT_ASSESSED` |
| Full-rule-assessed games | 0 | 0 |

The projected-roster run produced 13 shootout games and 108 shootout attempts; every shooter was on that simulation’s projected roster, and the independent shooter-eligibility check passed. The five remaining structural non-passes are explicitly quarantined unsupported penalty transitions; there were no independent hard `FAIL` findings. Runtime was 48.914 seconds for fitting, 59.968 seconds for generation, and 0.470 seconds median per generated game.

The roster constraint changes player participation and can change game outcomes. Therefore these same-seed counts are a structural diagnostic, not a controlled predictive-performance comparison. No goal/SOG skill or adoption claim is made. The previous run’s three penalty quarantines versus five here should not be interpreted as a treatment effect; the generated records differ under the roster restriction.

The compact independently re-audited result is [`projected-roster-v1-final-120-audit.json`](../../research/nhl/game-rules-gate1/results/projected-roster-v1-final-120-audit.json). The full generated records remain outside Git at `/root/lp-data/nhl-game-rules-gate1-2026-10-26-projected-roster-v1-final-120/`.

## Verification

Passed:

- `python -m unittest discover -s research/nhl/statistical-full-game-v0.2b/tests -p 'test_*.py'` — 41 tests.
- `python -m unittest discover -s research/nhl/game-rules-gate1/tests -p 'test_*.py'` — 24 tests.
- `python -m py_compile research/nhl/statistical-full-game-v0.2b/nhl_game_state_sim.py research/nhl/statistical-full-game-v0.2b/historical_adapter.py research/nhl/game-rules-gate1/validator.py research/nhl/game-rules-gate1/run_diagnostic_sample.py research/nhl/game-rules-gate1/summarize_projected_roster_run.py research/nhl/game-rules-gate1/audit_pregame_roster_db.py`.
- Fixed-seed smoke: `python research/nhl/game-rules-gate1/run_diagnostic_sample.py --smoke --games 6 --draws 1 --output-dir /root/lp-data/nhl-game-rules-gate1-2026-10-26-projected-roster-smoke` — one game twice, canonicalized records byte-identical, native validation passed, independent projected-roster and shootout checks passed.
- Full diagnostic: `python research/nhl/game-rules-gate1/run_diagnostic_sample.py --games 6 --draws 20 --output-dir /root/lp-data/nhl-game-rules-gate1-2026-10-26-projected-roster-v1-final-120` — all 120 records revalidated; zero discrepancies between saved and freshly computed independent audit results.
- Summary re-audit: `python research/nhl/game-rules-gate1/summarize_projected_roster_run.py /root/lp-data/nhl-game-rules-gate1-2026-10-26-projected-roster-v1-final-120 --output research/nhl/game-rules-gate1/results/projected-roster-v1-final-120-audit.json`.
- Read-only current-roster DB audit: 32/32 teams projected.

## Remaining limitation

This closes the missing **simulated-roster declaration and internal shootout-eligibility check**. It does not establish that the projected 20 players equal the actual target-game dressed lineup, or that all official lineup eligibility conditions are modeled. That distinction remains explicit in the validator. No gate, forecast, or adoption decision changed.

Shootout eligibility rules were checked against the [2021–22 NHL Official Rules, Rule 84.4](https://media.nhl.com/site/asset/public/ext/2021-22/2021-22Rules.pdf). Use the season-applicable rulebook for other seasons.
