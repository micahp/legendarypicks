# Narrative event knowledge: research audit

**Captured:** 2026-10-31T21:57:41Z
**Mode:** research only; no application database writes; publisher bodies and play descriptions were not retained.

## Samples

- NFL event sample: 50 completed regular-season games, weeks 4–7, stratified 13/13/12/12.
- NBA event sample: 50 completed regular-season games from the 2025–26 season, selected as an even subset of the article sample.
- NBA article sample: 100 completed regular-season games, selected evenly across the 1,230-game 2025–26 regular-season data population; the 50-game event sample is nested inside it.

## Current storage and collector audit

- `game_story` has a `(league, game_id)` key and no story-kind/version column. The generator deletes and replaces that row, so a stored postgame row cannot recover an earlier preview. When a current row exists, its saved text is only one version; the database cannot tell whether a preview was ever generated before the recap.
- Sampled current story rows: NFL 50/50; NBA 0/50. Historical overwritten-preview count is not observable from this schema.
- Existing ESPN-tagged `news_items` metadata: NFL 1956 rows / 1956 URLs; NBA 778 rows / 778 URLs. The collector has headline, URL, publisher and published time columns; body/description was excluded from this audit query.
- The existing ESPN collector stores short descriptions in `news_items.body` and an optional story fetcher stores full ESPN story text. This prototype reads no `body` column and does not call the full-story collector.

## Article coverage in this sample

- NBA.com game pages with recap header metadata: 100/100; pages with AP origin explicitly identified in byline/credit metadata: 0/100.
- ESPN per-game NFL summaries with article headline metadata: 50/50; articles with AP origin explicitly identified by source/byline metadata: 50/50.
- NFL.com *What We Learned* weekly pages found: 4/4 sampled week pages. These are week-level packages, not one independent article per game.
- Duplicate audit: 0 duplicate copies in 0 duplicate normalized headline/date groups among 150 records with both fields; 0 exact-URL duplicate copies in 0 groups. Mirrored articles can still use distinct URLs.
- Headline labels are candidate labels only. This audit did not read or store article descriptions or article bodies; it therefore cannot claim coverage of themes that appear only inside the story.
- Headline/event detector: 23/48 headline-derived candidate labels were represented by a corresponding structured event category (23 articles had at least one detected candidate). This measures headline agreement only; it is not a journalist-theme recall estimate.
- Publication delay is unavailable: the available game-clock timestamps are estimates, not measured final-whistle times.

## Local database source audit

- The event extractor opens the supplied Legendary Picks development database in SQLite `mode=ro` with `PRAGMA query_only=ON`. Event statistics come from local tables; this invocation made zero external game-statistics requests.
- NFL `nfl_pbp`: 756,043 plays across 4,283 games, 2010-09-09–2026-10-29. `drive`, `series_result`, `down`, turnover and touchdown fields are present; per-play capture timestamps and score snapshots are missing.
- NFL supporting data: `team_game_results` 9,270 rows, player game logs 294,359 rows (294,264 with player IDs and 294,359 with stats JSON), and `nfl_snap_counts` 60,647 rows across seasons 2024–2026. Snap counts have no game ID or capture timestamp and join through the existing season/week/team schedule identity. The DB has no separate drive-named table; drive terminals are reconstructed from `nfl_pbp.drive` and `series_result`.
- NBA full play-by-play table: none found. `scoring_plays` has 2,490 rows for 5 games, captured 2026-06-09T18:10:34.772805+00:00–2026-06-29T19:36:32.666829+00:00; it omits non-scoring possessions and defensive sequence data. The 50-game event sample had local scoring plays for 0 games.
- NBA box-score coverage: `team_game_stats` has 2,466 rows across 1,233 games with actual `captured_at` timestamps; populated rows: turnovers 2,462, rebounds 2,462, assists 2,462, steals 2,462, blocks 2,462. Missing values: fouls on 0/2,466 rows; FG%, 3P% and FT% on 0, 0 and 0; `largest_lead` on 0 and `lead_changes` on 0. The 50-game sample matched 100 team rows.
- Player game logs have `ingested_at` but no source capture timestamp: NFL 294,264/294,359 rows have a player ID and NBA 34,792/34,792. They use canonical game dates and a conservative next-day boundary; ingestion time is not treated as historical availability. NFL PBP also uses that game-date boundary. NBA team box snapshots instead use their actual `captured_at`.

