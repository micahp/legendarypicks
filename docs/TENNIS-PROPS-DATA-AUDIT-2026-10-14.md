# Tennis player-projection data audit

- **Audited:** 2026-10-16
- **Database snapshot:** local `backend/data/picks.dev.db` (read-only queries)
- **Purpose:** establish historical coverage for service-point exposure, aces and double faults before Gate A.
- **Scope:** main-tour ATP/WTA rows selected by `backend/tennis_point_model.py::TOUR_FILTER`.
- **Data boundary:** research only. The source does not permit commercial use.

This audit describes the local development database snapshot, not production or a permanent upstream archive. Counts may
change when the source mirror is refreshed. “Both players” means the corresponding winner and loser fields are present
and valid on the same match row; counts are not independent per-player totals.

## Findings

The archive contains about 1.77 million ATP/WTA match rows across all competition levels. The main-tour filter selects
236,594 ATP and 218,609 WTA rows. Match-level serve statistics are much sparser than match results, especially in older
WTA seasons. From 2015 onward, paired service-point coverage is materially better and is suitable for chronological
exposure research, subject to the row-level score and source checks below.

| Main-tour dataset | Rows | Rows with result IDs and score | Both `svpt` | Both `ace` | Both `df` | Both `1stIn` | Both `1stWon` / `2ndWon` | Both `SvGms` | Both `bpSaved` / `bpFaced` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ATP | 236,594 | 236,542 | 121,748 | 121,748 | 121,748 | 121,748 | 121,748 | 121,747 | 121,748 |
| WTA | 218,609 | 218,503 | 65,895 | 65,879 | 65,846 | 65,896 | 65,894 | 39,517 | 65,889 |

Paired service-point records span 1990-12-31 through 2026-05-17 for ATP, and 2003-05-26 through 2026-05-18 for WTA.
Those are the earliest/latest rows with paired `svpt` in this filtered snapshot, not a claim that every intervening year is
complete.

### Paired service-point coverage by historical period

Counts are main-tour rows / rows with both players' service-point statistics. 2025-26 is partial in this snapshot.

| Period | ATP rows / paired `svpt` | WTA rows / paired `svpt` |
|---|---:|---:|
| 2000-2004 | 17,016 / 14,439 | 21,172 / 772 |
| 2005-2009 | 20,416 / 14,118 | 21,027 / 7,879 |
| 2010-2014 | 22,453 / 21,777 | 20,290 / 17,420 |
| 2015-2019 | 20,288 / 18,128 | 20,684 / 17,460 |
| 2020-2024 | 18,199 / 18,027 | 17,146 / 16,986 |
| 2025-2026 partial | 5,734 / 5,595 | 5,563 / 5,378 |

The 2000-2009 WTA gap is substantial. A comparison that starts in 2015 has more comparable paired coverage; any earlier folds
must publish their changing sample sizes and may not silently impute missing outcomes.

### All-level inventory (context only)

This is the full source-table coverage before the main-tour filters. It must not be used as the main-tour denominator.

| Source table | Rows | Rows with result IDs and score | Both `svpt` | Both `ace` | Both `df` | Both `1stIn` | Both `1stWon` | Both `2ndWon` | Both `SvGms` | `RET` marker in score | walkover marker in score |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ATP all levels | 988,216 | 988,064 | 259,680 | 259,680 | 259,680 | 259,680 | 259,680 | 259,680 | 259,678 | 29,690 | 5,557 |
| WTA all levels | 786,657 | 786,460 | 101,998 | 101,982 | 101,949 | 101,999 | 101,999 | 101,997 | 75,314 | 18,767 | 4,636 |

The source-table date range reaches back before the reliable modern-stat era and includes implausible historical date values.
The main-tour research query begins in 2000; old raw date minima should not be presented as useful model coverage.

## Fields and target construction

The source rows are keyed by match winner and loser (`w_` and `l_`), not home and away. Relevant aggregates are:

| Field | Use | Limitation |
|---|---|---|
| `svpt` | Service-point exposure for that player | Match aggregate; does not identify each point or the server's first/second-serve sequence. |
| `ace`, `df` | Ace and double-fault count targets | Aggregate counts; aces are not labeled as first-serve or second-serve aces. |
| `1stIn` | First serves landed; with `svpt`, supports a second-serve-opportunity exposure proxy (`svpt - 1stIn`) | Verify source conventions and row validity before deriving the denominator. |
| `1stWon`, `2ndWon` | Serve points won on first and second serve; feeds the current point model | Match-level aggregates, not point sequence. |
| `SvGms` | Service games played | Missing more often than `svpt`, particularly in WTA. |
| `bpSaved`, `bpFaced` | Server-side break-point outcomes | Does not provide shot-level context; partial-match rows need separate handling. |
| `score`, `best_of`, `surface` | Completion screening, match format and broad court surface | Score strings do not provide a complete, normalized tournament-rules record. `tourney_date` is event start, not actual match date. |

