# NFL chart content — what the analytics community actually posts

Reference for the "shareable chart" acquisition angle. Pairs with
[NFL-DATA-INVENTORY.md](./NFL-DATA-INVENTORY.md), which is the authority on what LP
actually stores.

> **Provenance.** The survey in §1 was supplied by Micah (2026-07-26) from a search of
> the 2025 NFL season, roughly Sept 2025 – Feb 2026. **I did not independently verify
> these posts, their engagement figures, or the account attributions** — this box cannot
> reach X, and the datacenter-IP bot wall already blocks ESPN and PFR. Treat the examples
> as directionally real and the engagement numbers as unverified. The feasibility mapping
> in §3 *is* verified: it was read off the ingest code and the database.

---

## 1. The survey

Tooling is near-universally **nflfastR / nflverse** — the open play-by-play ecosystem.
Posts credit it explicitly, usually with a `via @nflfastR` tag.

| Account | Date | Chart | Metric | Grain |
|---|---|---|---|---|
| @tejfbanalytics | 2026-01-11 | WPA lost on special teams, one game | win probability added | **per play** |
| @benbbaldwin | 2026-01-06 | Offensive series results, all 32 teams, stacked bars | TD / 1st down / FG / punt / TO rate | **per play** (series) |
| @EvanHAbrams | 2026-01-12 | Downfield pass chart, one game | air yards per throw, completion state | **per play** |
| @Intellectsp | 2026-01-21 | CPOE vs EPA scatter, r = 0.691, 5 seasons | CPOE, EPA per dropback | per game |
| @GrantPaulsen | 2025-11-13 | EPA per run by gap, fan diagram | EPA by rush direction | **per play** |
| @hawkblogger | 2025-12-14 | Weekly team EPA lines + pass/run volume bars | EPA per play by week | per game |
| @mrcaseb | ongoing | maintainer posts — new features e.g. explosive plays | — | — |
| @LeeSharpeNFL | ongoing | schedule data folded into nflverse | — | — |

### What the ones that travel have in common

- **A single claim, not a dashboard.** One chart, one sentence, one argument.
- **Tied to something that just happened** — last night's game, a trade, end of season.
- **A named entity people already argue about** — a team, a QB, a coach's decision.
- **Simple forms.** Stacked bars, scatter with a trend line, a dot chart, a radial gap
  diagram. Nothing exotic.
- **Credited tooling.** `via @nflfastR` is part of the convention and signals
  reproducibility.

## 2. Why this is relevant to LP

The metrics driving these posts — EPA, CPOE, air yards, separation — are the same ones
LP had sitting ingested and unrendered until 2026-07-26 (commits `632b9e3`, `2f618e9`).
The raw material overlaps almost exactly with what the community builds content from.

## 3. What LP can build today, and what it cannot — verified

`ingest_nfl_pbp_logs.py` downloads the full nflverse play-by-play with
`import_pbp_data([year])`, aggregates it to per-player-per-game lines, and **persists
only the rollup**. No play table exists. So:

**Buildable from stored data — per-game grain**

- CPOE vs EPA-per-dropback scatter (the @Intellectsp form) — `cpoe`, `epa_per_db`
- Week-over-week efficiency lines (the @hawkblogger form, player rather than team)
- Separation / cushion / YAC-over-expected distributions — WR and TE only, 210 players
- Target share, snap share, carry share trends
- Position leaderboards on any stored metric

**Not buildable without retaining plays**

- Win probability swings inside a game (@tejfbanalytics)
- Series / drive outcome breakdowns (@benbbaldwin)
- Air-yards pass charts, one mark per throw (@EvanHAbrams)
- EPA by run gap or direction (@GrantPaulsen)
- Any down / distance / field-position / personnel split

**Four of the six concrete examples need per-play data.** The chart forms that travel
furthest are exactly the ones the current rollup cannot produce.

## 4. The constraint that decides whether this is a real angle

Retaining plays is one write in an ingest that already fetches the rows — but this
box is memory-tight (5.9 GB, ~1.5 GB available with a dev server up), and a season of
play-by-play is roughly 50k plays × ~370 columns. **Column selection and row volume have
to be sized before committing**, not after. That sizing has not been done.

## 5. Honest counterweight

LP is not short of surfaces; it is short of traffic. Prior course-correction on the
esports board (see the esports/niche direction memory) was specifically about not
grinding on surfaces nobody visits. A chart nobody sees is the same failure with better
metrics.

What is different here: these posts are **distribution**, not another in-app surface —
the artifact is a PNG that leaves the site. That is the same thesis as the broadcast-alpha
pivot to crowd-vs-market receipts. It only works if something publishes them on a
cadence, which is a separate build from generating them.
