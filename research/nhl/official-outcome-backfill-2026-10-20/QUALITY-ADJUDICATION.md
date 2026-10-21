# NHL official outcome quality adjudication

**Base:** `research/nhl/official-outcome-backfill-2026-10-20` at `c91ae36c39b57f86c7c839a2e424eec3ee9330a0`

**Scope:** SOG, goalie saves, shots against, goals against, and research-label eligibility.
**Decision:** Resolve all 20 skater/team SOG discrepancies as a comparison-scope error. Leave both goalie arithmetic conflicts unresolved and quarantine their six statistic labels.

No source outcome, normalized backfill file, canonical game population, goalie preregistration, model, or production data was changed. This work did not fit or calibrate a model, evaluate a market or ROI, or make sportsbook settlement claims.

## Findings

The 20 SOG validation alerts were all a one-shot difference between the sum of forward and defense rows and the official team total. For each affected team-side, I independently reconstructed the skater SOG values from the pinned original GameCenter payload and reconciled NHL play-by-play events by numeric player ID. Every skater's event count matched the original value. The additional team SOG was one event credited to a same-team goalie. The PBP summary and original official team SOG agreed for all 44 sides in the 22 affected games.

Nineteen of the extra goalie events are `shot-on-goal` events. In game `2019020684`, Pekka Rinne (NHL ID `8471469`) scored a goal with a `wrist` shot type (event 702); it is included in Nashville's SOG total. This confirms that the validator compared skater-only rows against a team total that also includes goalie SOG. No skater value was adjusted.

The two goalie records remain internally inconsistent:

| Game (date) | Goalie (NHL ID) | Published saves / GA / SA | PBP evidence | Decision |
|---|---|---:|---|---|
| `2022020158` (2022-11-01) | A. Stolarz (`8476932`) | 40 / 5 / 44 | 40 explicit non-goal shot-on-goal events; 5 regulation goals against, four with `shotType`, one without; opponent team SOG 44. Game ended in a shootout, which is excluded from these regulation counts. | Quarantine saves, GA, and SA. The untyped goal's shot classification does not identify which published field causes `40 + 5 != 44`. |
| `2022020276` (2022-11-19) | U. Luukkonen (`8480045`) | 19 / 5 / 23 | 19 explicit non-goal shot-on-goal events; 5 regulation goals against, four with `shotType`, one without; opponent team SOG 23. | Quarantine saves, GA, and SA. The untyped goal's shot classification does not identify which published field causes `19 + 5 != 23`. |

For both games, numeric player ID, team, game, and TOI agree between the original GameCenter record and the NHL Stats REST response. The historical NHL Game Summary repeats the goalie lines `5-44` and `5-23`, respectively. The original fields, Stats REST, PBP event counts, PBP team SOG, and Game Summary are preserved in `goalie_event_reconciliation.csv` and linked in the ledger with URLs, retrieval timestamps, and hashes. These NHL surfaces corroborate the displayed values; they do not resolve the failed identity. There is no correction and saves are never calculated as `SA - GA`.

### SOG discrepancies, individually reconciled

“Skater sum → official team SOG” is the sum of the original forward and defense rows compared with the official team total. The goalie ID and PBP event ID identify the additional team SOG event. Each row links to a game/team issue record in `adjudication_ledger.csv`; per-skater values, counts, event types, and source hashes are in `sog_event_reconciliation.csv`.

