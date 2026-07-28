# NFL data-honesty audit — 2026-07-28

Backend items are B*, frontend items F*. Measured against dev `:8096`, DB
`backend/data/picks.dev.db`, originally at `dev` @ `387391e`.

## Status at `c43d347`

| | finding | state |
|---|---|---|
| B1 | board and pool disagree about the same player | **fixed** `c43d347` |
| B2 | Aubrey's fake-punt carry published as kicking output | **fixed** `a740ccf` |
| B3 | a measured zero rendered as "no data" | open — `or None` at `nfl_offseason.py:986` |
| B4 | `ppr_per_team_game` divides by a hardcoded 17 | open, latent |
| B5 | pool contract never states its reference season | open |
| B6 | target-less weeks dropped from the season denominator | **fixed** `2ca7d57` |
| B7 | 284 players' snap % wrong — needs the published snap rows | open, needs ingest |
| B8 | 373 source-absent players rendered `gp=0, team_games=17` | open |
| F1–F3 | bye weeks, season labels | fixed `ab3490c`, `387391e` |
| F4, F5 | `RB1` collision, colour-coded judgement | open, design calls |

B6–B8 come from an independent read-only audit against the published nflverse
artifacts, with SHA-256s recorded for every source file. It is committed at
`docs/audits/nfl-honesty-2026-07-28/`, including the full `all-disagreements.csv`
— every surface/field disagreement with ours and published side by side.

---

## B1 FIXED (`c43d347`). The research board and the mock-draft pool disagree about the same player

Six live cases, every one a user can hit by checking a player twice:

| player | field | `/api/nfl/draft-board` | `/api/nfl/mock-draft/pool` |
|---|---|---|---|
| Chris Olave | `ppr_per_game_played` | 16.8 | 16.7 |
| Xavier Worthy | `ppr_per_game_played` | 7.8 | 7.9 |
| Ladd McConkey | `snap_pct` | 77.0 | 78.0 |
| DeMario Douglas | `snap_pct` | 27.0 | 26.0 |
| Colston Loveland | `snap_pct` | 65.0 | 64.0 |
| Mike Evans | `target_share` | 24.4 | 24.3 |

**Not two data sources — two rounding implementations.** Both are exact halfway
ties: Olave is 268.0 / 16 = **16.75**, Worthy 109.9 / 14 = **7.85**. The two paths
resolve the tie in opposite directions, and not even consistently with each other
(Olave rounds up on the board and down in the pool; Worthy does the reverse).

Fix is one shared rounding helper used by every surface, with an explicit and
documented tie rule — not a per-field reconciliation. A gate should assert
board == pool for every shared player and field, the same cross-endpoint shape
job16's parity test already uses.

> **The paragraph above is wrong, and the way it is wrong is the lesson.** Both
> surfaces already used the same rounder — plain `round()` — so a shared helper
> would have changed nothing. The inputs differed, not the rounding: Olave's
> 268.0 PPR over 16 games is an exact 16.75, which SQLite's `SUM` reaches and a
> Python accumulation loop misses by a last bit. "Two rounding implementations"
> was inferred from the symptom's shape and never checked. Fixed at `c43d347` by
> deleting two of the three implementations, not by sharing a rounder.

## B2 FIXED (`a740ccf`). Brandon Aubrey: one surface withholds, the other prints the artifact

`player_id` 882. `/api/nfl/draft-board?position=PK` returns `ppr_per_team_game`
and `xfp_per_game` as `null`. The pool and `/api/nfl/draft/player/882` return
`0.0` and `0.8`. Both come from the single fake-punt carry (B8).

**The board is right.** A kicker has no PPR, so the field is structurally null,
not a small number. `nfl_offseason.py:974-984` nulls the PPR family for `is_pk`;
`nfl_mock_draft.py` does not.

Own goal: job16's spec instructed matching the detail endpoint exactly "rather
than laundering a known defect behind a second opinion." The reasoning was right
and the target was wrong — the detail endpoint is the one that disagrees with the
board. Fix by nulling the PPR family for PK everywhere, which suppresses nothing
real, since the artifact remains visible in `player_game_logs`.

## B3. A measured zero is rendered as "we have no data"

`nfl_offseason.py:986` — `ppr_total = (scoring["ppr_total"] if scoring else None) or None`.
In Python `0 or None` is `None`. Reinforced at `:1056` and `:1057`, which guard on
`if ppr_total and games_played`.

Myles Price (`player_id` 18010, WR MIN) played **16 games**, has 16 rows in
`player_game_logs` and 16 in `nfl_snap_counts`, every row `{"fpts": 0, "fpts_ppr": 0}`.
He is measured completely and scored exactly zero. The pool returns `null` and the
UI renders an em dash — which claims we know nothing about him.

This is the inverse of fabricating a value and violates the same rule: absence and
zero are different facts. One player today only because 2025 is complete; during a
season, zero-point games are routine, and every one will read as missing data.

## B4. `ppr_per_team_game` divides by a hardcoded 17 — latent

`nfl_offseason.py:1057` — `_round(ppr_total / _REG_SEASON_TEAM_GAMES)`.

Fifty lines above, `:1003-1013` computes `team_games_val` from the player's actual
`team_weeks` under a comment that says explicitly *"Per-player team_games from
actual team_weeks, not the 17-constant. After a mid-season trade the new team may
have played a different number of games."* That value is then not used here.

**Not live:** no player in the current pool has `team_games != 17` (checked all
300). It fires on exactly the case the comment anticipates. The metric's whole
claim is "what the roster spot actually returned", which a wrong denominator
silently breaks.

## B5. The pool contract never states which season its statistics describe

