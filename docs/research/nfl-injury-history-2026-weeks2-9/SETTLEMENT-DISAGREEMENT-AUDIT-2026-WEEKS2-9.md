# Settlement disagreement audit — 2026 Weeks 2–9

Row-level root-cause analysis of the 38 graded prop lines where the recorded
sportsbook settlement disagreed with our graded settlement. The backtest numbers
on `weekly-prop-projection-metrics.csv` are unchanged; nothing in the grader,
the ingester, or `prop_results` was modified by this audit.

## Headline

38 prop lines are **2 underlying problems**, not 38. Both are the same defect,
and the defect is in the weekly ingest, not in the grader's settlement logic or
in the sportsbook data:

> The weekly ingester drops the entire receiving key group (`targets`, `rec`,
> `rec_yds`, `rec_td`, `rec_air_yds`) when a player's target count is zero. The
> NFL credits receiving yards — and any touchdown — for a post-catch lateral to
> the player who ends up with the ball, which can happen with zero targets and
> zero receptions. Those yards then vanish from our game log, and the grader,
> which reads a missing key as zero, settles the over as a loss.

Both books and both players were right; we were wrong.

## The 38 rows

| Week | Game | Player | Pos | Market | Lines | Lines | Books | Recorded (book) | Ours |
|---|---|---|---|---|---|---|---|---|---|
| 3 | `2026_03_ARI_SF` (ARI @ SF) | Deebo Samuel Sr. | WR | receiving_yards | 31.5 – 51.5 | 23 | 7 | 80 yds, over | 0 yds, under |
| 4 | `2026_04_DAL_HOU` (HOU vs DAL) | David Montgomery | RB | receiving_yards | 0.5 – 11.5 | 15 | 7 | 19 yds, over | 0 yds, under |

- All 7 tracked books are represented in both cases (bovada 13, draftkings 6,
  fanduel 4, betmgm 4, caesars 4, hardrock 5, betrivers 2).
- 8 alternate lines on the same two player-games agreed and are **not** in the
  audit (Deebo 92.5/98.5/101.5/108.5, Montgomery 28.5/40.5/41.5/54.5): they are
  far above the true value, so both sources settle under.
- Full detail, including `prop_id`, `under_prop_id`, odds both sides,
  `captured_at`, `settled_at`, and the raw stats JSON:
  `settlement-disagreements-2026-weeks2-9.csv`.

## Grouping: repeats, not independent problems

| Grouping | Distinct | Concentration |
|---|---|---|
| Player | 2 | Deebo 23 lines, Montgomery 15 lines |
| Player + market | 2 | 100% `receiving_yards` |
| Game | 2 | one game each |
| Book | 7 | spread evenly across all books |
| Alternate line | 15 | 8 distinct lines for Deebo, 7 for Montgomery |

Every one of the 38 falls inside two player-games. Nothing is book-specific,
market-family-wide, or spread across weeks.

## Underlying facts (three independent sources agree with the book)

1. **Upstream nflverse** (`stats_player_week_2026.parquet`, fetched 2026-11-13,
   sha256 recorded in the audit log): Deebo wk3 `targets 0, receptions 0,
   receiving_yards 80, receiving_tds 1`; Montgomery wk4 `targets 0,
   receptions 0, receiving_yards 19, receiving_tds 0`.
2. **Our own database** has those rows, but with `targets: 0` and **no**
   receiving keys at all — `rec_yds`, `rec`, `rec_td`, `rec_air_yds` are absent,
   which is what the grader reads as zero. Every other week for the same
   players carries them (Deebo wk2: `rec_yds 31, rec 3, targets 4`).
3. **Official play-by-play (ESPN summary for the two events)**:
   - `401872958`: "(Shotgun) B.Purdy pass short left to M.Evans to SF 20 for 2
     yards. **Lateral to D.Samuel for 80 yards, TOUCHDOWN.**" — Evans is credited
     with the 2-yard reception; Deebo gets 80 receiving yards and the TD with no
     reception and no target.
   - `401872967`: "(Shotgun) C.Stroud pass short right to D.Schultz to DAL 25
     for 2 yards. **Lateral to D.Montgomery** pushed ob at DAL 6 for 19 yards."
   - ESPN box score for the same events shows the identical shape: Deebo
     `receptions 0, receivingYards 80, receivingTDs 1, targets 0`; Montgomery
     `receptions 0, receivingYards 19, targets 0`.
   - Our own `fpts` agrees, which is the tell: Deebo's log row carries
     `fpts 15.4` = 14 rush yds (1.4) + 80 rec yds (8.0) + TD (6.0). The yards are
     being counted somewhere in our pipeline — just not in the field the grader
     reads.