| Game ID | Date | Season | Team | Skater sum → official | Goalie NHL ID | PBP event (type) |
|---|---|---:|---|---:|---:|---|
| `2018020160` | 2018-10-28 | 2018 | DET | 22 → 23 | `8473541` | 617 (`shot-on-goal`) |
| `2018020755` | 2019-01-20 | 2018 | CAR | 33 → 34 | `8475852` | 541 (`shot-on-goal`) |
| `2019020076` | 2019-10-13 | 2019 | VGK | 35 → 36 | `8470594` | 662 (`shot-on-goal`) |
| `2019020106` | 2019-10-17 | 2019 | LAK | 46 → 47 | `8475789` | 246 (`shot-on-goal`) |
| `2019020623` | 2019-12-31 | 2019 | EDM | 30 → 31 | `8475156` | 555 (`shot-on-goal`) |
| `2019020684` | 2020-01-09 | 2019 | NSH | 29 → 30 | `8471469` | 702 (`goal`, wrist shot) |
| `2019020951` | 2020-02-22 | 2019 | CAR | 46 → 47 | `8479188` | 468 (`shot-on-goal`) |
| `2020020266` | 2021-02-18 | 2020 | NYR | 32 → 33 | `8480382` | 770 (`shot-on-goal`) |
| `2020020373` | 2021-03-05 | 2020 | BOS | 24 → 25 | `8470860` | 638 (`shot-on-goal`) |
| `2020020468` | 2021-03-18 | 2020 | BUF | 23 → 24 | `8475622` | 319 (`shot-on-goal`) |
| `2020020491` | 2021-03-20 | 2020 | EDM | 36 → 37 | `8469608` | 380 (`shot-on-goal`) |
| `2020020613` | 2021-04-06 | 2020 | NYR | 24 → 25 | `8478048` | 395 (`shot-on-goal`) |
| `2020020791` | 2021-04-30 | 2020 | MTL | 34 → 35 | `8474596` | 582 (`shot-on-goal`) |
| `2021020065` | 2021-10-22 | 2021 | VGK | 38 → 39 | `8475215` | 84 (`shot-on-goal`) |
| `2021020405` | 2021-12-09 | 2021 | CBJ | 33 → 34 | `8478007` | 59 (`shot-on-goal`) |
| `2021020555` | 2021-12-30 | 2021 | NSH | 33 → 34 | `8479496` | 468 (`shot-on-goal`) |
| `2021020677` | 2022-01-15 | 2021 | COL | 31 → 32 | `8475311` | 192 (`shot-on-goal`) |
| `2021020769` | 2022-01-28 | 2021 | COL | 26 → 27 | `8480925` | 652 (`shot-on-goal`) |
| `2021021278` | 2022-04-26 | 2021 | EDM | 41 → 42 | `8469608` | 752 (`shot-on-goal`) |
| `2022020222` | 2022-11-11 | 2022 | WSH | 23 → 24 | `8475311` | 18 (`shot-on-goal`) |

The SOG root cause is the validator's comparison frame, not a skater parsing discrepancy: it summed skaters while comparing against a team total that includes goalie SOG. We found no missing skater identity or team attribution error in these 20 cases. PBP confirms the individual skater values for the affected sides; unaffected sides remain eligible under the original source verification, valid numeric identity/appearance, and passing team SOG total check. This is not an event-by-event PBP audit of every historical player-game row.

## Label statuses and before/after

| Scope | Before adjudication | Final status | Research-label result |
|---|---|---|---|
| 20 SOG team-side issues | No player-level disposition | 20 `ADJUDICATED`, 0 quarantined | 360 skater SOG values individually match numeric-ID PBP event counts; all remain eligible |
| Two goalie arithmetic issues | No field-level disposition | 2 source issues `QUARANTINED` | All six goalie saves/SA/GA fields retain their source values but have empty `accepted_value`; excluded from training, evaluation, and grading |
| Unaffected positive-TOI skater SOG | No quality status | `VERIFIED` where source/identity/appearance and team-side checks pass | Eligible |
| Other positive-TOI goalie saves, SA, GA | No quality status | `VERIFIED` where identity, appearance, and `saves + GA = SA` pass | Eligible |
| Zero-TOI goalie slots | Stored official roster rows | `NOT_APPLICABLE` | Retained for audit; excluded from played-goalie outcomes |

Status definitions:

- `VERIFIED`: published value has valid game/player identity and appearance, passes the applicable integrity/consistency checks, and has no known conflict. For unaffected SOG rows, this includes the team-side sum check, not independent PBP event validation of each player.
- `ADJUDICATED`: the discrepancy is resolved by documented numeric-ID event evidence. The official value is unchanged.
- `QUARANTINED`: published value remains visible, but a conflicting field-level issue is unresolved. `accepted_value` is blank and all eligibility flags are false.
- `NOT_APPLICABLE`: the player did not have a played-game appearance or the statistic does not apply. Zero-TOI backups are never zero-save outcomes.

### Eligible rows by start season and statistic

Goalie counts in each row apply to **each** of SAVES, SHOTS_AGAINST, and GOALS_AGAINST. Thus the six goalie quarantines are two records in each of three statistics.

