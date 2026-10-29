# SLC streak buckets: record and points, by era (2026-10-29)

Research, descriptive. The output of `scripts/nfl_sequence/streak_buckets_report.py --cutoff 2026`. It reads regular-season
games from 2010 to 2025 only (4,175 games, every one with a final score in `nfl_schedule`). 2026 is not read.

## Buckets

Eleven individual buckets: W1 to W4, W5+ (five or more wins in a row), NONE, L1 to L4, and L5+ (five or more losses). A team's
state going into a game is the run it carries in from its earlier games that season. The streak resets each season, and a tie
breaks it. Each team-game counts once, in the bucket it carried into that game.

## What the table is, and is not

This is the record and the points that each streak state went with. It is a description of results. A team on a long win streak
is usually a good team, and a team on a long losing streak is usually a bad one, so these numbers carry team quality, schedule and
game script. They do not measure what a streak does to a team's play.

The play-call streak splits (`streak_splits.py`, off by default) measure a different thing: the dropback rate in each bucket
relative to the team's own overall rate. That is what enters the model, and this table does not feed it.

## What the record shows

- Win share rises with the streak length in every era. W5+ won 0.669, 0.694 and 0.641 of its games in 2010-2015, 2016-2020 and
  2021-2025. L5+ won 0.320, 0.282 and 0.303.
- Points follow the same ordering. W5+ teams scored 25.9, 26.7 and 25.8 per game and allowed 19.8, 19.3 and 21.9. L5+ teams
  scored 18.9, 18.6 and 17.3 per game and allowed 24.6, 24.0 and 24.8.
- The middle is flat and not monotone. NONE, L1, W1 and W2 sit within a few points of win share of each other, and the order
  among them changes between eras (for example NONE is below L1 in 2010-2015 and above it in 2016-2020).
- The end buckets are small: about 110 to 150 team-games each per era. For a win share near 0.5, the 95% interval is about
  plus or minus 0.09 for those buckets, and about plus or minus 0.04 for L1 (718 team-games in 2010-2015).

## Tables

Team-games are team-game rows. PF and PA are points scored and allowed, totals and per game. Margin per game is PF/g minus PA/g.
The ALL row in each era sums to zero margin, which is a check that every game was counted once for each side.

### 2010-2015

| bucket | team-games | W | L | T | win share | PF total | PA total | PF/g | PA/g | margin/g |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| L5+ | 150 | 48 | 102 | 0 | 0.32 | 2834 | 3691 | 18.893 | 24.607 | -5.713 |
| L4 | 83 | 22 | 61 | 0 | 0.2651 | 1567 | 2025 | 18.88 | 24.398 | -5.518 |
| L3 | 157 | 66 | 89 | 2 | 0.4204 | 3390 | 3805 | 21.592 | 24.236 | -2.643 |
| L2 | 329 | 158 | 171 | 0 | 0.4802 | 7205 | 7590 | 21.9 | 23.07 | -1.17 |
| L1 | 718 | 367 | 349 | 2 | 0.5111 | 16489 | 16187 | 22.965 | 22.545 | 0.421 |
| NONE | 198 | 98 | 100 | 0 | 0.4949 | 4405 | 4469 | 22.247 | 22.571 | -0.323 |
| W1 | 716 | 356 | 359 | 1 | 0.4972 | 16256 | 16294 | 22.704 | 22.757 | -0.053 |
| W2 | 331 | 181 | 149 | 1 | 0.5468 | 7695 | 7099 | 23.248 | 21.447 | 1.801 |
| W3 | 173 | 98 | 75 | 0 | 0.5665 | 4232 | 3811 | 24.462 | 22.029 | 2.434 |
| W4 | 87 | 52 | 35 | 0 | 0.5977 | 2086 | 1972 | 23.977 | 22.667 | 1.31 |
| W5+ | 130 | 87 | 43 | 0 | 0.6692 | 3361 | 2577 | 25.854 | 19.823 | 6.031 |
| ALL | 3072 | 1533 | 1533 | 6 | 0.499 | 69520 | 69520 | 22.63 | 22.63 | 0.0 |

### 2016-2020