## Deterministic local event prototype

- Local extraction status: NFL 50/50 sample games processed from `nfl_pbp`; NBA 50/50 games produced team-box facts. NBA team-box facts are not full play-by-play.
- NFL reconstructed scoring totals matched `nfl_schedule` for 49/50 sampled games. Scoring facts are withheld on a mismatch; drive, turnover, fourth-down and snap summaries retain their own evidence IDs.
- NFL `team_game_results` score reconciliation was available for 0/50 sampled games; 0 matched and 0 differed. The remaining games had no complete two-team results pair for the sample's ESPN IDs. Of 0 team turnover snapshot comparisons available in the sample, 0 matched and 0 differed. Drive and fourth-down summaries are derived from local play fields; no independent local result table was available to reconcile those categories.
- `nfl_pbp` has no per-play score snapshots, so this iteration emits no NFL comeback, lead-change, or clutch-outcome claims. NBA has no local full play sequence, and its team-game snapshots contain no `largest_lead` or `lead_changes` values; those event categories remain unavailable locally.
- The five prior NBA timeline failures (401810016, 401810188, 401810257, 401809242, 401810585) are absent from local play-level storage. The old checkpoint kept only `NarrativeDataError`, not a message or failed timeline, so its exact failure class cannot be reproduced from this DB/artifact. No validation threshold was weakened.
- Event fact counts: nba player_outlier=288, nba standings_record=100, nba team_box_summary=100, nfl drive_summary=100, nfl fourth_down_attempts=79, nfl player_outlier=206, nfl scoring_summary=98, nfl snap_workload=1107, nfl standings_record=100, nfl turnover_events=38.
- Backfilled game facts use canonical database game IDs and dated source-game references. Neutral events list both participants. The renderer says a team took the lead; it never says that a particular play won the game.

## Pregame retrieval and story comparison

- The retriever rejects an `as_of` time after kickoff, requires `occurred_at < target_start`, `available_at <= as_of`, a verified fact with supporting game/event IDs, and team/player relevance, and excludes the target game's canonical local ID.
- The comparison includes deterministic event-only and deterministic combined-facts candidates. Both use the same matchup, cutoff, and complete authorized evidence packet; the combined candidate can use standings and player-form facts alongside event facts.
- Existing cached previews have no persisted source manifest. They are retained as story versions but excluded from numerical evidence scoring and the blinded candidate set until their authorized evidence can be reconstructed.
- LLM status: 0 previously generated grounded previews reused; new model calls=0.
- Blinded candidate coverage prepared for human rating: nba 60 paired targets, nfl 51 paired targets. `blind_evidence.jsonl` supplies each pair the same evidence and cutoff. The ID-to-generator key is kept outside this review packet; do not give it to raters. No human ratings have been entered.
- Numeric evidence gate (preview-level): deterministic_combined 1/120 previews contained a number absent from the supplied event calculations; deterministic_event 0/111 previews contained a number absent from the supplied event calculations.
- Numeric-token overlap is only a mechanical screen, not claim verification. It is not used to grade existing previews whose full evidence set is unknown. Relevance, factual accuracy, specificity, and readability still require blinded human ratings; no improvement claim is made.

## Rights and limits

- AP says its structured news-data products cover AI training, retrieval and archive use. Public readability alone is not a bulk-training license; the corpus here retains metadata and links only. See [AP AI, tech and data](https://www.ap.org/who-we-serve/ai-tech-and-data/) and [AP source data](https://www.ap.org/intelligence/our-offerings/source-data/).
- NBA.com terms restrict commercial use of stats and prohibit certain fantasy/gambling uses without consent. These research outputs are not wired into the product; obtain rights review before bulk reuse. See [NBA.com Terms of Use](https://www.nba.com/termsofuse).
- The 100-game NBA article sample is systematic across one completed regular season, not a random sample. NFL covers four selected weeks, not a full season. Not-found pages mean unavailable at the requested page/endpoint during this run, not that the publisher has no article.

## Network request count

- No publisher requests were made in this iteration; saved article-metadata checkpoints were read (site.api.espn.com 50 rows, www.nba.com 100 rows, www.nfl.com 4 rows).

See `sample_manifest.json`, `local_database_coverage.json`, `publisher_metadata.jsonl`, `event_records.jsonl`, `blind_review_packet.zip`, and the other JSONL/CSV audit artifacts in this directory.
