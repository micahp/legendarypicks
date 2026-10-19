# NHL starter-feed feasibility — 2026-10-19

Research-only. Branch `research/nhl-starter-feed-2026-10-19`, worktree
`/root/lp-nhl-starter-feed` (off `dev` @ `c4bd3c9f`). Not merged, not deployed. The tiered
pick policy is untouched and remains NO-GO. No GSAx re-run, no re-parameterisation.

**Verdict: DROP.** A pre-puck-drop starter feed cannot be obtained free, reliably, and with
history; and even a perfect feed has an outcome ceiling (`|Δp| ≈ 0.0071`) below the noise
floor of the game-level gates the goalie adjustment already failed. Closing the starter gap
cannot plausibly turn the null into a win.

## 1. Correcting the premise

The goalie report (`research/nhl/goalie-adjustment-report-2026-10-18.md`) established:

- Located shot-level data **exists in abundance**: `shots`, 2,079,359 rows, seasons 2007–2025,
  with coordinates, angle, distance, shot type, `xGoal`, and `goalieIdForShot`. Shot
  difficulty was never untestable — it enters through the xG denominator. The G2 null is a
  real null for the GSAx adjustment, not an inability to measure.
- What is actually missing is a **pre-puck-drop starter signal**. The only starter flag on
  this host is `goalies_playoff_boxscores.starter`, 2025-postseason-only and post-hoc.
- Consequence already recorded: the expected starter had to be guessed statistically at
  **49.7%** accuracy, against a **52.5%** raw same-starter repeat rate. The heuristic is
  barely better than assuming the starter repeats, and worse on back-to-backs.

The question here is narrow: **does a usable starter feed exist at all, and what is the
ceiling on its value?** This document answers only that. It does not revisit GSAx, the goal
distribution, or the pick policy.

## 2. Feed survey

Method: inspect the local ingestion/DB for any existing lineup feed, and query the free NHL
API (`api-web.nhle.com`) live for a future game to see exactly what it publishes pre-puck-drop.
Local checks: `backend/ingest_nhl.py` pulls only
`api-web.nhle.com/v1/roster/{TEAM}/current` (current rosters) and player landing stats. No
lineup/probable-starter ingest exists anywhere in `backend/`. The main app DB has no
lineup/roster/starter table for NHL. The goalie worktree named Daily Faceoff as the intended
source but nothing fetches or stores it.

Live API verification on 2026-10-19 against game `2026020137` (ANA @ NYR, `gameState: FUT`,
puck drop 23:00 UTC):

| Endpoint | Result for a future game |
|---|---|
| `/v1/gamecenter/{id}/landing` | OK. Contains `matchup.goalieComparison` — but that is **season team totals + goalie leaders** (`gaa`, `savePctg`, `gamesPlayed`), **not** the designated starter. No `starter`/`probable`/`projected` field anywhere. |
| `/v1/gamecenter/{id}/roster` | **HTTP 404** pre-game. |
| `/v1/gamecenter/{id}/summary` | **HTTP 404**. |
| `/v1/gamecenter/{id}/line-score` | **HTTP 404**. |
| `/v1/gamecenter/{id}/right-rail` | OK but contains no goalie/starter field. |

So the NHL's own free API publishes **no pre-puck-drop starter**. It is post-hoc at best:
the `starter` concept only appears in box scores once the game is played.

Candidate feed table. "Lead time" is relative to puck drop. "Historical" asks whether past
pre-game snapshots can be reconstructed, which is what a backtest needs. "Storable" asks
whether we may persist it without violating terms.

| Source | What it publishes | Lead time | Historical | Free? | Storable? |
|---|---|---|---|---|---|
| NHL API (`api-web.nhle.com`) gamecenter | Game meta, season goalie stats in `matchup.goalieComparison`; no starter field; roster/summary/line-score 404 pre-game | none for starter | No pre-game archive; only post-hoc box scores | Free | Yes (no starter to store) |
| Daily Faceoff | Probable + confirmed starters, line combos | Morning-of → ~1h (confirmed at warmups) | No bulk/archived pre-game snapshots | Free web | ToS-restricted; scraping is the only route |
| Left Wing Lock | Probable + confirmed starters | Morning-of → ~1h | No bulk archive | Freemium | Restricted |
| Rotowire | Probable starters / lineups | Early AM → warmups | Paid historical access possible | Paid subscription | Yes, via subscription |
| MoneyPuck / local `shots` | Post-hoc `goalieIdForShot` | post-game only | 2007–2025, already local | Free | Already stored |
| NHL box scores / `goalies_gamelogs`, `goalies_playoff_boxscores.starter` | Post-hoc starter | post-game only | Full history locally (regular-season starter flag absent) | Free | Already stored |
| Beat writers / team PR / social | Confirmed starter | ~1–2h, unstructured | No reliable archive | Free | Unstructured, not bulk-storable |

Summary of the survey: the only sources that actually carry a *pre-puck-drop probable or
confirmed starter* are third-party (Daily Faceoff, Left Wing Lock, Rotowire). Daily Faceoff
and Left Wing Lock are free to read but have no historical pre-game archive and no clean bulk
API; Rotowire has history only behind a paid subscription. The NHL's own API does not carry
the signal at all. There is **no free, self-hosted, historically-archivable starter feed**.

## 3. Achievable accuracy

The 49.7% is the number that must move. What could a feed realistically deliver?

