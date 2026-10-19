# swcrockett weekly import: availability and first capture

Checked 2026-10-19. Research only; no model, gate, serving, or production changes.

## Availability audit

The public [swcrockett NFL win-probability repository](https://github.com/swcrockett/nfl-win-probability-model) stores weekly predictions as CSVs under `outputs/predictions/`. A direct unauthenticated fetch of the repository tree listed 2026 Weeks 1–6. The newest listed file was Week 6. Its CSV contains `season`, `week`, `gameday`, `game_id`, away/home team codes, both win probabilities, predicted winner, and confidence. It contains the game date, but **not a kickoff time**. No authentication, paywall, or JavaScript challenge blocked access.

Every successful direct source fetch made for this audit or capture is recorded here. Hashes are over the exact response body bytes.

| Artifact | HTTP | Retrieved at (UTC) | Bytes | Raw SHA-256 |
|---|---:|---|---:|---|
| [Repository tree API](https://api.github.com/repos/swcrockett/nfl-win-probability-model/git/trees/main?recursive=1) | 200 | 2026-10-19T19:03:17.131844Z | 10,947 | `69957e770152be8e3fb4e9c36f446d48cc403f658413bf618b95035e7763a5f4` |
| [README](https://raw.githubusercontent.com/swcrockett/nfl-win-probability-model/main/README.md) | 200 | 2026-10-19T19:03:33.254317Z | 24,093 | `845545e3715c2f1a8993500c13062fe24091d4250476cb04fb4416f2a78a01b9` |
| [LICENSE](https://raw.githubusercontent.com/swcrockett/nfl-win-probability-model/main/LICENSE) | 200 | 2026-10-19T19:03:33.381863Z | 1,072 | `825f7f25233a8d550d5c51aa36ea1e329476d3de3a5ce4042796a6cf9033c8d` |
| [2026 Week 6 predictions, audit fetch](https://raw.githubusercontent.com/swcrockett/nfl-win-probability-model/main/outputs/predictions/2026_week_06.csv) | 200 | 2026-10-19T19:03:33.506458Z | 1,545 | `54e523d5d5ad6e035dfed082367adf3d7652d4303b27bbb0f52492a0e9034149` |
| [2026 Week 6 predictions, captured artifact](https://raw.githubusercontent.com/swcrockett/nfl-win-probability-model/main/outputs/predictions/2026_week_06.csv) | 200 | 2026-10-19T19:08:10.249057Z | 1,545 | `54e523d5d5ad6e035dfed082367adf3d7652d4303b27bbb0f52492a0e9034149` |
| [2026 Week 7 expected path](https://raw.githubusercontent.com/swcrockett/nfl-win-probability-model/main/outputs/predictions/2026_week_07.csv) | 404 | 2026-10-19T19:04:11.500293Z | 14-byte error body | — |
| [nflverse schedule, audit fetch](https://github.com/nflverse/nfldata/raw/master/data/games.csv) | 200 | 2026-10-19T19:06:07.225663Z | 2,185,300 | `75ebd10c9a11e86ffa81548a45de052027e7dce8ccc4bf2b2c7fe58f5c11930e` |
| [nflverse schedule, captured artifact](https://github.com/nflverse/nfldata/raw/master/data/games.csv) | 200 | 2026-10-19T19:08:10.830863Z | 2,185,300 | `75ebd10c9a11e86ffa81548a45de052027e7dce8ccc4bf2b2c7fe58f5c11930e` |

The included repository `LICENSE` is MIT, copyright Samuel Crockett (2026). I found no separate forecast/data license or source-specific terms-of-service statement in the fetched README or LICENSE. The CSV contains no market odds, quotes, or prices.

Because the forecast CSV gives only `gameday`, the importer resolves the exact kickoff by its published `game_id` against the public [nflverse games schedule](https://github.com/nflverse/nfldata/raw/master/data/games.csv). This supplies schedule metadata only; all imported probabilities come directly from swcrockett's CSV. Its row for `2026_06_WAS_SF` lists a 2026-10-19 20:15 America/New_York kickoff (`2026-10-20T00:15:00Z`).

## Importer and capture

[`backend/swcrockett_import.py`](../../backend/swcrockett_import.py) fetches one requested weekly CSV and the schedule, checks the source schema and game identity, normalizes team codes to this repo's ESPN vocabulary, and writes `research/swcrockett/<season>-w<week>.json`. Each game carries its source URL, fetch timestamp, season/week, UTC kickoff, teams, home-win probability, raw prediction-payload SHA-256, and `post_kickoff`. It refuses duplicate IDs or matchups, unknown teams, a mismatched schedule row, absent kickoff, and probabilities outside `(0,1)` or not summing to one. Captures at an existing path are immutable; a conflicting rerun fails instead of replacing them.

The first capture is [`research/swcrockett/2026-w6.json`](../swcrockett/2026-w6.json): 14 games, 13 marked `post_kickoff: true`, and one still pre-kickoff when fetched. The fetched raw prediction payload hash matches both direct audit fetches above.

## Matched-game comparison

[`backend/compare_swcrockett.py`](../../backend/compare_swcrockett.py) reads only the dev database in SQLite read-only/query-only mode. It pairs a captured forecast with the latest locked base `nfl-v1` probability recorded no later than kickoff, uses the matching schedule score, drops post-kickoff captures, and reports Brier, log loss, and paired differences as swcrockett minus v1. The interval routine uses 2,000 week-block bootstrap replicates, seed `20261019`, block `(season, Monday-of-week UTC)`, and game-count weighting.

For this capture the source population is 14 games:

- 13 are excluded as post-kickoff at our fetch time. Although the dev schedule has final scores for those 13, the current import is not a prospective capture for them.
- The one pre-kickoff game, Washington at San Francisco, had neither a final score nor a locked incumbent v1 row at capture time. It is excluded for both reasons.
- Duplicate games: 0. Unmapped team codes: 0. Ties among the 13 completed games: 0.
- Eligible matched, graded games: **0**. Brier and log loss are not computable; there are no paired per-game differences, bootstrap blocks, or intervals. This sample says nothing about relative model quality.

The publisher's file has no market prices, and no market probability is inferred from it. The market and the benchmark ladder remain the evaluation references; this comparison makes no adoption or superiority claim.

## Reproduction

Run the comparator against the committed capture and the read-only dev database:

```bash
python3 backend/compare_swcrockett.py research/swcrockett/2026-w6.json \
  --db /root/legendarypicks/backend/data/picks.dev.db
```

To capture a future week before kickoff (on a clean output path):

```bash
python3 backend/swcrockett_import.py --season 2026 --week 7
```

At audit time that Week 7 URL returned HTTP 404, and the importer exited 2 without creating an output. The committed Week 6 JSON is the reproducible record of the source bytes and fetch time used here; fetching `main` again creates a new timestamped capture.