The match source supports initial aggregate-count baselines. It does not contain reliable per-point event labels for first-serve
aces, rally outcomes, serve direction, return depth, winners or unforced errors. Those must not be fabricated from totals.

## Completion, format and chronology

- Main-tour ATP rows include 919,495 best-of-three and 68,685 best-of-five matches (plus 36 rows coded best-of-one). WTA
  includes 786,427 best-of-three, 124 best-of-five and 106 best-of-one rows. Initial Gate A should be restricted to completed
  best-of-three matches so that scoring rules and source coverage are comparable; best-of-five is a separate format study.
- The all-level score strings contain 29,690 ATP and 18,767 WTA `RET` markers, plus 5,557 and 4,636 walkover markers,
  respectively. These are raw marker counts, not a final adjudication of every incomplete or abandoned match. Exclude
  retirements and walkovers from the primary completed-match exposure target; report their coverage separately.
- The live archive field `tourney_date` is the tournament start date, not each match's actual date/time. The walk-forward
  replay groups all matches on the same event-start date and updates player histories only after the whole date group. That
  prevents same-date leakage but may lag information that would have been available between rounds. Exact match-time
  chronology requires another source.
- The available `best_of` and score text do not form a complete, verified rules table for every tournament and season. The
  existing backtest treats bracket-marked deciding match tiebreaks as a special format; this convention needs tournament-level
  verification before the simulator is claimed to cover all historical formats.
- Match scores can be checked for completion, but a target row with incomplete or inconsistent service statistics must be
  excluded from service-point scoring even if its match result is present.

## Main-tour filters and surface

The audit uses the same ATP/WTA main-tour SQL filters as `backend/tennis_point_model.py`; it does not count every event in
the source CSVs as ATP/WTA tour matches. The WTA rule includes the approved historical event-ID exceptions for generic `W`
levels and excludes ITF and WTA 125 events as currently documented in that module.

The row schema contains broad surface labels (hard, clay, grass and historical carpet) and match format. Surface is present
on 234,753 of 236,594 ATP main-tour rows and 214,186 of 218,609 WTA main-tour rows. A surface- and year-stratified count
should accompany each modeling run; historical carpet and early WTA statistics are sparse and should not be pooled as if
they represented modern hard-court coverage.

## Prospective data and grading audit (local dev snapshot)

The same dev database has a partial pre-match forecast stream, but it is not yet the daily evaluation system described in
the research plan:

- 12 forecast locks are present since 2026-10-14, with the earliest lock on 2026-10-15; none were locked on Oct 14.
- 11 of those locks have a grade in the snapshot. All use `tennis-free-daily-v1`.
- Locks are unique by `(league, game_id)`, so the current table cannot preserve multiple concurrent challenger versions
  for one match.
- The stored projection includes a selected-winner probability and expected total games/interval plus point estimates for
  aces. It does not retain an input snapshot or full winner, total-game, ace or double-fault probability distributions.
- Grading currently records winner correctness and absolute total-games error. It does not compute winner Brier/log loss,
  distribution scores, calibration or ace/DF grades. There is no cumulative daily report or 100/250/500/1,000-match view.

These counts describe the inspected local development database only. Do not backdate missing forecasts to Oct 14. Prospective
records should be immutable and keyed by model version, target, input snapshot and forecast timestamp; every challenger
needs its own records.

## Gate A protocol and status

The first experiment compared exact expected service points from the existing point-probability/scoring model with two
direct exposure references: a rolling player/surface mean shrunk to the tour/surface mean, and the tour/surface mean alone.
The expected-volume screen is complete on both tours. On ATP (35,099 matches), simulator MAE is 19.227 versus 17.711 for
player-rolling and 17.655 for tour/surface; simulator mean bias is +7.292. On WTA (38,635 matches), the corresponding MAEs
are 20.250, 18.036 and 17.957; simulator mean bias is +9.226. It loses in every test year and on hard, clay and grass.

The exact expectation uses the current point probabilities and scoring rules and was checked against independent
point-by-point Monte Carlo. All comparisons use prior-only, completed best-of-three matches and identical paired target
rows. The archived event-start date forces all same-date matches to be forecast before any of them update history.

The full-distribution replay, using 50 simulated trajectories per match, also loses to the direct empirical exposure
distribution on both tours and under-covers nominal intervals. Two independent seeds per tour produced ATP simulator
CRPS 12.842/12.814 versus direct 12.214, and WTA 13.503/13.505 versus direct 12.422. The current simulator is rejected
for service-point exposure on the evaluated completed best-of-three population. A format/history-depth review remains
before extending this decision to other formats or evidence-depth groups.
Results:
[`TENNIS-PROPS-BASELINES-2026-10-14.md`](TENNIS-PROPS-BASELINES-2026-10-14.md).
