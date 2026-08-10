# News discovery — teaching the engine to find the signal

**Status:** built and running on dev — 2026-08-10 (news is dev-only).
**Scope:** `backend/discover_topics.py`, `news_conversations` +
`news_topic_candidates` in `_core.py`, `ingest_league_news.load_conversations()`.
**Parents:** `PLAN-league-news-engine.md` (the engine), `NEWS-FEEDBACK.md` (the
card feedback loop this mirrors), `NEWS-AUDIT-2026-08-09.md` (gap #2).

## 1. What a seed was, and why that wasn't enough

A seed was a **search string**. `{"seed": "dodgers salary cap"}` went into a
Bluesky search, matching posts got tagged, and the tagged posts became a card.
Nothing was learned, nothing was scored, nothing carried between runs.

The consequence, stated plainly: **the engine could only report on conversations
a human had already named.** `nba-kawhi-cap` exists because a person read the
feed, noticed the Pablo Torre story recurring, and typed an entry by hand. Micah,
2026-08-10:

> i don't just want these to be in the conversation i want it to be training
> data for it to get better at finding the signal

The card feedback loop already learns — but only *how a card is framed*, never
*which conversations exist*. Discovery is the missing half.

## 2. The two stages

**Stage 1 — cheap, deterministic, inspectable.** Cluster the last 10 days of
`news_items` and score each cluster on the properties Micah's own topics share:

| Property | Why it is in the score |
|---|---|
| Recurs over several **days** | A one-day spike is a result, not a conversation |
| Several **independent outlets** | One outlet talking to itself is not a conversation (`espn-nfl` and `espn-mlb` count as one) |
| Social chatter and articles **converge** | People arguing about the same thing that got reported is the strongest signal there is |
| There is a **stake** | Money, rules, power, a fight — not a scoreline |

Stake and convergence dominate the score; recurrence only breaks ties. Each of
the gates below was added because the pass surfaced junk without it — all
measured on the real corpus the same day:

- **Two-word entities only.** Single capitalized tokens are first names and
  sentence openers; `larry`, `mike`, `red`, `blue`, `all`, `after` filled the
  entire top 14.
- **Team names are containers.** `brewers` recurs every day across every outlet
  and says nothing. The exclusion list is the classifier's own `LEAGUE_TERMS` —
  we did not write a second list of team names.
- **The stake must be in the headlines, in more than one of them.** Scanning
  each cluster's full text let ambient chatter satisfy it: any cluster of 30
  MLB items contains "salary cap" *somewhere*, so every club looked like a cap
  conversation.
- **A stake term inside the cluster key is not a stake.** "chris sale" is a
  pitcher, not a franchise sale.
- **Stake phrases cluster too.** Not every conversation is named after a person
  or a club — "media rights", "promotion and relegation", "expansion" are the
  shape Micah's topics take, and entity clustering alone can never form them.
- **Already-covered topics are dropped** on two shared significant words. One
  shared word was too aggressive (seeds are full of generic terms like "cap"),
  substring matching was too weak (`the dodgers` never matched the seed
  `dodgers salary cap`, so the pass proposed a topic we already serve).

**Stage 2 — judged against the labels.** Survivors go to DeepSeek in one call
with the **approved conversations as positive exemplars** and the **rejected
candidates as negative ones**. The model infers the boundary from the contrast;
there is no fixed rule, exactly as in `_editor_marks`. A topic Micah dictated
himself is marked as such in the prompt — it is the strongest positive label
available. Output per candidate: propose or drop, a title, a `seed` phrase that
would actually retrieve the chatter, and one sentence naming the stake.

**Nothing publishes itself.** A candidate becomes a conversation only when a
human approves it.

## 3. The labels ARE the training data

```
dictated topic ─┐
approved cand. ─┼──> positive exemplars ─┐
                │                        ├──> stage 2 judge ──> proposals
rejected cand. ─┴──> negative exemplars ─┘                          │
        ▲                                                           │
        └──────────────── your verdict ─────────────────────────────┘
```

Every approve/reject sharpens the next run. There is no retraining step and no
fine-tune — the teaching set grows in the DB and is read into the prompt at run
time, the same mechanism as the card feedback loop.

## 4. The CLI

| Command | What it does |
|---|---|
| `discover_topics.py` | Run both stages, write proposals |
| `--dry-run` | Stage 1 only, no model call, no writes — see the ranking and the gates |
| `--no-judge` | Same, kept separate so cost is always an explicit choice |
| `--list` | Review proposals with score, features and evidence |
| `--approve <id>` | Becomes a row in `news_conversations` (origin `discovered`) — the collector picks it up on the next run, no code edit, no deploy |
| `--reject <id> --note "..."` | Kept forever as a negative exemplar; the note is the teaching signal |
| `--days N` | Widen or narrow the corpus window (default 10) |

Runs nightly as step 3 of `scripts/news-collect.sh`.

## 5. Conversations moved out of the code

`news_conversations` is now the source of truth;
`ingest_league_news._DEFAULT_CONVERSATIONS` is seed data for a fresh DB and the
fallback if the table is empty or unreachable. `--sync-conversations` writes the
defaults in. **This closes gap #2 of the 2026-08-09 audit** — a topic no longer
needs a code edit and a deploy.

## 6. First real run (2026-08-10)

1,098 items in the window, 836 raw clusters, **1** cleared every stage-1 gate.
Stage 2 rejected it (`world cup` — a tournament, not a conversation). The one
pending proposal from an earlier, looser run (`the dodgers` → "Dodgers payroll
debate") was rejected by hand as a duplicate of `mlb-salary-cap`, and is now the
first negative exemplar.

**A low yield is the correct result here, not a broken pass.** The only two
stake-phrase clusters in the corpus — `salary cap` and `media rights` — are both
already served by existing conversations. The engine currently covers the money
stories in its own feed. Yield should be judged over weeks, at one or two good
proposals, not fourteen.

## 7. Known limits

- **Corpus density is the binding constraint.** 783 of 836 clusters die on
  "fewer than 3 items". More sources (a transfer-news feed, more Bluesky
  queries) would raise the yield far more than any threshold tuning.
- **English-only stake vocabulary.** `_STAKE_TERMS` is English; Spanish-language
  chatter about Liga MX finances will not trip it.
- **No embedding/semantic clustering.** Two headlines about the same story that
  share no capitalized pair land in different clusters. Deliberate: the whole of
  stage 1 must stay explainable and free.
- **The judge sees titles, not full cards.** It reasons about a cluster's
  evidence lines, not the article bodies.
