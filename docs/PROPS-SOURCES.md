# Props: where every line comes from

Written 2026-09-05 after a day in which three separate lanes turned out to be
silently dead. Read this before adding a provider, because the lesson of that
day is that **we did not have an access problem, we had three bugs**, and the
instinct to go find a new source was wrong every time.

## The providers, and what each is actually for

| provider | how we reach it | prices | odds? |
|---|---|---|---|
| **Bovada** | direct HTTP from this box | goals, assists, first goal scorer, goal+assist; tennis match markets; MLB/NFL/NBA/NHL | **yes, 100%** |
| **RotoWire relay** | direct HTTP from this box | 7 of the soccer eleven: shots, SOT, passes attempted, saves, clearances, tackles, crosses | **yes, 100%** |
| **PrizePicks direct** | browser on a residential IP, saved to a file | all 11 soccer markets, including the two nothing else has | **NO — 0%** |

### The odds column is the one that decides things

`props` rows carry an `odds` column and a prop with no price is not a bet.
Measured 2026-09-05:

```
mls   bovada                2200   100% priced
mls   rotowire:prizepicks   1022   100% priced
lcup  prizepicks-demon      1334     0% priced
lcup  prizepicks-goblin      198     0% priced
lcup  prizepicks              11     0% priced
```

PrizePicks is a pick'em product. `demon` and `goblin` are payout multipliers,
not prices, and they are carried in `source` rather than flattened because a
demon read as a plain over/under is a different bet than the book is taking.
So PrizePicks fills market coverage and **cannot** fill the odds requirement.

## The eleven soccer markets

The list this league is built for: shots, shots on target, passes attempted,
goals, goalie saves, clearances, assists, attempted dribbles, tackles, crosses,
fouls. Note the stored vocabulary is `dribbles` and `fouls_committed`, not
`attempted_dribbles` and `fouls` — querying the wrong key returns 0 and looks
like a coverage gap.

Where they come from, after 2026-09-05:

```
goals, assists            bovada          priced
shots, SOT, passes,       rotowire        priced
saves, clearances,
crosses, tackles
dribbles, fouls_committed prizepicks only UNPRICED, and only via a browser pull
```

## Access: what is actually blocked

- **Bovada does not block us.** 3,147 MLS props came off this datacenter IP on
  2026-09-05.
- **RotoWire does not block us.** It relays PrizePicks as a book, but it is a
  *curated subset*: zero Leagues Cup and zero Liga MX across eight archived
  days. A relay's book list is a claim about the relay, not about the book.
- **PrizePicks blocks everything scripted.** 403 across api, partner-api, app
  and www from this box, and 403 from a verified residential IP (Charter,
  Austin) using curl with matching headers. It is not an IP-range block. A
  logged-in browser is served; `urllib` and `curl` are not. So
  `backend/tools/pull_prizepicks.py` no longer works as written, and the only
  method known to succeed is a human opening
  `https://api.prizepicks.com/projections?league_id=82` and saving the JSON.
  That produced 1,722 props across 12 markets on 2026-08-25.

Drop location for that file: `data/prizepicks_drop/<YYYY-MM-DD>/`, then
`python3 backend/ingest_prizepicks_props.py <path>`.

## The bug class that hid all of this

**A short list is a perfectly plausible list.** Every failure below returned
HTTP 200 and a well-formed response, so nothing raised and every instrument
read healthy.

1. **The bare Bovada coupon path truncates.** Any query parameter defeats it.
   Same minute, 2026-09-05: `soccer/.../mls` bare 0 events, `lang=en` 15;
   `baseball/mlb` bare 15 events, with a param 27. So MLS read as "Bovada does
   not carry this league" and MLB was ingesting about half its fixtures.

   Use `lang=en`. **Do not use `marketFilterId=def`** — it is Bovada's default
   market *filter* and returns Game Lines only, stripping every player prop.

2. **Bovada files tennis under the tournament, not the tour.** `tennis/atp` and
   `tennis/wta` return 200 with zero events. The lane died 2026-08-29, mid US
   Open, while we were trading it. Correct path is
   `tennis/us-open/men-s-singles`. These slugs are tournament-specific and go
   stale when the Slam ends.

3. **The adaptive backoff amplified both.** It counts empty runs and rests a
   league after three. Those truncated runs looked empty, so it slept the
   leagues: atp 29 empty runs, wc 63, wta 28, lcup 12, nfl 4 with the season
   opening that week. Even after the truncation was fixed the leagues stayed
   asleep. **A backoff that cannot distinguish "the publisher has nothing" from
   "we asked wrong" will re-suppress every lane we fix.** State lives in
   `backend/data/bovada-league-backoff.json`.

## Environment: which server, which database

`bovada_scraper` POSTs to `$LP_API_BASE/api/props/ingest` and its default,
`http://localhost:8000`, is wrong for both environments — nothing listens there.

```
:8096   dev    /root/legendarypicks/backend/data/picks.dev.db
:8100   PROD   container, /app/data/picks.db
:8097          /root/lp-sport-first-nav worktree, stale since 2026-08-28
```

Always identify a server by `db_path` and freshness from `/api/health`, never by
port folklore. Ingest with an explicit base:

```bash
LP_API_BASE=http://127.0.0.1:8096 python3 -m bovada_scraper mls --ingest   # dev
LP_API_BASE=http://127.0.0.1:8100 python3 -m bovada_scraper mls --ingest   # prod
```

## Open, and worth doing next

**Tennis player props are scraped but not parsed.** The US Open coupon carries
Player Props, Service Game Props, Break Props, Ace/Double Fault Props, Set Props
and Match Props. We ingest only `match_winner`, `total_games` and `win_a_set`.
Service Game and Break props are exactly the hold-and-break data the tennis
reprice work needs, and they are sitting in a payload we already fetch.

**The tennis path needs to walk the tree.** Matching on tournament name rather
than guessing slugs, the same technique that found the Leagues Cup path.

**Bovada's `/sports/player-props` builder is login-gated** and untested. Same
shape as the PrizePicks problem: a logged-in browser may be served markets an
anonymous request is not. Unknown whether it exposes anything beyond the twelve
markets we now get.

**MLB and the other leagues have not been re-measured** since the truncation fix.
MLB was ingesting ~15 of 27 fixtures; nobody has checked what the other leagues
were missing.
