# Proposal: Narrative Event Knowledge for Pregame Summaries

**Date:** 2026-10-31
**Scope:** Research only on `dev`; no production changes.

I reviewed the current development branch of Legendary Picks and think this could substantially improve our pregame summaries.

The central discovery is that ESPN and NBA.com often publish Associated Press reporting. That may give us a common source of game recaps across both leagues, instead of requiring an entirely different collection strategy for each sport.

We should use those articles to learn what makes a game important and how journalists explain it, rather than training a model simply to imitate their writing.

## 1. What Legendary Picks currently does

| File | Current responsibility |
| --- | --- |
| `core_stories.py` | Generates pregame previews and postgame recaps using DeepSeek |
| `stakes.py` | Determines playoff, division, and standings implications |
| `player_form.py` | Supplies recent player performance from game logs |
| `matchup_context.py` | Adds recent results, leaders, and competition context |
| `pregenerate_game_stories.py` | Pre-generates upcoming previews and finished-game recaps |
| `ingest_league_news/fetch.py` | Collects ESPN article headlines, descriptions, and some full article text |

The current generator prioritizes stakes, hot and cold streaks, then records. It asks DeepSeek for one to four sentences.

The problem is that it writes predominantly from aggregated numbers. For example, it might say Detroit has won two straight games. With event-level context, it could instead explain that Detroit survived a failed fourth-down gamble and won on a last-second field goal, while its next opponent has been relying heavily on its defense.

There are also three architectural issues to address:

- `game_story` has one row per game, so a recap can replace the original pregame preview instead of preserving both.
- The generation pipeline does not systematically extract decisive drives, blown leads, strategic adjustments, and turning points.
- Historical replay needs stricter as-of filters. Current form retrieval is not designed as a fully cutoff-safe historical training feature builder.

An earlier repository audit also found 156 NFL story records with `has_stakes=0`. That does not mean the NFL stakes engine is absent, but it shows how little useful stakes context was reaching those stories at the time of that audit.

## 2. What I found about the articles

### NFL: AP recaps through ESPN and other publishers

The October 25, 2026 Lions–Packers recap explains Detroit’s last-second victory, Campbell’s unsuccessful fourth-down gamble, Green Bay’s missed field goals, and the game’s playoff context. It is credited to AP (ESPN 690 +1).

### NBA: NBA.com game-summary pages

The October 30, 2026 Warriors–Lakers page includes a full AP-written game recap along with box scores, lead changes, scoring, and other game data. That is more valuable than the separate NBA.com video recap collection (NBA.com +1).

There is an additional wrinkle: some AP NBA recaps explicitly disclose that the story was created using Data Skrive technology and Sportradar data (ESPN). This gives us three kinds of material to label separately when evaluating the corpus:

1. Human reporting.
2. Computer-assisted writing.
3. Standardized game data.

For sourcing, prioritize AP-origin recaps, use ESPN to discover NFL game articles, NBA.com game-summary pages to discover NBA articles, and NFL.com’s *What We Learned* series as a second source for football analysis. NFL.com publishes substantial postgame takeaways even though its layout differs from a traditional wire recap.

Coverage rates across complete seasons have not been verified, so we should not assume every game has an article.

## 3. What we should learn from those articles

Consider the Lions–Packers example. The article identifies the missed field goals and fourth-down decisions as central to the game’s story. Those facts are more useful than simply knowing Detroit won 20–17.

We can turn that editorial judgment into structured labels:

### Example: postgame knowledge record

**Green Bay at Detroit · October 25, 2026**

- **Outcome:** Detroit 20, Green Bay 17
- **Decisive event:** Game-winning field goal
- **Strategic themes:** Fourth-down decisions, clock management
- **Performance themes:** Missed kicks, penalties, turnovers

These are article-derived candidate labels. Reconcile individual events and claims against game data before adding them to the verified knowledge store.

The resulting feedback loop would be:

