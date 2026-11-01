# Pixel Red Zone R0 source audit

**As of:** 2026-11-01 07:01 UTC
**Status:** Historical ESPN summary contract captured; R0 remains open pending live NFL observations and revision/latency evidence.
**Scope:** Evidence for the [Pixel Red Zone specification](https://github.com/micahp/legendarypicks/blob/docs/pixel-redzone-arcade-training-2026-11-01/docs/product/legendary-play/PIXEL-RED-ZONE-CHANNEL-SPEC-2026-11-01.md). This audit uses the app's configured ESPN client and keeps historical evidence separate from live claims.

## ESPN access and current slate

The existing `espn_client` successfully fetched ESPN's NFL `/summary?event=...` responses through its configured `site.web.api.espn.com` client. Eight historical requests completed without errors on Nov. 1 between 06:57:14 and 06:57:25 UTC. A separate ESPN scoreboard request returned 13 completed games for Sept. 7, 2025; eight matching summaries were captured.

The managed app's `GET /api/nfl/games?date=2026-11-01` returned 12 games, all scheduled, at 06:55 UTC. A direct request through the same configured ESPN client returned those 12 scheduled events again at 07:01:19 UTC, before kickoff. The current slate and event IDs are retained in the capture manifest. No game was live at either sample time, so a live NFL situation and in-game latency remain unobserved.

## Historical fixtures

The decoded ESPN summary responses and per-capture manifest are under [`fixtures/pixel-red-zone-2026-11-01/`](fixtures/pixel-red-zone-2026-11-01/); see [`capture_manifest.json`](fixtures/pixel-red-zone-2026-11-01/capture_manifest.json) for exact hashes and counts. Each fixture is stored as JSON; the manifest records event ID, capture time, byte length, SHA-256, field coverage, and score reconciliation. The sample contains 8 games, 157 drives, 1,464 nested play records, and 1,464 distinct play IDs within those captures.

| ESPN event | Matchup | Plays | Verified coverage |
|---|---|---:|---|
| `401772830` | TB at ATL | 187 | TDs, FGs, PATs, reviews |
| `401772829` | CIN at CLE | 180 | TDs, FGs, PATs, turnovers, review |
| `401772719` | MIA at IND | 163 | TDs, FGs, PATs, two-point pass, turnovers |
| `401772720` | LV at NE | 197 | TDs, FGs, PATs, turnovers |
| `401772718` | ARI at NO | 195 | TDs, FGs, PATs, turnover, review |
| `401772721` | PIT at NYJ | 175 | TDs, FGs, PATs, two-point rush/pass |
| `401772827` | NYG at WSH | 190 | TDs, FGs, PATs, turnovers, reviews |
| `401772828` | CAR at JAX | 177 | TDs, FGs, PATs, turnovers, reviews |

Across the eight samples, ESPN supplied 33 touchdown records, 28 field-goal records, 33 structured `pointAfterAttempt` results (including extra points and two-point attempts), 12 plays with `isTurnover=true`, and 10 structured review objects. The last play score and summary-header score for every game matched that game's final ESPN scoreboard score (8/8). These checks establish historical field availability and final-score reconciliation for this sample; they do not establish live update behavior.

## ESPN play shape and field coverage

The play records are nested at `drives.previous[*].plays`; the sampled summaries have no top-level `plays` array. Each nested play has a publisher `id`, sequence number, type, period, clock, scores, scoring flag, text, start/end state, and `modified` timestamp. `pointAfterAttempt` and `review` are structured fields, not merely text labels. The captured `wallclock` is absent on 5 of 1,464 plays; missing source values remain null.

For the 1,464 play records, `id`, period number, clock display, home/away score, type text, scoring flag, `modified`, `start`, and `end` were present on every record. Both start and end contained down, distance, yard line, and yards to end zone on all 1,464 records. Start possession text was present on 1,356 records and end possession text on 1,337. The publisher's `wallclock` was present on 1,459 records. Counts by game and exact hashes are in the capture manifest.

ESPN's `review` object records review type and upheld status on the sampled review plays. Try results appear as `pointAfterAttempt` on the touchdown play; no separate stable play ID for a try was established. Two-point outcomes are present in this field and/or the play description. The UI must retain ESPN's source values and must not invent a separate play event or ball path from the prose.

### Independent field-position check

I joined these ESPN event IDs to the development database's `nfl_schedule.espn`, then matched plays to its separately sourced `nfl_pbp` rows using period, game clock, possession team, down, and distance. Yard position was deliberately excluded from the join. Only unambiguous one-to-one matches were compared. The independent `nflfastR` definition of `yardline_100` is yards from the opponent end zone for the possession team ([field definitions](https://nflfastr.com/articles/field_descriptions)).

Of 988 unique matched plays, ESPN `start.yardsToEndzone` exactly matched `nfl_pbp.yardline_100` on 956 (96.76%); 22 were complements and 10 had another mismatch. The complements were punts or a punt with a running-into-the-kicker penalty; the other mismatches were seven timeouts, two two-minute warnings, and one pass reception. Per-game counts and the join rule are recorded in the manifest. This is a bounded historical sample, not a live accuracy rate. It rules out blindly treating every ESPN `yardsToEndzone` as an offense-relative field coordinate. Preserve raw values, and leave a spot transition unavailable unless its event-class mapping is verified.

## App route finding

The existing [NFL PBP handler](../../backend/routers/games/game_detail.py) reads `summary.get("plays")`. That does not match the captured NFL summary shape, so it returns `available:false` even when ESPN supplied hundreds of plays. The app's game-info route returned ESPN venue/official data for a captured historical event, and the configured client fetched all eight summaries. This is an adapter-shape bug; the earlier conclusion that the raw summary path had not been verified is superseded.

The scoreboard adapter in [`scoreboard.py`](../../backend/espn_client/scoreboard.py) maps a football `situation`, but the scheduled Nov. 1 snapshots contained no live situation. Historical summary fields alone do not prove how this live state behaves. Before rendering a field position, the visual mapping from ESPN's raw team/yard-line fields to the room's attacking direction still needs live and boundary validation.

## Freshness, revisions, and retained app data

Historical plays carry `wallclock` on 1,459/1,464 records, `modified` on all 1,464, and the summary carries `meta.firstPlayWallClock`, `meta.lastPlayWallClock`, and `meta.lastUpdatedAt`. This is publisher-provided historical timing evidence. It does not measure LP first-seen latency. The retained `scoreboard_snapshots` store upserts one current row per game; it does not retain a play observation/revision sequence. Distinct IDs were confirmed within each captured game, but duplicate delivery and post-publication correction behavior require repeated captures. No review/correction rate can be inferred from this single historical snapshot per game.

## R0 coverage matrix

| Requirement | Evidence | Result |
|---|---|---|
| Sunday slate and live situation | 12 scheduled games at 06:55 UTC; no live game | Partial; live sample outstanding |
| 5–10 historical ESPN games | 8 decoded summary fixtures; TDs, tries, turnovers, reviews, FGs represented | Met for historical source coverage |
| Stable IDs and duplicate/revision behavior | 1,464 distinct IDs within one capture per game | IDs observed; duplicate/revision behavior unverified |
| Possession, spot, down/distance, type, score, period/clock | Historical fields observed; independent spot join: 956/988 exact, 22 complements, 10 other mismatches | Partial; source field mapping must fail closed by event class |
| Publisher-to-LP latency | Publisher wallclock and capture timestamps exist, but no per-play first-seen history | Not measurable yet |
| Review/correction rate and score reconciliation | Structured reviews observed; all 8 final scores reconcile; no repeated captures | Score check passed; correction rate unmeasured |

## Gate decision

R0 remains open. The configured ESPN API is working, and the historical summaries establish most needed fields, but the spot cross-check found event classes that cannot use a direct `yardsToEndzone` mapping. Do not call the channel live, animate unverified transitions, or infer a separate try play from touchdown prose. To close R0, capture the live Sunday slate and repeated samples through the existing ESPN-backed path, recording exact publisher IDs, raw situation/spot fields, LP first-seen times, score changes, and revisions/corrections. Validate the field mapping per event class and keep unknown spots null before building field animation.