- **Perfect feed (confirmed starter at puck drop):** accuracy ≈ 100%, but only at ~1 hour
  before puck drop. For a morning/early-afternoon forecast the realistic hit rate of a
  "probable starter" feed is materially lower.
- **Realistic free feed:** probable-starter pages publish hours ahead and are typically right
  roughly 70–80% of the time for the *listed* goalie; the listed goalie is frequently not the
  starter, and back-to-backs and late changes are exactly where the heuristic already fails
  (back-to-back same-starter repeat is only 25.4%).
- **Observed-starter ceiling already measured:** the goalie report's retrospective recomputation
  using the *observed* starter is the perfect-feed bound — no feed can beat it. Even then the
  average win-probability movement is `|Δp| = 0.0071`, max 0.0573.

So a perfect feed would move starter accuracy from 49.7% to 100%, but the *forecast* only
gains the 0.0071 Δp already measured on the observed starter. A realistic free feed captures
a fraction of that. The raw same-starter repeat rate (52.5%) is itself close to the heuristic,
so the headroom above 49.7% is small and concentrated in spots (back-to-backs) where no free
source reliably confirms in time.

## 4. Bounded upside

Take the goalie report's observed-starter recomputation as the upper bound. If starter
information were **perfect**:

- Win probability moves `|Δp| = 0.0071` on average, max `0.0573`.
- Expected goals-against rates move ~`+0.004` (home) / `−0.0015` (away) goals.
- Fitted goalie effect: `κ = −4.72` ⇒ GA-rate multiplier 0.968 (95th-pct goalie) to 1.020
  (5th-pct goalie), a **±2–3% GA swing**.

The decisive argument is direct, not arithmetic: **the perfect-feed recomputation already failed
the outcome gates.** The observed-starter forecast is exactly what a perfect feed delivers, and
it did not beat the league-average-goalie baseline on Brier or log loss — the paired,
game-clustered CIs included zero. If the ceiling case itself fails the gate, no less-accurate
feed can clear it. That argument alone carries the DROP.

The Brier arithmetic sometimes quoted here — a `0.0071` movement changing Brier "on the order of
`(0.0071)² ≈ 5×10⁻⁵`" — is **illustrative, not a bound**, and the comparison to the CI half-width
is dimensionally invalid: a probability movement and a Brier interval are different units. The
true per-game Brier delta from a probability shift `d = p₂ − p₁` is `2·d·(p₁ − y) + d²`. Its
first-order term `2·d·(p₁ − y)` is ~`1×10⁻³` per game and does **not** average to zero when the
starter signal is informative. So the honest statement is not "the effect is 10× below the noise
floor"; it is "the perfect-feed case was measured and failed the gate" — a statement about the
gate outcome, not a unit comparison. The distribution gate, by contrast, already passes without a
real feed (CRPS 1.3917 → 1.3872, PIT improves both sides), so a feed's marginal value would be
confined to the goal distribution, not the outcome.

Plainly: the null is not caused by the starter gap alone. The goalie effect size is genuinely
small (±2–3% GA). Closing the starter gap raises starter accuracy but does not raise the
lever's size. The perfect-feed bound already failed the outcome gate; that is the bound that
matters.

## 5. Recommendation: DROP

Do not invest in a starter feed. Reasons, in order of weight:

1. **No free, reliable, historical feed exists.** The NHL API carries no pre-game starter; the
   only probable-starter sources are third-party with no pre-game archive (Daily Faceoff,
   Left Wing Lock) or paid (Rotowire). Micah wants real prices before any paid swap, and the
   value below does not justify one.
2. **The perfect-feed ceiling already failed the outcome gate.** The observed-starter
   recomputation *is* the perfect-feed bound, and that forecast did not beat the
   league-average-goalie baseline on Brier or log loss. If the ceiling case fails the gate, no
   less-accurate feed can clear it.
3. **The distribution already improves without a feed.** The real, defensible finding from the
   goalie work — CRPS/PIT improvement — is obtained without any starter signal. A feed would
   only sharpen the pre-confirmation goal distribution slightly, not change outcomes.
4. **A feed would require ongoing, fragile scraping** of ToS-restricted pages, with no bulk
   history, on a cost-conscious, shared box. Operating cost exceeds expected value.

This is a "not worth it" verdict, which the task explicitly allows. The information gap is
real and correctly identified; closing it is simply not worth the cost given the measured
effect size.

## 6. What was deliberately not done

- No GSAx re-run, no shrinkage/window/feature change. The G2 null stands.
- No production code, ingestion, or schema changes. Nothing was adopted, promoted, or served.
- The tiered pick policy was not touched (still NO-GO).
- No dev merge, no deploy. Research stays on this branch.
- No paid feed was purchased or trialled; only free public endpoints were inspected live.

## 7. Provenance

- Goalie report and audit: `research/nhl/goalie-adjustment-report-2026-10-18.md`,
  `research/nhl/goalie-data-audit-2026-10-18.md` (worktree `/root/lp-goalie-research`).
- Starter accuracy 49.7%, repeat rate 52.5%, `|Δp| = 0.0071`, `κ = −4.72`: goalie report §3–§6.
- Live API check: `api-web.nhle.com` gamecenter endpoints, 2026-10-19, game `2026020137`.
- Local ingestion check: `backend/ingest_nhl.py`, `backend/data/picks.db` table list.
