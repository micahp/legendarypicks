# 2025 NFL.com official inactive extraction and validation

## Coverage and parsing

- NFL.com source pages: **64**, discovered from monthly news sitemaps spanning September 2025–February 2026; every rendered page returned HTTP 200.
- Schedule reconciliation: **285/285 games** and **570/570 team lists**, including regular season and playoffs.
- Game counts: REG 272; WC 6; DIV 4; CON 2; SB 1. NFL schedule source: [nflverse schedules](https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv).
- The parser produced 3,614 source rows. Ten SUNDAY NIGHT section headings were mistaken for safety entries and removed. For 239 tight-end rows, the rendered text showed TE Name but the parser split it as position T and name E Name; the final rows correct those to TE and the published name. Parenthetical emergency-QB notes were stripped only from identity matching; source text is retained in raw_entry.
- Final JSONL: **3,604 source rows** (3,492 ordinary inactive, 112 emergency_qb3); source duplicates are retained. There are 0 extra resolved source rows beyond distinct exact identities.
- NFL.com game-type/week fields are used for joins; the output keeps the exact 2024 JSONL field schema and uses the scheduled week values (REG 1–18, WC 19, DIV 20, CON 21, SB 22).
- One Week 13 Sunday page contains a NYG–NE matchup teaser without inactive-list sections; the Monday game is covered by its separate article. This is a coverage note, not a missing team list. The ten heading artifacts above were found in the player-row audit and are reported explicitly.

## GSIS identity resolution

**3,594/3,604 (99.72%)** source rows resolved from the players table or the same-table-verified 2024 official crosswalk; **10** rows remain unresolved. The exact players-table and resolver-method counts below are source-row counts:

| Resolution method | Rows |
|---|---:|
| `players_table_exact_alias` | 3,321 |
| `players_table_disambiguated` | 160 |
| `players_table_suffix_alias` | 58 |
| `players_table_fuzzy` | 21 |
| `players_table_unique_surname_team_position` | 20 |
| `2024_official_crosswalk` | 9 |
| `players_table_compound_surname_alias` | 5 |
| **Total resolved** | **3,594** |

Unresolved rows: **10 across 5 source name/position/team signatures**. Names and row counts: C.J. Okoye (1), Hollywood Brown (1), Jaylon Jones (2), Zach Tom (6). Candidate IDs and page-level keys are in [unresolved row detail](official_inactives_unresolved_2025.csv). All IDs are restricted to players whose player-table career bounds include 2025; ambiguous, absent, or unsupported matches remain null.
- The fuzzy and nickname aliases are used only where the players table supplies a unique candidate with name/position/team support. The 2024 crosswalk is supplemental and every carried ID is verified in the players table and active-season bounds.
- Player-position disagreements are retained as identity-resolution notes in JSONL; position never overrides an exact unique name. Trade-week/team differences never change the exact identity key.

## Post-resolution roster diagnostics

Roster data is used only after identity resolution to evaluate exact team-week GSIS keys. No fallback match changes the source team.

| Diagnostic | Source rows |
|---|---:|
| Exact team-week GSIS roster key | 3,589 |
| Same GSIS appears that week under another team only | 5 |
| No roster row for same GSIS that week | 0 |

The designation-rate report contains the roster-status dispositions for distinct ordinary inactive and emergency-QB3 identities, including `RES` conflicts and identities with no exact roster row. `same_week_other_team_only` is an attribution diagnostic, not a match.

## Related report and constraints

- [2025 injury designation and validation rates](official_inactive_designation_rates_2025.md).
- [Official identities with no exact injury row](official_inactives_without_exact_injury_row_2025.csv).
- [2025 page-level coverage](inactive_page_coverage_2025.json).
- Existing 2024 reports and JSONL were not changed; the validation decision is in its own new addendum. No probability fit was made during this analysis.