`/api/nfl/draft-board` publishes `reference_season: 2025`. `/api/nfl/mock-draft/pool`
publishes `contract`, `season` (the season being *drafted*, 2026), and `count` —
nothing about the season the stats come from. A client cannot label the numbers
truthfully.

Suggest adding `reference_season` to the pool contract, matching the board.

---

## B6 FIXED (`2ca7d57`). A target-less week left the season denominator

Season target share averaged only the weeks that carried a `target_share` key, so
a receiver's target-less games vanished from the denominator and one busy
afternoon became his season rate. **243 players** on the board. Tom Kennedy read
14.8% against a published 2.5%; Britain Covey 11.8% against 2.0%.

Root cause is the ingest, not the aggregate: `_RECV_KEYS` is written only when the
week's target count is truthy, so a published `0.0` is dropped rather than stored.
The published artifact carries a non-null `target_share` on all 18,539 REG rows
and exactly **14,223** are zero — precisely the 14,223 rows where we store no key.

Both halves matter. A target-less week for a receiver is a published zero; a
player who drew no target *all season* is not a receiver and must stay null. The
first cut of the fix collapsed those and had Josh Allen reporting 0.0% target
share, which the pinned expectation caught.

`targets` (14,223) and `carries` (16,286) have the identical drop and are still
unfixed — they are display-only today, but the per-week game log renders them, so
a zero-target week still reads "—" there.

## B7. 284 players' snap percentage is wrong — and it is NOT the same fix

`off_pct` comes from the snap artifact, not the weekly stats file, and
`player_game_logs` only holds weeks a player recorded a touch. So a week with
snaps but no touch has **no row at all** — the value is not merely absent from the
row, the row does not exist. Coalescing it to zero would invent measured zeros.
Kennedy reads 65% against a published 12%; Jalen Royals 67% against 19%.

This needs the published snap rows to exist before it can be averaged correctly.
The aggregates deliberately keep a bare `AVG` on `snap_pct` and `xfp_per_game`
until then, and both call sites say so in a comment.

## B8. 373 source-absent players are rendered as `gp=0, team_games=17`

A player the source has never heard of is presented identically to a player
measured at zero across a full season — the same confusion as B3, one level up.

---

## Frontend — already fixed

- **F1 FIXED (`ab3490c`).** Bye weeks read `/api/nfl/schedule/2025` while drafting
  2026. DEN 12→10, LAR 8→11, SEA 8→11, CIN 10→6, DAL 10→14. Shipped wrong in
  v0.6.11 and v0.6.12.
- **F2 FIXED (`387391e`).** `ResultsScreen` labelled last season's production
  "PPR · 2026 season" beneath a headline that said "last season" correctly.
- **F3 FIXED (`387391e`).** Stat tooltips hardcoded "2025" — true today, false in
  twelve months. Now "last completed season" until B5 lands.

## F4. "RB1" means two different things in the same product — mine, introduced today

In the draft pool and the pre-draft list, the chip under a name reads `RB1` and
means **positional rank by ADP** (the best back on the board). In the results
roster panel, `RB1` is a **starting slot** — `buildRosterSlots` fills RB1/RB2 in
*draft order*, so a user's first-drafted back is labelled RB1 regardless of quality.

Both are standard fantasy conventions, which is exactly why the collision is easy
to miss and easy to misread. The overlay already disambiguates
("WR2 by ADP — not our ranking"); the row chip does not. Roster-slot naming is the
older convention and the one every incumbent uses, so the pool chip is the one to
change if we change either. Flagging rather than renaming unilaterally.

## F5. The same claim is colour-coded on one screen and colourless on another

`ResultsScreen`'s `ValueCard` renders a value pick in **emerald**. The overlay's
reach/value line I added is deliberately colourless, because `honest-data-ui` §6.2
reserves accent for absence and "reaching" is a judgement, not a missing value.

One of the two is wrong. I lean toward colourless in both — value-vs-reach is an
opinion, and colouring opinions is how a data product starts feeling like a tout
sheet — but this is a design call, not a correctness one.

## Checked and clean

- `adp ?? 999` sentinel is gone from `pages/mock-draft.tsx`.
- `TEAM_GAMES = 17` hardcoding is gone; `poolTeamGames` counts published `team_weeks`.
- `AvailabilityStrip` iterates `team_weeks`, so a bye cannot render as a missed game.
- No `NaN`, `undefined`, `Infinity` or `[object Object]` on `/mock-draft`,
  `/leagues/nfl`, or `/leagues/nfl?tab=camp` at 414x896 or 1440x900.
- 34 of the 35 em dashes in the pool are `sample: 'none'` with `games_played: 0`
  — honest absence. The 35th was B3.

- Every `toFixed` call site in the mock-draft surfaces carries the right unit —
  percentages get `%`, ADP and rates render plain, `snap_pct` at 0dp and
  `target_share` at 1dp match what the API emits.
- The value-vs-ADP sign convention is correct in both implementations, despite
  using opposite sign variables: `ResultsScreen` uses `pick_no - adp` (negative =
  value), the overlay uses `adp - currentPick` (positive = reach). Both produce the
  right verdict — spot-checked at ADP 90 drafted at pick 1 ("reaching 7.4 rounds
  early") and ADP 4.6 at pick 20 ("value").
- All 7 `thin` players sit at ADP ~169.9, the undrafted tail, so a 3-game sample
  never surfaces near the top of the board. Two carry negative rates (Kyle Allen
  -0.1, Jalen Milroe -0.5) which are real: interceptions and fumbles cost points.
- `FLEX` fills from the first remaining RB, then WR, then TE in *draft* order
  rather than by production. Cosmetic on a results screen, and "best" is a
  judgement we have not earned, so leaving it.

## Not yet audited

The camp-tab research board's own surfaces beyond the fields shared with the pool,
and the queue/autopick ordering.
