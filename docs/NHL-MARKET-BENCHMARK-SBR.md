# NHL market benchmark — the SBR odds archive

Status: **usable as the NHL market benchmark from 2018-19 onward.** Legacy seasons are
partial and must not be quoted as a no-vig benchmark.

## Where it came from

Sportsbook Review's `scoresoddsarchives` NHL spreadsheets. The live URLs return 404 as of
2026-10-19; the files are preserved in the Wayback Machine and were retrieved from there:

```
https://web.archive.org/web/<timestamp>id_/https://sportsbookreviewsonline.com/scoresoddsarchives/nhl/nhl%20odds%20<season>.xlsx
```

16 season files, 2007-08 through 2022-23. The raw xlsx files are not committed (they are
redistributable only as an archive copy); `parse_sbr.py` regenerates the normalised artifact
from them.

## Format changes across seasons

| Era | Open / Close column | Puck line | Total |
| --- | --- | --- | --- |
| 2007-08 → 2013-14 | One price per row; the other row of the pair carries a **total as a string** (`5.5u25`) | absent | embedded string, one side only |
| 2014-15 → 2015-16 | Moneyline open/close per side | string form `+1.5(-305)` | embedded, one side only |
| 2016-17 → 2017-18 | same as above, **partial files** (428 and 124 games) | string form | embedded |
| 2018-19 → 2022-23 | Numeric moneyline open and close, both sides | numeric line + price | numeric `OpenOU` / `CloseOU` with prices |

Only the last era is a complete two-sided market. Before 2018-19 the moneyline is numeric on
roughly one row in two (≈50-60% of rows), so **no-vig probabilities cannot be computed for
those seasons** — the opposite side is carrying a total instead of a price.

## Measured coverage

Games = paired rows. Percentages are share of rows carrying that field.

| Season | Games | ML | Puck line | Total open | Total close |
| --- | --- | --- | --- | --- | --- |
| 2007-08 | 1,315 | 55% | 0% | 23% | 0% |
| 2008-09 | 1,317 | 59% | 0% | 31% | 0% |
| 2009-10 | 1,318 | 55% | 0% | 31% | 0% |
| 2010-11 | 1,319 | 53% | 0% | 34% | 0% |
| 2011-12 | 1,315 | 54% | 0% | 29% | 0% |
| 2012-13 | 806 | 50% | 0% | 25% | 0% |
| 2013-14 | 1,323 | 54% | 0% | 28% | 0% |
| 2014-15 | 1,319 | 55% | 100% | 25% | 0% |
| 2015-16 | 1,321 | 56% | 100% | 17% | 0% |
| 2016-17 | 428 | 56% | 100% | 22% | 0% |
| 2017-18 | 124 | 61% | 100% | 29% | 0% |
| 2018-19 | 1,358 | 100% | 100% | 100% | 100% |
| 2019-20 | 1,082 | 100% | 100% | 100% | 100% |
| 2020-21 | 952 | 100% | 100% | 100% | 100% |
| 2021-22 | 1,401 | 100% | 100% | 100% | 100% |
| 2022-23 | 339 | 100% | 100% | 100% | 100% |

The five complete-market seasons hold 5,132 artifact rows; 1 row in 2020-21 is missing `final`, so
5,131 are complete on every field — the count used in the benchmark table below.

2022-23 is a partial file: 339 of ~1,312 games. 2019-20 and 2020-21 are short seasons for
real-world reasons (COVID), not data gaps.

## Normalised artifact

`games_2018_2023.jsonl.gz` — one row per game, 5,132 games, **5,131 complete** on moneyline
open and close, puck line, and total open and close. Fields per side: `team`, `final`,
`ml_open`, `ml_close`, `puck_line`, `puck_price`, `ou_open`, `ou_open_price`, `ou_close`,
`ou_close_price`.

Moneyline prices are American. Conversion to no-vig: implied probability per side, then
normalise the pair to sum to one.

## The market benchmark

No-vig moneyline Brier on the normalised artifact, pooled 5,131 games:

| Season | Games | Brier |
| --- | --- | --- |
| 2018-19 | 1,358 | 0.24150 |
| 2019-20 | 1,082 | 0.24323 |
| 2020-21 | 951 | 0.23169 |
| 2021-22 | 1,401 | 0.22562 |
| 2022-23 | 339 | 0.23897 |
| **Pooled** | **5,131** | **0.23554** |

Any model claim of a "good" NHL Brier is meaningless without this number. A model at 0.24 is
one thousandth of a Brier point from the closing market, not a strong model.

## How the prices may be used

Three distinct objects, never interchangeable:

1. **Closing price** — a benchmark for prediction quality. Compare model probabilities against
   the no-vig close on the identical games.
2. **Opening price** — a study of opening-to-closing movement, and whether the model agrees
   more with the opener or the close.
3. **The price we could actually have bet** — **not present.** The archive has no intraday
   timestamps, so there is no T−90 observation and no way to reconstruct what was available
   before puck drop. A closing price must never be presented as a price the model could have
   taken earlier in the day.

Backtests at "historical prices" are therefore restricted to pre-game open and close, and any
strategy result must say which of the two it used.

## Known gaps

- Nothing after 2022-23. 2023-24 onward needs a different source.
- No timestamps: open and close only, and "close" is whatever SBR recorded, not necessarily
  the final pre-game price at a named book.
- Puck line has a single price, not an open/close pair.
- 2016-17 and 2017-18 are truncated snapshots; do not use them as full seasons.
- Team names are SBR's own spellings (`SanJose`, `TampaBay`, `SeattleKraken`) and need mapping
  before joining to any other source.
- Overtime and shootout are included in `Final`, which matches how the moneyline settles, but
  a totals or puck-line study must state whether regulation-only is required.

## Reproduction

```
python parse_sbr.py            # reads /root/lp-data/nhl-sbr/*.xlsx, rewrites the jsonl
```

The script prints the paired-game count and the share with a complete market. It does not
download anything; the xlsx files must be fetched from the Wayback URLs above first.