1. **Historical games:** Final stats, play-by-play, standings, and player workloads.
2. **Recap interpretation:** Which events did journalists emphasize, and why?
3. **Verified narrative event database:** Turning points, streaks, records, injuries, and tactical themes.
4. **Pregame context ranking:** Rank only events known before the upcoming game’s cutoff.
5. **Legendary Picks pregame summary:** Write grounded text with supporting evidence attached.

The NFL simulation and play-by-play work already underway can make this especially useful. Rather than asking a model to decide whether a game featured a comeback, we can calculate the deficit, lead changes, possession sequence, fourth-down conversions, and winning drive ourselves.

The article tells us which events deserved attention. Our data establishes what actually happened. This distinction matters because postgame commentary can include subjective interpretations and mistakes.

## 4. Deterministic first, trained model second

Build a deterministic fact and event extraction system first, then train a small ranking model when we have enough labels.

| Narrative category | How Legendary Picks can calculate it |
| --- | --- |
| Comeback | Largest deficit overcome, lead changes, final result |
| Close-game execution | Fourth-quarter drives, turnovers, late scoring |
| Offensive dominance | EPA/play, success rate, explosive plays, scoring drives |
| Defensive dominance | Points allowed, sacks, pressure, takeaways, drive success |
| Player breakout | Performance relative to earlier games and a role-adjusted baseline |
| Momentum | Recent outcomes and changes in opponent-adjusted efficiency |
| Rivalry or rematch | Prior meetings, division and conference relationships |
| Stakes | Verified clinching scenarios, playoff positioning, elimination |

The eventual trained model should answer: **Which three to five available facts best explain this upcoming matchup?** It should not predict the winner or generate raw facts, and it must not use postgame outcomes as inputs to earlier pregame predictions.

This keeps predictive modeling separate from editorial storytelling.

## 5. The source-rights issue matters

AP’s licensing offering is relevant because it explicitly markets structured news data for AI models, including historical data and retrieval applications (Associated Press).

Publicly readable articles are not automatically licensed for bulk collection, model training, or commercial reuse. NBA.com’s terms also impose restrictive conditions around its content and statistics, especially for commercial fantasy and betting-related uses (NBA.com).

For Legendary Picks, start with an article discovery and coverage audit, retain publisher metadata and links, and produce our own verified event labels from game data. Full-text corpus training should follow a rights review or appropriate license.

## 6. Proposed next work for the coding agent

Keep the initial task research-only on `dev`, with no production changes.

1. **Audit existing story and news infrastructure.** Inventory `game_story`, `news_items`, the ESPN collector, and existing NFL/NBA data tables. Determine what is already stored and which historical previews were overwritten.
2. **Measure recap availability.** Match a representative four-week NFL sample and at least 100 NBA games to ESPN, NBA.com, AP, and NFL.com article metadata. Report game coverage, publication delay, publisher, byline, duplicates, and unavailable records. Do not ingest article bodies without approved rights.
3. **Build a narrative-event prototype.** For 50 NFL and 50 NBA games, derive comeback magnitude, scoring runs, clutch events, player outliers, decisive drives, and standings consequences from existing game data. Separately annotate article-emphasized themes where permitted, then measure how often our event detector identifies them.
4. **Build a pregame context retriever.** Given a future game and an as-of timestamp, retrieve the most relevant recent verified events for each team and its available players. Store every supporting game ID, event ID, timestamp, and calculation.
5. **Run a blind comparison.** Generate the existing DeepSeek preview alongside a deterministic-event version and an LLM-written version grounded in the same event facts. Compare specificity, factual errors, repeated information, relevance, and leakage. Preserve previews and recaps separately instead of overwriting them.

### Release gates

- Zero known future-information leakage.
- No unsupported numerical claims.
- Reproducible event extraction.
- Measurable improvement over existing previews on a held-out sample.

## Longer-term opportunity

This would improve more than the text on Legendary Picks. The same event knowledge could eventually explain simulations, support smarter player and team research, and power a sports-data MCP service.

We already have a substantial historical NFL play-by-play foundation. The missing layer is converting those events into a searchable understanding of what happened, what mattered, and what could matter in the next game.

Prioritize building that layer before spending money fine-tuning a writing model.
