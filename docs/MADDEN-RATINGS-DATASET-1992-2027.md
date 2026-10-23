# Madden NFL player ratings dataset (1992-2027)

Full player-ratings extraction from https://nfldraftbuzz.com/madden/, scraped 2026-10-22.

Data files live outside this repo, in the workspace scraper folder
`nfldraftbuzz-madden/` (bundle: `madden_ratings_1992-2027.zip`). This document is the
spec: what the dataset contains, its columns, its known gaps, and what has been
verified against the source.

Every player rating the site publishes, for every Madden NFL release they appear in,
with every attribute column the site shows.

## Contents

| File | What it is |
|---|---|
| `out/madden_ratings_long.csv` | 58,743 rows x 70 columns. One row per player per Madden release, all attributes. |
| `out/by_year/madden_<year>.csv` | 36 files, 1992 to 2027. Same rows sliced per release, for "year by year" work. |
| `out/madden_player_seasons.db` | SQLite. `ratings` table (same data) + `players` table (career span, peak OVR, teams). Indexed on player_id and madden_release. |
| `out/coverage.json` | Per-column non-null counts, recomputed on every build. |

Numbers:

- 12,570 players
- 58,743 player-seasons
- 36 releases: Madden NFL 1992 through Madden NFL 2027
- 60 attribute columns (OVR, SPEED ... KRN) + 10 identity columns = 70
- OVR present on 58,345 rows: 50,203 EA-published, 8,142 calculated by the site
- 32 franchise slugs, plus 454 rows where the source shows no team

## Columns

Identity: `player_id` (site id), `player_name`, `slug` (site URL slug),
`madden_release` (year in the game title), `dupe_seq` (see below),
`nfl_season` (the season the ratings cover, e.g. Madden 2026 = 2025 NFL season),
`team`, `POS`, `source`, `site_calculated`.

`player_name` comes from the player page heading, with the site's `WR - Buccaneers`
position/team suffix stripped; suffixes like `Jr.` and hyphenated names are preserved.

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

## Notes and gotchas

- **Two sources, merged.** Player career pages (`/madden/player/<id>-<slug>`) are the
  primary source: 51,356 rows, full attribute set. Team-season pages
  (`/madden/team/<team>/<year>`) added 7,387 seasons that no player page carried
  (mostly short-career players), flagged in the `source` column as `team_page`.
- **Attribute aliases normalized.** Team pages use different headers than player pages:
  `SPD->SPEED`, `SAC->TAS`, `MAC->TAM`, `DAC->TAD`, `TUF->TGH` (verified equal values on
  overlapping players). `RUN`, `RR`, `RTE`, `THA` only ever appear on team pages and are
  left as their own columns rather than guessed into another bucket.
- **`TAC` is not `THA` and must not be merged.** It never co-occurs with `THA` on a row,
  carries kicker and punter values (2012: 124 rows, 31 K and 25 P), and reads about 13
  points above the depth-chart average. It is the site's generic "accuracy" label for
  the 1992-2004 era: throw accuracy for quarterbacks, kick accuracy for specialists.
  `THA` is the later-era throw-accuracy column on team pages only.
- **11 cells read exactly 100, all in Madden 1997** (TAK x3, CTH x4, RBK x2, PBK x1,
  AWR x1). Verified in the source HTML: the site publishes those numbers. Not clamped
  or altered here; Madden 1997 shipped on a 0-99 scale, so treat these as the site's
  own cap artifact.
- **40 player-releases appear twice.** The source lists a player once per team when he
  changed teams mid-season (William Perry 1994: Bears 46 OVR / Eagles 69 OVR; Mel Gray
  1998; Mike Williams 2013 has one teamless row at 78 and a Seahawks row at 76). Both
  rows are kept; `dupe_seq` numbers them so
  `(player_id, madden_release, dupe_seq)` is a unique key.