| Start season | SOG eligible | SOG adjudicated | SOG quarantined | Goalie eligible per statistic | Goalie adjudicated per statistic | Goalie quarantined per statistic |
|---:|---:|---:|---:|---:|---:|---:|
| 2018 | 45,755 | 36 | 0 | 2,720 | 0 | 0 |
| 2019 | 38,949 | 90 | 0 | 2,306 | 0 | 0 |
| 2020 | 31,226 | 108 | 0 | 1,852 | 0 | 0 |
| 2021 | 47,208 | 108 | 0 | 2,818 | 0 | 0 |
| 2022 | 12,344 | 18 | 0 | 721 | 0 | 2 |
| **Total** | **175,482** | **360** | **0** | **10,417** | **0** | **2** |

There are 234,008 field rows in total: 175,490 skater SOG records and 19,506 goalie records × three statistics. The status totals are 206,373 `VERIFIED`, 360 `ADJUDICATED`, six `QUARANTINED`, and 27,269 `NOT_APPLICABLE`. Eligible field rows are 175,482 SOG, 10,417 for each goalie statistic, or 206,733 total across the four statistic columns. These are field-row counts, not unique players or games. No source value was corrected or imputed.

## Population and identity checks

The frozen populations remain separate:

| Population | Games |
|---|---:|
| Canonical official frame | 4,876 |
| SBR market subset | 4,872 |
| Goalie preregistration complete cases | 4,763 |
| Goalie preregistration out-of-fold evaluation | 3,509 |

The 4,876-game frame includes 343 games in the partial 2022-23 archive slice; SBR contains 339 there. The preregistration's 4,763 and 3,509 denominators were neither recalculated nor changed.

The archive reconciliation overlap check found one of seven one-sided played-goalie rows in an SOG-issue team-side: David Ayres (`8479188`) in game `2019020951`; his 28:41 official appearance and PBP goalie event are retained. Archive absence did not invalidate his appearance. Of five potential name-alias IDs, Alexis Lafrenière (`8482109`) appears on two affected NYR sides (`2020020266` and `2020020613`); PBP confirms the numeric ID on the event records. No player identity was changed by display name, and neither goalie arithmetic player ID is one of the alias IDs.

## Reproduction and provenance

The original backfill artifacts and raw GameCenter payloads remain unchanged. Original raw payloads remain outside Git at `/root/lp-data/nhl-official-outcome-backfill-2026-10-20/`; independently fetched PBP, Stats REST, and Game Summary bodies remain outside Git at `/root/lp-data/nhl-official-outcome-quality-adjudication-2026-10-20/`. `research_label_source_pins.json` pins original normalized inputs and manifests; each build rehashes/decompresses all 4,876 original GameCenter bodies and checks their game IDs against that pinned manifest. The new evidence manifests record URLs, retrieval times, byte lengths, and SHA-256 hashes. Source bodies are verified against those hashes on every build.

Relevant source endpoints:

- NHL GameCenter play-by-play: `https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play`
- NHL Stats REST goalie summary: `https://api.nhle.com/stats/rest/en/goalie/summary?isAggregate=false&isGame=true&cayenneExp=gameId={game_id}&limit=100`
- Historical Game Summaries: [2022-11-01, game 2022020158](https://www.nhl.com/scores/htmlreports/20222023/GS020158.HTM), [2022-11-19, game 2022020276](https://www.nhl.com/scores/htmlreports/20222023/GS020276.HTM)

Rebuild the five derived outputs with `python3 build_research_labels.py --write`. Verify without writing with `python3 build_research_labels.py`. The reader `read_research_labels()` exposes source value, accepted value, and status; callers may request a statistic and explicitly filter by `training`, `evaluation`, or `grading`. Without an eligibility filter, quarantined and not-applicable source rows stay visible for audit.

The original official artifact verifier was rerun against a temporary copy of the frozen artifact set. It passed: 4,876 frame games; 4,876 raw responses verified; 175,490 skater rows; 19,506 goalie rows; 9,752 team sides; and the original 22 issues. Its original verification file was not overwritten. The standalone test suite also checks hash failures, deterministic output, issue dispositions, source immutability, eligibility, zero-TOI handling, and numeric-ID joins.

## Research use and limitations

The eligible official outcomes are suitable for historical player-prop **model development** when downstream code selects only rows with the relevant `eligible_* == true` flag and carries the quality status. The two goalie records are excluded for all three goalie target statistics. The SOG discrepancy cases remain eligible because every affected skater's value is independently matched to a PBP player ID.

This is not proof of historical sportsbook settlement. Settlement claims still require book-specific market availability, exact player/market/line/price records, grading rules in force, and stat-correction timing. The archived NHL outcomes do not establish that a sportsbook offered a given prop or graded it identically. Quality approval also does not imply model skill, price coverage, ROI, or deployability.
