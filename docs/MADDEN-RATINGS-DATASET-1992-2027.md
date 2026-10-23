# Madden NFL player ratings dataset (1992-2027)

Full player-ratings extraction from https://nfldraftbuzz.com/madden/, scraped 2026-10-22.

Data files live outside this repo, in the workspace scraper folder
`nfldraftbuzz-madden/` (bundle: `madden_ratings_1992-2027.zip`). This document is the
spec: what the dataset contains, its columns, and its known gaps.

Every player rating the site publishes, for every Madden NFL release they appear in,
with every attribute column the site shows.

## Contents

| File | What it is |
|---|---|
| `out/madden_ratings_long.csv` | 58,743 rows × 73 columns. One row per player per Madden release, all attributes. |
| `out/by_year/madden_<year>.csv` | 36 files, 1992 → 2027. Same rows sliced per release, for "year by year" work. |
| `out/madden_player_seasons.db` | SQLite. `ratings` table (same data) + `players` table (career span, peak OVR, teams). Indexed on player_id and madden_release. |
| `out/coverage.json` | The counts below, machine-readable. |

Numbers:

- 12,570 players
- 58,743 player-seasons
- 36 releases: Madden NFL 1992 through Madden NFL 2027
- 60 attribute columns (OVR, SPEED … KRN) + 5 identity columns
- 50,203 rows have an OVR (older releases shipped no OVR at all - see Notes)
- 0 rows where OVR, SPEED and AWR are all empty

## Columns

Identity: `player_id` (site id), `player_name`, `slug` (site URL slug),
`madden_release` (year in the game title), `nfl_season` (the season the ratings cover,
e.g. Madden 2026 = 2025 NFL season), `team`, `POS`, `source`.

Attributes, in the site's own shorthand:

`OVR, SPEED, ACC, AGI, COD, STR, JMP, STA, INJ, TGH, AWR, PRC, THP, TAC, TAS, TAM, TAD,
PAC, TOR, TUP, BSK, CAR, BTK, TRK, BCV, SFA, SPM, JKM, CTH, SPC, CIT, SRR, MRR, DRR,
RLS, RBK, RBP, RBF, PBK, PBP, PBF, IBL, LBK, TAK, POW, PUR, BSH, PMV, FMV, MCV, ZCV,
PRS, KPW, KAC, KRN, RUN, ELU, RR, RTE, THA`

Blank cell = the site shows `-` for that attribute in that release ("not tracked in
Madden <year>"). That is real absence, not a scrape gap.

## Notes / gotchas

- **Two sources, merged.** Player career pages (`/madden/player/<id>-<slug>`) are the
  primary source: 51,356 rows, full attribute set. Team-season pages
  (`/madden/team/<team>/<year>`) added 7,387 seasons that no player page carried
  (mostly short-career players), flagged in the `source` column as `team_page`.
- **Attribute aliases normalized.** Team pages use different headers than player pages:
  `SPD→SPEED`, `SAC→TAS`, `MAC→TAM`, `DAC→TAD`, `TUF→TGH` (verified equal values on
  overlapping players). `RUN`, `RR`, `RTE`, `THA` only ever appear on team pages and are
  left as their own columns rather than guessed into another bucket.
- **Old releases have no OVR.** Madden 1992-1996 era pages carry only a handful of
  attributes (SPD/AGI/AWR/…), no overall. Those rows have `OVR` blank.
- **`team`** is the franchise slug the site uses for that season, so historical names
  differ (`raiders` vs the Oakland years, `rams` vs St. Louis, `titans` vs `oilers`).
  64 distinct slugs appear in total.
- **Coverage caveat.** The site's own copy claims "40,725 players · 69,861 player-seasons".
  Every player page reachable from its sitemap and every team-season roster page was
  crawled (12,570 player pages, 1,043 team-season pages, 0 fetch failures), and this
  dataset is the total that actually exists at those URLs: 12,570 players, 58,743
  seasons. The higher figure appears to count prospects/other DB entries that have no
  Madden ratings page.
- Verified by re-fetching 20 random players live after the build: 84 seasons, 0
  mismatches on any attribute.

## Quick queries

```sql
-- one player's whole career
SELECT madden_release, team, OVR, SPEED, AWR FROM ratings
WHERE player_name = 'Tom Brady' ORDER BY madden_release;

-- biggest OVR jumps season over season
SELECT player_name, madden_release, OVR,
       OVR - LAG(OVR) OVER (PARTITION BY player_id ORDER BY madden_release) AS delta
FROM ratings WHERE OVR IS NOT NULL
ORDER BY delta DESC LIMIT 20;
```

Reproduce with `phase1_teams.py` → `phase2_players.py` → `build_dataset.py`
(fetch layer in `crawl.py`, `spotcheck.py` re-verifies against the live site).
