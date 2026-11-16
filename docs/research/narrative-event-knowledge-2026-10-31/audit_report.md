# Narrative event knowledge: research audit

**Captured:** 2026-10-31T19:41:52Z
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
- Headline/event detector: 14/45 headline-derived candidate labels were represented by a corresponding structured event category (13 articles had at least one detected candidate). This measures headline agreement only; it is not a journalist-theme recall estimate.
- Publication delay is unavailable: the available game-clock timestamps are estimates, not measured final-whistle times.

## Deterministic event prototype

- PBP collection status: summary_endpoint_checkpoint_after_prior_core_403. The earlier ESPN Core sample was stopped after a 403; this resumed run did not retry that host.
- Validated timelines: NFL scoring-play timelines 50/50; NBA full-play timelines 45/50.
- Event timestamps are estimates from scheduled kickoff plus period clock. They order plays reproducibly but do not establish an observed final-whistle time.
- The event validator requires unique play IDs, timezone-aware event timestamps, nondecreasing scores, and a terminal score matching the repository schedule; games failing any check are excluded from verified facts.
- Categories are calculated from structured score snapshots: comeback magnitude, non-tied lead changes, scoring runs, late scoring events, and decisive lead changes. NFL summary data contains scoring plays only, so drive, turnover, and fourth-down facts are not inferred. NBA summary data provides full play rows; only event flags present in that source are used.
- Player outliers use canonical `player_id` and prior logs whose ingestion timestamp is at or before the sample game's first play. The baseline is per-player and game-type, requires five prior available games, and is not role-adjusted. Incomplete availability timestamps are omitted.
- Event fact counts: nba clutch_events=45, nba comeback=35, nba decisive_score=35, nba lead_changes=35, nba scoring_run=45, nba standings_record=90, nfl clutch_events=37, nfl comeback=34, nfl decisive_score=34, nfl lead_changes=34, nfl scoring_run=50.
- Standings facts state only win/loss/tie records. Same-calendar-day prior games are excluded because exact order is not available in every local schedule source; no playoff-clinching or rank claims are inferred.

## Pregame retrieval and story comparison

- The retriever requires `occurred_at < target_start`, `available_at <= as_of`, a verified fact with supporting game/event IDs, and team/player relevance. It excludes the target game and uses a stable category/recency order.
- The artifact writes separate `story_kind` values for existing pregame previews, deterministic event previews, and any grounded model versions; it does not write to `game_story`.
- LLM status: 2 previously generated grounded previews reused; new model calls=0.
- Blind target coverage: paired targets nfl 12; single-variant targets nba 9. NBA upcoming rows lack an ESPN event-ID crosswalk, so an existing NBA preview could not be joined.
- Numeric evidence gate (preview-level): deterministic_event 0/21 previews contained a number absent from the supplied event calculations; existing_preview 12/12 previews contained a number absent from the supplied event calculations; llm_grounded 0/2 previews contained a number absent from the supplied event calculations.
- Blind comparison measurements are mechanical: held-out targets, evidence IDs, numerical claims, repeated wording, and cutoff leakage. Semantic relevance and whether a phrase is readable still require an actual blinded reviewer; no improvement claim is made without those ratings.

## Rights and limits

- AP says its structured news-data products cover AI training, retrieval and archive use. Public readability alone is not a bulk-training license; the corpus here retains metadata and links only. See [AP AI, tech and data](https://www.ap.org/who-we-serve/ai-tech-and-data/) and [AP source data](https://www.ap.org/intelligence/our-offerings/source-data/).
- NBA.com terms restrict commercial use of stats and prohibit certain fantasy/gambling uses without consent. These research outputs are not wired into the product; obtain rights review before bulk reuse. See [NBA.com Terms of Use](https://www.nba.com/termsofuse).
- The 100-game NBA article sample is systematic across one completed regular season, not a random sample. NFL covers four selected weeks, not a full season. Not-found pages mean unavailable at the requested page/endpoint during this run, not that the publisher has no article.

## Network request count

- `site.api.espn.com`: 150 requests.
- `www.nba.com`: 100 requests.
- `www.nfl.com`: 4 requests.
- All logged collection attempts, including the failed first pass and metadata re-fetch: 536 requests (cdn.nba.com 1, site.api.espn.com 257, sports.core.api.espn.com 70, www.nba.com 200, www.nfl.com 8). See `network-spend.jsonl` for HTTP statuses.

See `sample_manifest.json`, `publisher_metadata.jsonl`, `event_records.jsonl`, `blind_comparison.jsonl`, and `blind_key.json` for the allowlisted audit records.