No stat correction, no push, no void, no market-definition difference, and no
disagreement about the settlement itself. Both recorded settlements are correct.

## Root cause

`backend/ingest_nfl_weekly_stats.py` builds the stats JSON with role gates:

```python
groups = ((_PASS_KEYS, att or sac), (_RUSH_KEYS, car),
          (_RECV_KEYS, tgt), (_KICK_KEYS, is_kicker))
for keys, active in groups:
    if not active:
        continue
```

The receiving gate is `tgt`. Zero targets means the whole receiving group is
skipped, so `rec_yds` and `rec_td` are never written. The file already documents
this exact failure mode for one key — `target_share` was moved out of the gate
into `_ALWAYS_KEYS` because "a receiver who drew no targets in a game has a
published target_share of 0.0, and dropping the key takes that week out of the
season denominator". The same reasoning was not applied to `rec_yds` / `rec_td`,
which are the fields the prop grader reads.

Downstream, `nfl_player_projection_v2.Row` sets `rec_yds = _num(stats.get("rec_yds"))`,
so an absent key becomes 0 and is indistinguishable from a genuine zero-target,
zero-yard game. That is why the mismatch surfaces as a settlement disagreement
rather than as a missing-data error.

Scale of the condition in the source data (nflverse regular season):

| Season | Player-weeks | `receiving_yards > 0` with `targets == 0` |
|---|---|---|
| 2025 | 18,540 | 1 (Isaiah Bond, wk16, 21 yds) |
| 2026 | 9,534 | 2 (Deebo wk3, Montgomery wk4) |

Rare but recurring — a systematic gate defect with a low hit rate, not a
one-off data glitch. The 2025 case means one row of 2025 model history is
silently short as well.

## Classification

| Case | Lines | Cause | Status |
|---|---|---|---|
| Deebo Samuel Sr. wk3 vs ARI | 23 | Ingest gate drops `rec_yds`/`rec_td` when `targets == 0` (lateral-play scoring) | confirmed ingest bug |
| David Montgomery wk4 vs DAL | 15 | Same gate, same cause, no TD | confirmed ingest bug |

- Grader settlement logic: **not implicated**. It compares the line to the stat
  it is given; it was given 0.
- Source settlement: **not implicated**. Both settlements match the official
  play-by-play and the upstream nflverse artifact.
- Stat correction / push / void / market definition: **ruled out**. The plays
  are laterals, not corrections; lines are all half-points, so no pushes; the
  book settled the standard "receiving yards" definition.
- Unresolved: **none**.

Not a bug: the 8 high alternate lines on the same player-games that agree with
us. They are correct settlements under a wrong stat value, because the line sits
above both 0 and the true value.

## Impact

### Settlement-only (probabilities held fixed)

Setting `actual` to the true value and re-deriving `over` from `actual > line`
for the 46 receiving-yards lines on the two player-games, with every probability
untouched (`impact-settlement-only.json`, `impact-mae-settlement-only.json`):

| Week | Lines | Spec B v2 Brier | Δ | Forward Platt Brier | Δ | Market Brier | Δ |
|---|---|---|---|---|---|---|---|
| 3 | 35 | 0.282858 → 0.283444 | +0.000586 | 0.250044 → 0.250095 | +0.000052 | 0.2462531 → 0.2462531 | +0.0000001 |
| 4 | 26 | 0.285347 → 0.285814 | +0.000467 | 0.247876 → 0.247880 | +0.000004 | 0.2468628 → 0.2469004 | +0.000038 |
| 2–9 pooled | 46 | 0.265222 → 0.265356 | +0.000135 | 0.243917 → 0.243925 | +0.000008 | 0.2457535 → 0.2457587 | +0.000005 |