- **454 rows have no team.** The source shows no team badge for those rows and none is
  invented here. 106 of them are in Madden 2027, and 60 of those belong to Giants and
  Jets players (by their 2026 roster): both franchises' 2027 team pages are stubs that
  return an empty table, which is also why 2027 shows 30 teams rather than 32.
- **Madden 2027 is partial.** 1,531 rows, 30 team pages, no Giants or Jets rosters on
  the site. Do not treat 2027 as a complete release.
- **Team slugs are the site's per-season franchise slug**, lowercased, so historical
  names differ (`raiders` covers the Oakland years, `rams` St. Louis, `titans` the
  Oilers). 32 non-blank slugs in total.
- **Coverage caveat.** The site's own copy claims "40,725 players - 69,861
  player-seasons". Every player page reachable from its sitemap and every team-season
  roster page was crawled (12,570 player pages, 1,043 team-season pages, 0 fetch
  failures), and this dataset is the total that actually exists at those URLs. The
  higher figure appears to count prospects and other non-Madden database entries.

## Coverage by release

Rows per release, players per team, and how many of the 60 attributes exist in that era.
The sparse years are the source's shape, not scrape loss: a sample of 2008-2013 pages
was re-read and the numeric rating cells in the raw HTML match the stored values
exactly (2008: 156 cells for 4 players, 2010: 54, 2011: 168, 2012: 65).

| Releases | Rows/yr | Players/team | Attributes available | OVR |
|---|---|---|---|---|
| 1992-1996 | 811-1,331 | 29-44 | 16 (SPD, AGI, STR, AWR, THP, TAC, CAR, BTK, CTH, RBK, PBK, TAK, PUR, MCV, KPW, KAC) | calculated by the site, 95-97% of rows |
| 1997 | 1,323 | 44 | 26 | EA-published |
| 1998-2000 | 1,168-1,250 | 39-41 | 26, thin rows | calculated by the site, ~95% |
| 2001-2012 | 1,416-1,635 | 45-51 | 18-52, uneven | EA-published |
| 2010 and 2012 | 1,632 / 1,471 | 51 / 46 | 18 and 47 columns, 12.2 and 16.5 populated cells per row | EA-published |
| 2013-2026 | 1,960-2,195 | 61-69 | 55-59 | EA-published |
| 2027 | 1,531 | 51 | 54 | EA-published (partial release, 30 teams on the site) |

Madden 2010 and 2012 are genuinely thin at the source: the site tracks a reduced
attribute set for those releases (12.2 and 16.5 populated cells per row against ~38
in the surrounding years). 2012 is uneven rather than reduced, 47 columns present
across the release but sparsely filled.

So: modern-era coverage is effectively complete at roughly full 53-man-plus rosters
per team every year. 1992-2000 is thinner because the site itself holds fewer players
and fewer attributes for those releases and its OVR for those years is a calculation,
not EA's number. Treat pre-2001 rows as partial records with a reconstructed overall.

Team counts per release match the real league (28 teams 1992-1994, 30 in 1996-2000,
31 in 2001-2002, 32 from 2003 - the site is missing part of the 2002 Texans squad).

## Validation

`audit_bundle.py` is the offline audit and needs no network: zip freshness, team
casing and blanks, duplicate keys, `coverage.json` vs CSV, and CSV vs SQLite
cell-for-cell. Last run: 0 stale entries, 0 mixed-case teams, 454 blanks, 40 duplicate
keys all carrying distinct `dupe_seq`, 0 of 60 attribute counts disagreeing, 0 cell
diffs.

`spotcheck.py` re-fetches 20 random players from the live site and diffs every
attribute; last run 84 seasons, 0 mismatches. It needs network, so it is not
reproducible offline - the offline guarantee comes from `audit_bundle.py` plus the
per-release numeric-cell comparison above.

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

Reproduce with `phase1_teams.py` -> `phase2_players.py` -> `build_dataset.py`
(fetch layer in `crawl.py`).