| bucket | team-games | W | L | T | win share | PF total | PA total | PF/g | PA/g | margin/g |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| L5+ | 124 | 35 | 89 | 0 | 0.2823 | 2308 | 2975 | 18.613 | 23.992 | -5.379 |
| L4 | 75 | 31 | 44 | 0 | 0.4133 | 1575 | 1863 | 21.0 | 24.84 | -3.84 |
| L3 | 145 | 62 | 83 | 0 | 0.4276 | 3187 | 3581 | 21.979 | 24.697 | -2.717 |
| L2 | 284 | 126 | 156 | 2 | 0.4437 | 6469 | 6853 | 22.778 | 24.13 | -1.352 |
| L1 | 566 | 268 | 297 | 1 | 0.4735 | 12789 | 13151 | 22.595 | 23.235 | -0.64 |
| NONE | 172 | 83 | 85 | 4 | 0.4826 | 3923 | 3942 | 22.808 | 22.919 | -0.11 |
| W1 | 566 | 313 | 250 | 3 | 0.553 | 13465 | 12710 | 23.79 | 22.456 | 1.334 |
| W2 | 297 | 153 | 143 | 1 | 0.5152 | 7016 | 6964 | 23.623 | 23.448 | 0.175 |
| W3 | 147 | 82 | 64 | 1 | 0.5578 | 3494 | 3277 | 23.769 | 22.293 | 1.476 |
| W4 | 73 | 44 | 29 | 0 | 0.6027 | 1914 | 1652 | 26.219 | 22.63 | 3.589 |
| W5+ | 111 | 77 | 34 | 0 | 0.6937 | 2965 | 2137 | 26.712 | 19.252 | 7.459 |
| ALL | 2560 | 1274 | 1274 | 12 | 0.4977 | 59105 | 59105 | 23.088 | 23.088 | 0.0 |

### 2021-2025

| bucket | team-games | W | L | T | win share | PF total | PA total | PF/g | PA/g | margin/g |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| L5+ | 119 | 36 | 82 | 1 | 0.3025 | 2058 | 2947 | 17.294 | 24.765 | -7.471 |
| L4 | 84 | 31 | 53 | 0 | 0.369 | 1567 | 1842 | 18.655 | 21.929 | -3.274 |
| L3 | 157 | 67 | 90 | 0 | 0.4268 | 3199 | 3537 | 20.376 | 22.529 | -2.153 |
| L2 | 294 | 134 | 159 | 1 | 0.4558 | 6256 | 6856 | 21.279 | 23.32 | -2.041 |
| L1 | 621 | 308 | 311 | 2 | 0.496 | 14289 | 14203 | 23.01 | 22.871 | 0.138 |
| NONE | 168 | 81 | 85 | 2 | 0.4821 | 3645 | 3693 | 21.696 | 21.982 | -0.286 |
| W1 | 619 | 299 | 320 | 0 | 0.483 | 13951 | 14217 | 22.538 | 22.968 | -0.43 |
| W2 | 282 | 168 | 114 | 0 | 0.5957 | 6736 | 5799 | 23.887 | 20.564 | 3.323 |
| W3 | 161 | 102 | 58 | 1 | 0.6335 | 4168 | 3548 | 25.888 | 22.037 | 3.851 |
| W4 | 96 | 54 | 41 | 1 | 0.5625 | 2302 | 1985 | 23.979 | 20.677 | 3.302 |
| W5+ | 117 | 75 | 42 | 0 | 0.641 | 3016 | 2560 | 25.778 | 21.88 | 3.897 |
| ALL | 2718 | 1355 | 1355 | 8 | 0.4985 | 61187 | 61187 | 22.512 | 22.512 | 0.0 |

### all seasons

| bucket | team-games | W | L | T | win share | PF total | PA total | PF/g | PA/g | margin/g |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| L5+ | 393 | 119 | 273 | 1 | 0.3028 | 7200 | 9613 | 18.321 | 24.461 | -6.14 |
| L4 | 242 | 84 | 158 | 0 | 0.3471 | 4709 | 5730 | 19.459 | 23.678 | -4.219 |
| L3 | 459 | 195 | 262 | 2 | 0.4248 | 9776 | 10923 | 21.298 | 23.797 | -2.499 |
| L2 | 907 | 418 | 486 | 3 | 0.4609 | 19930 | 21299 | 21.974 | 23.483 | -1.509 |
| L1 | 1905 | 943 | 957 | 5 | 0.495 | 43567 | 43541 | 22.87 | 22.856 | 0.014 |
| NONE | 538 | 262 | 270 | 6 | 0.487 | 11973 | 12104 | 22.255 | 22.498 | -0.243 |
| W1 | 1901 | 968 | 929 | 4 | 0.5092 | 43672 | 43221 | 22.973 | 22.736 | 0.237 |
| W2 | 910 | 502 | 406 | 2 | 0.5516 | 21447 | 19862 | 23.568 | 21.826 | 1.742 |
| W3 | 481 | 282 | 197 | 2 | 0.5863 | 11894 | 10636 | 24.728 | 22.112 | 2.615 |
| W4 | 256 | 150 | 105 | 1 | 0.5859 | 6302 | 5609 | 24.617 | 21.91 | 2.707 |
| W5+ | 358 | 239 | 119 | 0 | 0.6676 | 9342 | 7274 | 26.095 | 20.318 | 5.777 |
| ALL | 8350 | 4162 | 4162 | 26 | 0.4984 | 189812 | 189812 | 22.732 | 22.732 | 0.0 |

## Reproduce

`python3 scripts/nfl_sequence/streak_buckets_report.py --cutoff 2026 --out <json>`. The unit tests for the bucket rules are in
`scripts/nfl_sequence/test_streak_splits.py`.
