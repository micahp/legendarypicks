# WTA seed labels across the archive (1960 to 2026)

Source: scratch-wta-split.db, table tennis_wta_matches. Read-only. No external lists used.
Host country for the same-named check is a hand-entered rule for 12 tournament names only (Australian cities are AUS, the rest USA).

## Check 1: same-round collisions

Two different players with the same seed label in the same event and round. Qualifying rounds (Q1 to Q3) excluded.

| Decade | Label-round groups | Collisions |
|---|---|---|
| 1960s | 1,545 | 25 |
| 1970s | 8,445 | 61 |
| 1980s | 19,094 | 48 |
| 1990s | 48,157 | 110 |
| 2000s | 76,008 | 22 |
| 2010s | 98,467 | 49 |
| 2020s | 50,780 | 12 |

Collisions from 1980 onward by round: R32 144 (110 events), R16 57 (56 events), R64 18 (14), R128 11 (6), SF 8 (8), RR 2 (1), F 1 (1).
Example: Wimbledon 1985, R32, seed 1, both Chris Evert and Martina Navratilova.

## Check 2: multi-label player-events

One player with more than one seed label inside one event.

| Decade | Player-events | With conflict |
|---|---|---|
| 1960s | 618 | 16 |
| 1970s | 3,375 | 43 |
| 1980s | 11,204 | 16 |
| 1990s | 28,390 | 4 |
| 2000s | 41,032 | 3 |
| 2010s | 54,234 | 4 |
| 2020s | 59,426 | 63 |

The 63 conflicts in the 2020s have not been inspected yet.

## Event classes, 1960 to 1979

| Class | Events | Collision groups | Conflicted player-events |
|---|---|---|---|
| has_F: at least one F label observed | 21 | 6 | 7 |
| F_era_plain_only: 1968-01-01 to 1971-02-28, no F label | 141 | 25 | 15 |
| post_F_era_plain_only: after 1971-02-28, no F label | 461 | 55 | 37 |

No seeded events appear before 1968 in this data.

F labels appear in exactly 21 events in the whole archive, all between 1968-01-02 and 1971-02-26.

## Same-named events, 1966 to 1975, with no F label

Plain-labelled sides from players outside the host country, in events with no F label:

| Date | Event | Non-host plain sides |
|---|---|---|
| 1968-07-08 | Indianapolis | 3 |
| 1969-01-01 | Perth | 7 |
| 1969-01-06 | Melbourne | 3 |
| 1969-01-13 | Sydney | 16 |
| 1970-01-05 | Hobart | 4 |
| 1970-01-12 | Melbourne | 6 |
| 1970-03-16 | Sydney | 7 |
| 1970-07-20 | Cincinnati | 11 |

Events after February 1971 show many non-host plain sides too (for example Cincinnati 1971-08-02, 20 sides), but no F label exists after 1971-02-26 anywhere in the archive. That pattern is consistent with ordinary single-list seeding.

## Open

- The 63 conflicts in the 2020s are not inspected.
- The cause of post-1979 collisions is unknown.
- The external corrections (King, Eisel, Wade, Hogan, Sherriff, Sawamatsu, Defina) remain unverified.
