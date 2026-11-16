# 2024 Official Inactives Full-Season Extension

## Output and collection

- Full file: `/tmp/claude-0/-root/4a715766-ff4b-4980-99e5-dc209eaac7d4/scratchpad/avail/inactives/official_inactives_2024_full.jsonl`
- Rows: **3586** (Weeks 1–4 copied into this separate output: 808; Weeks 5–18 and playoffs: 2778). Original Weeks 1–4 files were not modified.
- Coverage: **285/285 games** and **570/570 team-game lists**; missing games: 0; extra games: 0; missing team-games: 0; extra team-games: 0.
- Weeks 5–18 plus playoffs: **52 NFL.com pages** rendered with Playwright Chromium; all page statuses 200; page/team/line parse exceptions: 0. The crawl retained the 5-second interval between page navigations. Regular season: 2024 Weeks 5–18; postseason: Wild Card, Divisional, Conference Championship and Super Bowl.
- Source labels: {'inactive': 3434, 'emergency_qb3': 152}.
- Duplicate published player rows retained: **3 duplicate identity/name keys** (no silent deduplication).
- `publication_time` remains null where the rendered NFL.com page itself showed “Published: Loading…”.

## Independent identity resolution tiers

IDs were resolved against nflverse `players.parquet`, using the player table’s display name, name fields, position, and 2024 career window. Weekly roster membership/status did **not** choose any GSIS ID. The original `roster_match_*` values for Weeks 1–4 remain separate diagnostics; roster status was read only after identity resolution for the comparison below.