The correction makes our scores **slightly worse**, which is the expected
direction: the model had those overs priced low, and the bogus zero was
rewarding it with a free correct "under". Point MAE over the ~500 player-game
markets per week moves by +0.0005 (Week 3) and +0.0039 (Week 4); Marcel-lite on
Week 4 improves 15.671 → 15.641 because it projected 16 for Montgomery against a
true 19 instead of against 0.

### History contamination (full what-if rerun)

Those same two rows are also history for later weeks, so the effect is separate
from settlement. `run_corrected_history_impact.py` patches only the two
in-memory `History` rows and calls the committed runner unchanged; its outputs
are in `impact-corrected-history/`. No database row, grader file, or committed
artifact was touched.

| Check | Before | After |
|---|---|---|
| Recorded settlement disagreements, Weeks 2–9 | 38 | **0** |
| Graded prop lines | 65,448 | 65,448 |
| Player-game-market rows | 3,805 | 3,805 |

Week-level Brier deltas from the rerun:

| Week | Spec B v2 | Forward Platt | Market |
|---|---|---|---|
| 3 | +0.000586 | +0.000052 | 0.000000 |
| 4 | +0.000463 | −0.000071 | +0.000038 |
| 5 | +0.000035 | +0.000083 | 0.000000 |
| 6 | −0.000024 | −0.000043 | 0.000000 |
| 7 | −0.000020 | +0.000059 | 0.000000 |
| 8 | −0.000015 | +0.000033 | 0.000000 |
| 9 | −0.000018 | +0.000011 | 0.000000 |
| 2–9 pooled | +0.000129 | +0.000017 | +0.000005 |

- **The 38 disagreements go to exactly 0**, with no change to the graded
  population. That is a complete, closed explanation: nothing else in the
  sample depends on this defect.
- Weeks 3–4 move because the outcomes themselves change; Weeks 5–9 move by
  ≤0.00004 because every later receiving-yard projection shifts by a few
  hundredths of a yard — the engine's season-level rate denominators include the
  corrected player-game, so the change reaches players who were never quoted.
- Deebo's Week 4 Marcel-lite jumps 26.33 → 53.0, which is the largest single
  downstream distortion found.
- Direction is consistent across both methods: the raw model scores marginally
  worse once the stat is right, and it still does not beat the market pooled
  (0.2654 vs 0.2458) or on forward Platt (0.2439 vs 0.2458 — a 0.002 edge that
  weakens, not strengthens, under correction).

## What this audit does not change

- The scored population is intact and reproducible: the independent Weeks 2–9
  re-derivation matched `grader.grade()` exactly (65,448 = 65,448), and a full
  rerun reproduced every Brier and MAE number because the sim seeds are stable.
  That result is preserved on its own in `population-audit-2026-weeks2-9.json`.
- No settlement row, grader file, or ingester file was edited. The committed
  backtest artifacts still contain the 38 disagreements, now documented.

## Reproduce

```sh
python docs/research/nfl-injury-history-2026-weeks2-9/audit_settlement_disagreements.py \
  --db backend/data/picks.dev.db \
  --out-dir docs/research/nfl-injury-history-2026-weeks2-9   # positional in practice
```

```sh
python docs/research/nfl-injury-history-2026-weeks2-9/run_corrected_history_impact.py
```

Both open the database read-only. The audit writes
`settlement-disagreements-2026-weeks2-9.csv` and
`settlement-disagreements-summary.json`; the what-if runner writes only inside
`impact-corrected-history/`.

## Recommended fix (not applied)

Move `rec_yds`, `rec_td`, `rec` and `rec_air_yds` out of the target-gated group
into the always-written set alongside `targets`, so a published zero target and
a published 80-yard lateral touchdown are both represented — the same treatment
`target_share` already received, for the same reason.

Condition (a) is already demonstrated by the in-memory what-if: correcting only
these two rows takes the disagreement count from 38 to 0. Before applying it,
confirm (b) the 2025 Isaiah Bond row appears, and (c) no other stat field
changes for any player-week, then re-run the backtest and re-record the metrics.

Until that is reviewed, read the committed backtest with these two rows treated
as known bad actuals and with the settlement column at 23/15 for Weeks 3/4.
