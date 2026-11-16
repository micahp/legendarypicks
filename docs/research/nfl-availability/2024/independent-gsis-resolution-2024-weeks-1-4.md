# Independent GSIS resolution and roster comparison: 2024 Weeks 1–4

## Source and method

- Player source: [nflverse players.parquet](https://github.com/nflverse/nflverse-data/releases/download/players/players.parquet)
- Download SHA-256: `b4a8a508cd621bfdb4b2e364e1bcee4ab5a945e74fb6a4cfc98af019a50c2812`; 24,861 player records.
- The weekly roster file was not used to assign independent GSIS IDs. Name matching used normalized `display_name`; suffix-only variants (Jr/Sr/II/III/IV/V) were allowed. Where names collided, published position and the player table’s position plus 2024 activity window (`rookie_season`/`last_season`) disambiguated candidates. No fuzzy spelling or nickname guesses were made.
- The earlier roster-derived GSIS value and match method are retained separately as `roster_match_gsis_id` and `roster_match_resolution`. `gsis_id` now contains only the independent player-table result; unresolved IDs remain null.

## Resolution counts

| Method | Resolved | Ambiguous | Failed | Total rows |
|---|---:|---:|---:|---:|
| Exact normalized `display_name` only | 744 | 27 | 37 | 808 |
| Final independent crosswalk (position, 2024 activity, suffix-only) | 787 | 0 | 21 | 808 |

The final crosswalk resolves 787/808 row occurrences (97.40%). After preserving the two duplicate article entries, this is 785 unique team-game-player identities. There are 21 failed rows across 18 distinct published names. The final crosswalk has no remaining ambiguous candidates; name-only ambiguities were resolved by independent position and 2024 player-history fields.

Resolved matching methods: `exact_display_name` 713, `exact_display_name_position` 7, `exact_display_name_position_mismatch` 41, `suffix_variant_position` 26.

Unresolved published names and row counts: `Antonie Winfield Jr.` (1), `Boogie Basham` (3), `Deshaun Johnson` (1), `Devaugh Vele` (1), `Devaughn Vale` (1), `Gerard Avery` (1), `Israel Abanikada` (1), `Izzy Abanikanda` (1), `Joshua Palmer` (1), `Ken Walker III` (1), `Kendal Fuller` (1), `Michael Jerrel` (1), `Michael Jordan` (1), `Mike Danna` (1), `Sala Aumavae-Laulu` (2), `Sam Elinger` (1), `Thomas Cameron` (1), `Zachary Thomas` (1).

Among the 787 independently resolved rows, 787 agree with the preserved roster match. This agreement was checked after resolution and did not supply IDs.

## Roster status comparison

Metrics use unique `(week, team, GSIS ID)` identities in the 128 covered team-games. Duplicate article rows are retained in JSONL but deduplicated for the comparison. “All official” includes emergency QB3 records; the ordinary-only row excludes that label. Recall is conditional on the independently resolved official-ID set. Unresolved official names reduce coverage, so strict matched precision is a lower-bound match rate and the recall is coverage-limited.

| Comparison | Roster count | Resolved official IDs | Matched | Precision / match rate | Recall among resolved official IDs | Unmatched roster IDs | Official IDs not in status |
|---|---:|---:|---:|---:|---:|---:|---:|
| INA vs all official (including emergency QB3) | 812 | 785 | 783 | 96.43% | 99.75% | 29 | 2 |
| INA vs ordinary inactive only | 812 | 756 | 754 | 92.86% | 99.74% | 58 | 2 |
| ACT vs all official | 6156 | 785 | 2 | 0.03% | 0.25% | 6154 | 783 |
| ACT vs ordinary inactive only | 6156 | 756 | 2 | 0.03% | 0.26% | 6154 | 754 |

The ACT rows are contradiction counts, not a predictive “positive” class: two resolved official-inactive IDs are marked ACT in Week 4 (`2/6,156`, 0.0325% of ACT roster identities; `2/785`, 0.25% of all resolved official identities).

## Adjudication items retained

### Roster INA identities absent from the published official list

| Week | Team | Player | Roster GSIS ID | Status |
|---:|---|---|---|---|
| 1 | DET | Trevor Nowaske | `00-0038660` | INA |
| 1 | GB | Alex McGough | `00-0034732` | INA |
| 1 | GB | Jack Podlesny | `00-0038808` | INA |
| 1 | NE | Jontrey Hunter | `00-0039690` | INA |
| 1 | NO | Nouredin Nouili | `00-0039619` | INA |
| 1 | NYG | Stantley Thomas-Oliver | `00-0036315` | INA |
| 1 | PHI | Jalyx Hunt | `00-0039740` | INA |
| 2 | JAX | Evan Engram | `00-0033881` | INA |

### Official inactive, roster ACT in Week 4

| Week | Team | Player | Independent GSIS ID | Official weeks listed | Week 4 roster status |
|---:|---|---|---|---|---|
| 4 | IND | Blake Freeland | `00-0039158` | 1, 2, 3, 4 | ACT |
| 4 | PIT | Isaac Seumalo | `00-0032954` | 1, 2, 3, 4 | ACT |

## Output

- Independent-ID JSONL: `/tmp/claude-0/-root/4a715766-ff4b-4980-99e5-dc209eaac7d4/scratchpad/avail/inactives/official_inactives_2024_weeks_1_4_independent_ids.jsonl`
- Original JSONL preserved unchanged: `/tmp/claude-0/-root/4a715766-ff4b-4980-99e5-dc209eaac7d4/scratchpad/avail/inactives/official_inactives_2024_weeks_1_4.jsonl`
