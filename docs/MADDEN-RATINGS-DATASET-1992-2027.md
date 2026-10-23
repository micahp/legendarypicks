# Madden NFL player ratings dataset (1992-2027)

Full player-ratings extraction from https://nfldraftbuzz.com/madden/, scraped 2026-10-22.

Data files live outside this repo, in the workspace scraper folder
`nfldraftbuzz-madden/` (bundle: `madden_ratings_1992-2027.zip`). This document is the
spec: what the dataset contains, its columns, its known gaps, and what has been
verified against the source.

## Contents

| File | What it is |
|---|---|
| `out/madden_ratings_long.csv` | 58,743 rows x 73 columns. One row per player per Madden release, all attributes. |
| `out/by_year/madden_<year>.csv` | 36 files, 1992 to 2027. Same rows sliced per release, for "year by year" work. |
| `out/madden_player_seasons.db` | SQLite. `ratings` table (same data) + `players` table (career span, peak OVR, teams). Indexed on player_id and madden_release. |
| `out/coverage.json` | Per-column non-null counts, recomputed on every build. |
| `out/source_limits.json` | Every validator-flagged property that is a source limit, with counts, evidence and consumer options. |
| `checks/` + `verify_evidence.py` | Frozen raw table rows (48 files, 26 player-seasons) and an offline script that recounts them. This is the evidence behind the attribute-density claims. |
| `checks/blanks/` + `verify_blanks.py` | The raw `<td class="mr-team">` for **all 325** blank-team rows, plus an offline script that checks each one is empty at the source while the row still carries ratings. |
| `audit_bundle.py`, `source_limits.py` | The offline audit and the limits-file generator, so both can be re-run on your side. |

Numbers:

- 12,570 players, 58,743 player-seasons
- 36 releases: Madden NFL 1992 through Madden NFL 2027
- 60 attribute columns (OVR, SPEED ... KRN) + 13 identity columns = 73
- OVR on 58,345 rows: 50,203 EA-published, 8,142 calculated by the site
- 32 franchise slugs, plus 23 `fa` rows and 325 rows where the source cell is empty

## Columns

Identity: `player_id`, `player_name`, `slug`, `madden_release`, `dupe_seq` (see below),
`nfl_season` (the season the ratings cover, e.g. Madden 2026 = 2025 NFL season),
`team`, `team_inferred`, `team_inferred_ambiguous`, `POS`, `source`, `site_calculated`, `value_flags`.

`team` is the site's franchise slug, lowercased. Two non-franchise values exist:
`fa` where the source prints the free-agent marker (23 rows), and empty where the
source cell is empty (325 rows, 280 of them in 2005-2012). Blank never means "we
failed to look": all 325 cells were re-fetched and frozen, see the team-cell note.

`team_inferred` is set on 93 of those blank rows, where the site names a franchise
elsewhere on the player page (profile Team field, milestone line, or heading) and the
player has exactly one franchise in his known seasons, so the season is unambiguous.
`team_inferred_ambiguous` is set on a further 20 rows where the page names a team but
the player has several franchises, so the signal does not fix that season. `team` is
never overwritten by either column.

`site_calculated` lists attributes on that row whose value nfldraftbuzz computed
itself. Only ever `OVR`: EA published no overall for Madden 1992-1996 and 1998-2000,
so the site derives one (its own tooltip: "Calculated overall (average of player's two
best ratings)") and marks it with an asterisk. 8,142 rows. Filter
`WHERE site_calculated = ''` for EA-published numbers only.

`value_flags` names attributes outside EA's 0-99 scale as `ATTR=value`; non-empty on
10 rows (11 cells), all Madden 1997. Values are never rewritten, only flagged.

`player_name` comes from the player page heading with the site's `WR - Buccaneers`
suffix stripped; `Jr.` and hyphenated names preserved.

Attributes, in the site's shorthand:

`OVR, SPEED, ACC, AGI, COD, STR, JMP, STA, INJ, TGH, AWR, PRC, THP, TAC, TAS, TAM, TAD,
PAC, TOR, TUP, BSK, CAR, BTK, TRK, BCV, SFA, SPM, JKM, CTH, SPC, CIT, SRR, MRR, DRR,
RLS, RBK, RBP, RBF, PBK, PBP, PBF, IBL, LBK, TAK, POW, PUR, BSH, PMV, FMV, MCV, ZCV,
PRS, KPW, KAC, KRN, RUN, ELU, RR, RTE, THA`

A blank cell means the site shows `-` there ("not tracked in Madden <year>").

## Notes and gotchas

- **Team cells are not all badges.** Most rows link the franchise; some render it as
  plain text inside `td.mr-team` with no image and no anchor (`<span>NY JETS</span>`),
  and a few hundred leave the cell empty. The parser reads all three forms; a
  text-only cell is mapped to its slug, `FA` to `fa`, empty to empty. This is why
  2027 shows 32 teams and not 30: Giants and Jets rows are text-only.
- **Two sources, merged.** Player career pages are primary (51,356 rows, full
  attribute set). Team-season pages added 7,387 seasons no player page carried
  (short-career players); `source` column says which.
- **Attribute aliases normalized** from team-page headers: `SPD->SPEED`, `SAC->TAS`,
  `MAC->TAM`, `DAC->TAD`, `TUF->TGH` (verified equal on overlapping players).
  `RUN`, `RR`, `RTE`, `THA` exist only on team pages and stay as their own columns.