Player source: [nflverse players.parquet](https://github.com/nflverse/nflverse-data/releases/download/players/players.parquet), SHA-256 `b4a8a508cd621bfdb4b2e364e1bcee4ab5a945e74fb6a4cfc98af019a50c2812` (24861 rows). Resolved IDs absent from local `nfl_hist_player_ids`: **0**.

| Validation-style tier | Rows |
|---|---:|
| exact display name (`exact_display_name`) | 3305 |
| player-table disambiguated by position and 2024 activity (`player_table_disambiguated`) | 184 |
| player-table name field alias (`player_table_alias`) | 39 |
| player-table spelling/order variant (`player_table_variant`) | 43 |
| official alias crosswalk (`official_alias_crosswalk`) | 13 |
| official source correction (`official_source_correction`) | 2 |
| unresolved / ambiguous | 0 |
| **Total** | **3586** |

The validation script’s `homonym_membership` and `roster_fallback` tiers were not used (**0** each). Unresolved rows: 0. Resolved source rows: 3586 (100.00%).


### Career-window guard

Every resolved GSIS ID was checked against `rookie_season <= 2024 <= last_season`. The guard flagged **1 row** before correction: Week 7 DEN “Patrick Surtain II” had been assigned to retired Patrick Surtain (`00-0015915`, 1998–2008). That ID was rejected and replaced with Pat Surtain II (`00-0036874`, 2021–2026). After correction: **0 career-window violations across 3,586 rows**; no player-table career years were missing.

### Trade-week team attribution

Week 10 Yannick Ngakoue (`00-0033123`) remains attributed to **NE** as published by NFL.com. The weekly roster snapshot carries the same ID under **BAL** with status INA, reflecting the old team in the trade week. This is recorded in the row’s `ambiguity_note` as a team-attribution discrepancy, not an identity-resolution failure.

## Source duplicates and published-name variants

Repeated source rows are retained in the JSONL. The following three keys each occur twice:

| Game | Team | Published name | GSIS ID | Rows |
|---|---|---|---|---:|
| 2024_01_CAR_NO | NO | Dallin Holker | `00-0039613` | 2 |
| 2024_02_LA_ARI | ARI | Dante Stills | `00-0038623` | 2 |
| 2024_17_KC_PIT | KC | Chris Jones | `00-0032762` | 2 |

Published spellings/names remain in `name_as_published`; the canonical player-table name is stored separately. Mappings with a differing published/canonical name are:

| Published | Player-table name | Rows | Resolution tier |
|---|---|---:|---|
| Adoree’ Jackson | Adoree' Jackson | 1 | exact_display_name |
| AJ Arcuri | A.J. Arcuri | 1 | exact_display_name |
| Al-Quadin Muhammed | Al-Quadin Muhammad | 1 | player_table_variant |
| Anthony Johnson | Anthony Johnson Jr. | 7 | player_table_disambiguated |
| Anthony Walker Jr. | Anthony Walker | 3 | exact_display_name |
| Antonie Winfield Jr. | Antoine Winfield Jr. | 1 | player_table_variant |
| Antonio Grier | Antonio Grier Jr. | 1 | exact_display_name |
| Antonio Hamilton Sr. | Antonio Hamilton | 3 | exact_display_name |
| Antonio Mafi | Atonio Mafi | 1 | player_table_variant |
| Ashtyn Adams | Ashtyn Davis | 1 | official_source_correction |
| Audric Estime | Audric Estimé | 1 | exact_display_name |
| ben Brown | Ben Brown | 1 | exact_display_name |
| Bernhard Reimann | Bernhard Raimann | 1 | player_table_variant |
| Boogie Basham | Carlos Basham | 5 | official_alias_crosswalk |
| Brenton Cox | Brenton Cox Jr. | 3 | exact_display_name |
| Brian Robinson Jr. | Brian Robinson | 3 | exact_display_name |
| Britain Convey | Britain Covey | 1 | player_table_variant |
| Byron Murphy | Byron Murphy II | 1 | player_table_disambiguated |
| C.J Hanson | C.J. Hanson | 1 | exact_display_name |
| Carlton Davis | Carlton Davis III | 1 | exact_display_name |
| Ced Johnson | Cedric Johnson | 1 | player_table_alias |
| Cedrick Wilson | Cedrick Wilson Jr. | 1 | player_table_disambiguated |
| Cedric Johnson | Cedric Johnson | 1 | exact_display_name |
| Christopher Hubbard | Chris Hubbard | 2 | player_table_alias |
| CJ Beathard | C.J. Beathard | 1 | exact_display_name |
| CJ Hanson | C.J. Hanson | 1 | exact_display_name |
| CJ Mosley | C.J. Mosley | 1 | player_table_disambiguated |
| Cory Trice | Cory Trice Jr. | 1 | exact_display_name |
| Cor’Dale Flott | Cordale Flott | 1 | exact_display_name |
| D.J. Chark | DJ Chark | 1 | exact_display_name |
| D.J. Reader | DJ Reader | 2 | exact_display_name |
| Darrell Luter | Darrell Luter Jr. | 2 | exact_display_name |
| Darrell Luter Jr | Darrell Luter Jr. | 1 | exact_display_name |
| David Long Jr. | David Long | 1 | player_table_disambiguated |
| Da’Ron Bland | DaRon Bland | 2 | exact_display_name |
| De'Antre Prince | Deantre Prince | 1 | exact_display_name |
| Deatrich Wise Jr. | Deatrich Wise | 2 | exact_display_name |
| Decamerion Richarson | Decamerion Richardson | 1 | player_table_variant |
| Deshaun Johnson | Desjuan Johnson | 1 | player_table_variant |
| Devaugh Vele | Devaughn Vele | 2 | player_table_variant |
| Devaughn Vale | Devaughn Vele | 1 | player_table_variant |
| Dominque Hampton | Dominique Hampton | 1 | player_table_variant |
| Doug Kramer Jr. | Doug Kramer | 1 | exact_display_name |
| Dru Phillips | Andru Phillips | 2 | player_table_alias |
| D’Ernest Johnson | D'Ernest Johnson | 1 | exact_display_name |
| D’Marco Jackson | D'Marco Jackson | 1 | exact_display_name |
| D’Onta Foreman | D'Onta Foreman | 2 | exact_display_name |
| Earnest Brown | Earnest Brown IV | 4 | exact_display_name |
| Eddie Ulofoshio | Edefuan Ulofoshio | 5 | official_alias_crosswalk |
| Emmanuel Forbes Jr. | Emmanuel Forbes | 4 | exact_display_name |
| Ethan Conner | Ethan Bonner | 1 | player_table_variant |
| Folorunso Fatukasi | Foley Fatukasi | 3 | player_table_alias |
| Gerard Avery | Genard Avery | 2 | player_table_variant |
| Geron Christian Sr. | Geron Christian | 1 | exact_display_name |
| Gervon Dexter | Gervon Dexter Sr. | 1 | exact_display_name |
| Giovani Manu | Giovanni Manu | 1 | player_table_variant |
| Henry To’oTo’o | Henry To'oTo'o | 1 | exact_display_name |
| Israel Abanikada | Israel Abanikanda | 1 | player_table_variant |
| Izzy Abanikanda | Israel Abanikanda | 3 | official_alias_crosswalk |
| Javaugh Gwyn | Jovaughn Gwyn | 1 | player_table_variant |
| Jay Tefele | Jay Tufele | 1 | player_table_variant |
| Ja’Sir Taylor | Ja'Sir Taylor | 2 | exact_display_name |
| Jedrick Wills Jr. | Jedrick Wills | 6 | exact_display_name |
| Jeff Wilson Jr. | Jeff Wilson | 5 | exact_display_name |
| Jha’Quan Jackson | Jha'Quan Jackson | 1 | exact_display_name |
| Joe Milton | Joe Milton III | 4 | exact_display_name |
| John Johnson III | John Johnson | 1 | player_table_disambiguated |
| John Metchie | John Metchie III | 2 | exact_display_name |
| John Ridgeway III | John Ridgeway | 3 | exact_display_name |
| John Stephens | John Stephens Jr. | 4 | exact_display_name |
| Josh Dobbs | Joshua Dobbs | 1 | player_table_alias |
| Josh Paschal | Joshua Paschal | 2 | player_table_alias |
| Josh Uche | Joshua Uche | 2 | player_table_alias |
| Joshua Palmer | Josh Palmer | 3 | player_table_alias |
| Justin Hardee Sr. | Justin Hardee | 1 | exact_display_name |
| K.J. Henry | KJ Henry | 2 | exact_display_name |
| Kana’I Mauga | Kana'i Mauga | 3 | exact_display_name |
| Kayode Awokika | Kayode Awosika | 1 | player_table_variant |
| Keitrel Clark | Kei'Trel Clark | 1 | exact_display_name |
| Ken Walker III | Kenneth Walker III | 1 | player_table_alias |
| Kendal Fuller | Kendall Fuller | 1 | player_table_variant |
| Kenneth Murray Jr. | Kenneth Murray, Jr. | 1 | exact_display_name |
| Kenny Moore | Kenny Moore II | 1 | player_table_disambiguated |
| KJ Osborn | K.J. Osborn | 1 | exact_display_name |
| Kris Jenkins Jr. | Kris Jenkins | 1 | player_table_disambiguated |
| Kromah Jamree | Jamree Kromah | 1 | player_table_variant |
| Kule Dugger | Kyle Dugger | 1 | player_table_variant |
| Laviska Shenault | Laviska Shenault Jr. | 1 | exact_display_name |
| Leonard Taylor | Leonard Taylor III | 3 | player_table_disambiguated |
| Leroy Watson | Leroy Watson IV | 4 | exact_display_name |
| Lonnie Johnson Jr. | Lonnie Johnson | 1 | player_table_disambiguated |
| L’Jarius Sneed | L'Jarius Sneed | 4 | exact_display_name |
| Mack Wilson Sr. | Mack Wilson | 1 | exact_display_name |
| Malcolm Ridriguez | Malcolm Rodriguez | 1 | player_table_variant |
| Malon Tuipulotu | Marlon Tuipulotu | 2 | player_table_variant |
| Micahel Jerrell | Michael Jerrell | 1 | player_table_variant |
| Michael Carter | Michael Carter II | 2 | player_table_disambiguated |
| Michael Jerrel | Michael Jerrell | 1 | player_table_variant |
| Michael Jordan | Mike Jordan | 1 | player_table_alias |
| Michael Woods II | Mike Woods | 1 | player_table_variant |
| Mike Danna | Michael Danna | 3 | player_table_alias |
| Mycole Pruitt | MyCole Pruitt | 1 | exact_display_name |
| Myles Coles | Myles Cole | 1 | player_table_variant |
| Myron Murphy II | Byron Murphy II | 1 | official_source_correction |
| Nick Morrow | Nicholas Morrow | 2 | player_table_alias |
| Orlando Brown Jr. | Orlando Brown | 3 | player_table_disambiguated |
| Otis Reese IV | Otis Reese | 2 | exact_display_name |
| Pat Jones II | Patrick Jones II | 3 | player_table_alias |
| Patrick O’Connell | Patrick O'Connell | 2 | exact_display_name |
| Patrick Surtain II | Patrick Surtain | 1 | exact_display_name |
| Pierre Strong Jr. | Pierre Strong | 2 | exact_display_name |
| Quan'tez Stiggers | Qwan'tez Stiggers | 1 | player_table_variant |
| Robert Beal Jr. | Rob Beal Jr. | 3 | player_table_alias |
| Ronnie Hickman | Ronnie Hickman Jr. | 3 | exact_display_name |
| Sala Aumavae-Laulu | Malaesala Aumavae-Laulu | 3 | player_table_alias |
| Sam Elinger | Sam Ehlinger | 1 | player_table_variant |
| Scotty Miller | Scott Miller | 2 | player_table_variant |
| Sedrick Van-Pran Granger | Sedrick Van Pran-Granger | 2 | exact_display_name |
| Shaq Barrett | Shaquil Barrett | 1 | player_table_alias |
| Stetson Bennet | Stetson Bennett | 1 | player_table_variant |
| Stetson Bennett IV | Stetson Bennett | 1 | exact_display_name |
| T.J. Bass | TJ Bass | 2 | exact_display_name |
| Tanner McLauchlan | Tanner McLachlan | 1 | player_table_variant |
| Tariq Woolen | Riq Woolen | 1 | player_table_alias |
| Thayer Munford | Thayer Munford Jr. | 2 | exact_display_name |
| Thomas Cameron | Cameron Thomas | 1 | player_table_variant |
| TJ Tampa | T.J. Tampa | 1 | exact_display_name |
| Travis Etienne Jr. | Travis Etienne | 1 | exact_display_name |
| Travis Glovber | Travis Glover | 1 | player_table_variant |
| Tre Hawkins | Tre Hawkins III | 1 | exact_display_name |
| Tre'davious White | Tre'Davious White | 1 | exact_display_name |
| Trent Irwin | Trenton Irwin | 1 | player_table_alias |
| Trey Pipkens | Trey Pipkins | 1 | player_table_variant |
| Trey Pipkins III | Trey Pipkins | 2 | exact_display_name |
| Tre’Davious White | Tre'Davious White | 3 | exact_display_name |
| Ty Zenter | Ty Zentner | 1 | player_table_variant |
| Velus Jones | Velus Jones Jr. | 2 | exact_display_name |
| Warren McClendon | Warren McClendon Jr. | 2 | exact_display_name |
| Will Anderson | Will Anderson Jr. | 2 | exact_display_name |
| Willie Gay | Willie Gay Jr. | 1 | exact_display_name |
| Xavier Newman | Xavier Newman-Johnson | 3 | player_table_variant |
| Xavier Weave | Xavier Weaver | 1 | player_table_variant |
| Zach Carter | Zachary Carter | 2 | player_table_alias |
| Zachary Thomas | Zach Thomas | 2 | player_table_alias |

The Week 5 Seattle DT row is a source correction: NFL.com says “Myron Murphy II,” while the player table and [Seahawks official signing report](https://www.seahawks.com/news/seahawks-sign-first-round-pick-byron-murphy-ii) identify the unique Seattle DT as Byron Murphy II (`00-0039309`). The published text is preserved and the discrepancy is noted on the row.

## Requested Weeks 1–4 adjudications

| Published name | Team/week | GSIS ID | Player-table identity | Resolution and evidence |
|---|---|---|---|---|
| Boogie Basham | NYG / 1 | `00-0036553` | Carlos Basham | official_alias_crosswalk; NFL and Bills sources identify Carlos Basham as “Boogie” Basham: https://www.buffalobills.com/news/carlos-basham-nfl-draft-defensive-end-wake-forest and https://static.www.nfl.com/league/apps/league-site/media-guides/2024/NYG.pdf. [NFL.com inactive article](https://www.nfl.com/news/inactive-reports-for-sunday-week-1-games-2024-nfl-season) |
| Sala Aumavae-Laulu | BAL / 2 | `00-0038382` | Malaesala Aumavae-Laulu | player_table_alias; Matched a player-table name field plus last_name. [NFL.com inactive article](https://www.nfl.com/news/inactive-reports-for-sunday-s-week-2-games-of-2024-nfl-season) |
| Israel Abanikada | NYJ / 2 | `00-0038389` | Israel Abanikanda | player_table_variant; Published surname differs by one letter from the unique active RB player-table record. [NFL.com inactive article](https://www.nfl.com/news/inactive-reports-for-sunday-s-week-2-games-of-2024-nfl-season) |
| Sala Aumavae-Laulu | BAL / 3 | `00-0038382` | Malaesala Aumavae-Laulu | player_table_alias; Matched player-table football_name/common_first_name/first_name plus last_name; position and 2024 player history are compatible. [NFL.com inactive article](https://www.nfl.com/news/inactive-reports-for-sunday-s-week-3-games-of-2024-nfl-season) |
| Mike Edwards | BUF / 3 | `00-0035681` | Mike Edwards | player_table_disambiguated; the player table has `00-0035681` at SAF and candidate `00-0039472` at OL; the NFL.com-listed S position selects `00-0035681`, without weekly roster membership/status. [NFL.com inactive article](https://www.nfl.com/news/week-2-monday-inactives-jacksonville-jaguars-at-buffalo-bills-washington-commanders-at-cincinnati-bengals) |
| Sam Elinger | IND / 3 | `00-0036879` | Sam Ehlinger | player_table_variant; Published surname spelling differs by one letter; unique active QB record. [NFL.com inactive article](https://www.nfl.com/news/inactive-reports-for-sunday-s-week-3-games-of-2024-nfl-season) |
| Thomas Cameron | KC / 3 | `00-0037815` | Cameron Thomas | player_table_variant; Published first and last names are reversed; unique active DE record. [NFL.com inactive article](https://www.nfl.com/news/inactive-reports-for-sunday-s-week-3-games-of-2024-nfl-season) |
| Boogie Basham | NYG / 3 | `00-0036553` | Carlos Basham | official_alias_crosswalk; NFL and Bills sources identify Carlos Basham as “Boogie” Basham: https://www.buffalobills.com/news/carlos-basham-nfl-draft-defensive-end-wake-forest and https://static.www.nfl.com/league/apps/league-site/media-guides/2024/NYG.pdf. [NFL.com inactive article](https://www.nfl.com/news/inactive-reports-for-sunday-s-week-3-games-of-2024-nfl-season) |
| Mike Edwards | BUF / 4 | `00-0035681` | Mike Edwards | player_table_disambiguated; the player table has `00-0035681` at SAF and candidate `00-0039472` at OL; the NFL.com-listed S position selects `00-0035681`, without weekly roster membership/status. [NFL.com inactive article](https://www.nfl.com/news/inactive-reports-for-sunday-s-week-4-games-of-2024-nfl-season) |
| Devaughn Vale | DEN / 4 | `00-0039424` | Devaughn Vele | player_table_variant; Published surname differs by one letter; unique active WR record. [NFL.com inactive article](https://www.nfl.com/news/inactive-reports-for-sunday-s-week-4-games-of-2024-nfl-season) |
| Boogie Basham | NYG / 4 | `00-0036553` | Carlos Basham | official_alias_crosswalk; NFL and Bills sources identify Carlos Basham as “Boogie” Basham: https://www.buffalobills.com/news/carlos-basham-nfl-draft-defensive-end-wake-forest and https://static.www.nfl.com/league/apps/league-site/media-guides/2024/NYG.pdf. [NFL.com inactive article](https://www.nfl.com/news/week-4-thursday-inactives-dallas-cowboys-at-new-york-giants) |
| Michael Jerrel | SEA / 4 | `00-0039842` | Michael Jerrell | player_table_variant; Published surname omits one r; unique active OT record. [NFL.com inactive article](https://www.nfl.com/news/week-4-monday-inactives-tennessee-titans-at-miami-dolphins-seattle-seahawks-at-detroit-lions) |

## Roster status comparison after identity resolution

The comparison uses unique `(game type, week, team, GSIS ID)` identities from the full covered schedule. Roster was not used to resolve IDs. `Precision` is overlap divided by the roster-status set; `recall` is overlap divided by resolved official identities. Emergency QB3 is included in “all official”; the ordinary column includes only labels `inactive`.

| Comparison | Match / denominator (precision) | Match / official (recall) | Status-only | Official not in status |
|---|---:|---:|---:|---:|
| INA vs all official | 3577/3611 (99.06%) | 3577/3583 (99.83%) | 34 | 6 |
| INA vs ordinary inactive | 3426/3611 (94.88%) | 3426/3431 (99.85%) | 185 | 5 |
| ACT vs all official | 4/27369 (0.01%) | 4/3583 (0.11%) | 27365 | 3579 |
| ACT vs ordinary inactive | 3/27369 (0.01%) | 3/3431 (0.09%) | 27366 | 3428 |

## Provenance

- Rendered-page list: `/tmp/claude-0/-root/4a715766-ff4b-4980-99e5-dc209eaac7d4/scratchpad/avail/inactives/inactive_pages_2024.json` (52 pages).
- Page coverage audit: `/tmp/claude-0/-root/4a715766-ff4b-4980-99e5-dc209eaac7d4/scratchpad/avail/inactives/inactive_page_coverage_2024_w5plus.json` (52 pages; 0 failures).
- Weeks 1–4 original JSONL SHA-256: `bdaa6ef234373da3db890a49cfdb64d86278fa76e20ebce7e3b76cb329f21a9f` (unchanged).
- Weeks 1–4 independent-ID source SHA-256: `54bd1d07174c61ae5833b2c76366cf8015989fdd18febbc44ef946364d7e5f54` (unchanged).
- Weeks 5+ parsed source SHA-256: `b3146912a4455a10596bf53b21f1fa762e2459f124e538a59bc969578674997d`.
- Full-season output SHA-256: `040e5af6d704820e32fdfe97b205401ae546e5ada221601fa13c1aa396c8a1be`.
- Input artifacts were not edited. No repository files, commits, pushes, or probability fits were made.
