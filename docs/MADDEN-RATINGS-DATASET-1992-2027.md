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
- 60 attribute columns (OVR, SPEED … KRN) + 10 identity columns = 70
- OVR present on 58,345 rows: 50,203 EA-published, 8,142 calculated by the site
- 0 rows where OVR, SPEED and AWR are all empty

## Columns

Identity: `player_id` (site id), `player_name`, `slug` (site URL slug),
`madden_release` (year in the game title), `dupe_seq` (see below),
`nfl_season` (the season the ratings cover, e.g. Madden 2026 = 2025 NFL season),
`team`, `POS`, `source`, `site_calculated`.

`site_calculated` lists, comma-separated, any attribute on that row whose value
nfldraftbuzz computed itself instead of copying from EA. Today that is only ever
`OVR`: EA published no overall for Madden 1992-1996 and 1998-2000, so the site
derives one (its own tooltip: "Calculated overall (average of player's two best
ratings)") and marks it with an asterisk. 8,142 of 58,743 rows carry a calculated
OVR. Filter `WHERE site_calculated = ''` for EA-published numbers only.

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
- **Old releases have no EA-published OVR.** Madden 1992-1996 and 1998-2000 pages
  carry a smaller attribute set and no EA overall; the OVR on those rows is the
  site's own calculation, flagged in `site_calculated`. OVR is present on 58,345
  of 58,743 rows (99%) but only 50,203 of those are EA-published.
- **40 player-releases appear twice.** The source lists a player once per team when
  he changed teams mid-season (William Perry 1994 = Bears row + Eagles row, with
  different ratings for each stint). Both rows are kept; `dupe_seq` numbers them
  (0, 1) so `(player_id, madden_release, dupe_seq)` is a unique key.
- **`team`** is the franchise slug the site uses for that season, lowercased, so
  historical names differ (`raiders` covers the Oakland years, `rams` St. Louis,
  `titans` the Oilers). 33 distinct slugs in total; 453 rows have no team listed
  at the source (free agents / no-team entries).
- **Coverage caveat.** The site's own copy claims "40,725 players · 69,861 player-seasons".
  Every player page reachable from its sitemap and every team-season roster page was
  crawled (12,570 player pages, 1,043 team-season pages, 0 fetch failures), and this
  dataset is the total that actually exists at those URLs: 12,570 players, 58,743
  seasons. The higher figure appears to count prospects/other DB entries that have no
  Madden ratings page.
- Verified by re-fetching 20 random players live after the build: 84 seasons, 0
  mismatches on any attribute.

## Coverage by release

Rows per release, players per team, and how many of the 60 attributes even exist in
that era. This is the shape of the source, not scrape loss:

| Releases | Rows/yr | Players/team | Attributes available | OVR |
|---|---|---|---|---|
| 1992-1996 | 811-1,331 | 29-44 | 16 (SPD, AGI, STR, AWR, THP, TAC, CAR, BTK, CTH, RBK, PBK, TAK, PUR, MCV, KPW, KAC) | calculated by the site, 95-97% of rows |
| 1997 | 1,323 | 44 | 26 | EA-published |
| 1998-2000 | 1,168-1,250 | 39-41 | 26, thin rows | calculated by the site, ~95% |
| 2001-2012 | 1,416-1,635 | 45-51 | 26-52 | EA-published |
| 2013-2026 | 1,960-2,195 | 61-69 | 55-59 | EA-published |
| 2027 | 1,531 | 51 | 54 | EA-published (partial release, 30 teams on the site) |

So: modern-era coverage is effectively complete at roughly full 53-man-plus rosters
per team every year. 1992-2000 is thinner because the site itself holds fewer players
and fewer attributes for those releases - 7-13 populated attribute cells per row against
37-41 in the modern era - and its OVR for those years is a calculation, not EA's number.
Treat pre-2001 rows as partial records with a reconstructed overall.

Team counts per release match the real league (28 teams 1992-1994, 30 in 1996-1999,
31 in 2000-2001, 32 from 2002).

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