- **`TAC` is not `THA` and must not be merged.** Never co-occurs with `THA`, carries
  kicker and punter values (2012: 124 rows, 31 K and 25 P), sits ~13 points above the
  depth-chart average. It is the site's generic accuracy label for 1992-2004: throw
  accuracy for quarterbacks, kick accuracy for specialists.
- **11 cells read 100, all Madden 1997** (TAK x3, CTH x4, RBK x2, PBK x1, AWR x1 over
  10 rows). Verified in the source HTML. Every other release tops out at 99, so this
  is the site's defect; flagged in `value_flags`, not clamped.
- **40 player-releases appear twice** (mid-season team changes, one row per stint:
  William Perry 1994 Bears 46 / Eagles 69, Mel Gray 1998, Mike Williams 2013 teamless
  78 / Seahawks 76). Both kept; `dupe_seq` makes `(player_id, madden_release, dupe_seq)`
  unique.
- **325 rows have an empty team cell**: 2012 95, 2005 58, 2009 47, 2006 46, 2007 41,
  2008 34, 2013 4, none in 2027. Checked row by row against the site, not sampled: all
  325 raw cells are frozen in `checks/blanks/`, and every one is an empty
  `<td class="mr-team">` with no text, no badge and no link, while its row keeps its
  numeric ratings. 324 of the 325 are the only row for that player-release; the 325th is
  Mike Williams 2013, whose other row carries Seattle. Only 1 of the 325 appears on a
  team-season roster page.
  The cell is empty far more often than the site is: 113 of the 325 name a franchise
  elsewhere on the page - the profile panel's Team field (all 113), a milestone line such as
  "Played for the Chargers across every Madden release in his career" (93 of the 113),
  or the heading (11 of them). 93 of those are single-franchise players, filed in `team_inferred`;
  20 are multi-team players where the season stays ambiguous, filed in
  `team_inferred_ambiguous`. The remaining 212 rows belong to players whose every
  season is teamless: no profile team, no milestone, no heading team, no roster page.
  All of it is captured in `checks/blank_signals.json`.
- **Team slugs follow the site's per-season franchise slug**, so `raiders` covers the
  Oakland years, `rams` St. Louis, `titans` the Oilers. 32 franchises.
- **Coverage caveat.** The site claims "40,725 players - 69,861 player-seasons".
  Every player page in its sitemap and every team-season roster page was crawled
  (12,570 + 1,043 pages, 0 failures); this dataset is what exists at those URLs.

## Coverage by release

Sparse years are the source's shape, not scrape loss. The `checks/` folder freezes the
raw rows and `verify_evidence.py` recounts them offline: numeric rating cells in the
page match stored values exactly (2008 156/156, 2009 159/159, 2010 66/66, 2011
168/168, 2012 83/83, 2013 168/168).

| Releases | Rows/yr | Players/team | Attributes | OVR |
|---|---|---|---|---|
| 1992-1996 | 811-1,331 | 29-44 | 16 | calculated by the site, 95-97% of rows |
| 1997 | 1,323 | 44 | 26 | EA-published |
| 1998-2000 | 1,168-1,250 | 39-41 | 26, thin rows | calculated by the site, ~95% |
| 2001-2012 | 1,416-1,635 | 45-51 | 18-52, uneven | EA-published |
| 2010 and 2012 | 1,632 / 1,471 | 51 / 46 | 18 and 47 columns, 12.2 and 16.5 cells per row | EA-published |
| 2013-2026 | 1,960-2,195 | 61-69 | 55-59 | EA-published |
| 2027 | 1,531 | 51 | 54 | EA-published (32 teams, partial roster) |

Madden 2010 and 2012 are genuinely thin at the source (12.2 and 16.5 populated cells
per row against ~38 in surrounding years). Team-season pages for those years are
thinner still - Stafford 2010 has 10 attributes on his team page against 12 on his
player page - so no richer source exists. `checks/` freezes both rows for that
comparison.

Team counts per release match the league: 28 teams 1992-1994, 30 in 1996-2000, 31 in
2001-2002, 32 from 2003.

## Validation

`audit_bundle.py` (offline, no network): zip freshness, team casing and blanks,
duplicate keys, `coverage.json` vs CSV, CSV vs SQLite cell-for-cell. Last run: 0 stale
entries, 0 mixed-case teams, 325 blanks, 40 duplicate keys with distinct `dupe_seq`,
0 of 60 attribute counts disagreeing, 0 cell diffs.

`verify_evidence.py` (offline): recounts the 48 frozen table rows in `checks/` and
diffs them against the CSV. Last run: 26/26 player-seasons match, every team-page row
thinner than its player-page row, exit 0.

`verify_blanks.py` (offline): re-parses all 325 frozen team cells and asserts each is
empty (no text, image or link) while its row still has numeric ratings, that the CSV
agrees on every key, and that the `team_inferred` / `team_inferred_ambiguous` columns
match `checks/blank_signals.json`. Last run: 325/325, PASS, exit 0.

Page signals are harvested by `harvest_blank_signals.py`, which needs network; the
build order is `build_dataset.py` -> `harvest_blank_signals.py` -> `build_dataset.py`,
and the harvested file is shipped so the second build is reproducible offline.

`source_limits.py` regenerates `out/source_limits.json` from the data, so the limits
file can never drift from the bundle.

`spotcheck.py` re-fetches 20 random players from the live site and diffs every
attribute; last run 84 seasons, 0 mismatches. Needs network, so the offline guarantees
come from the three scripts above.

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
