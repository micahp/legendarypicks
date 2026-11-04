# M5 freeze amendment 9, 2026-11-04: an elevated practice-squad kicker (MIA, 2026 week 8)

Status: owner-authorized (2026-11-04: "fix the MIA week 8 kicker gap"). No pinned layer file changes. Changes the kicker
table that `--playcall-fg-kicker` (amendment 6, on under `--slc-v2`) loads. Earlier freeze documents are not edited.

## What was wrong

The kicker table assigns each team-week the team's one active K (status `ACT`) on the published nflverse weekly roster.
In the roster captured 2026-10-27 Miami has no active K for week 8: Zane Gonzalez (`00-0033862`), signed in week 7, is
listed `DEV` (practice squad). He was elevated for the game; the roster was captured after the elevation reverted. The
nflverse republication of 2026-11-04 lists him `ACT` in week 8. The table had no MIA week 8 row, so v2 refused the game
`2026_08_NE_MIA` ("kicker table has no active kicker for MIA in 2026 week 8") and it was missing from every v2 score.

The 2026-11-04 roster was not used as the source: it also adds a second active K for the Rams in week 8 (Joshua Karty),
which the 2026-10-27 capture does not have and which would change an assignment the scored Rams game used.

## The change

`build_kicker_table.py`: a team-week with no active K takes its one practice-squad K. Zero or several practice-squad
kickers refuses, and every use is printed. Rebuilt from the same 2026-10-27 inputs:

| File | sha256 | Contents |
|---|---|---|
| `fg-kicker-2026-11-04/kicker_table_through_2025_assign_2026.json` | `f1535cf8fa563c961ef04cdfb08c626ad08fe7da64d540fc33a381021400764e` | 202 kickers fitted on 1999 to 2025; 242 2026 team-weeks assigned; 3 assigned kickers with no earlier kick |

Measured against the amendment 6 table (`9fdc57b2...`): the builder without this rule reproduces that table byte for
byte; with it, one assignment is added, `(2026, 8, MIA, 00-0033862)`, and nothing else differs (every other assignment,
every kicker offset, attempts and career long). The rule fires for that team-week only. Gonzalez has 150 earlier kicks,
offset +0.046. `simulate_pregame_batch.py` pins the new hash.

## Verification

Measured 2026-11-04 on the fast host, code `c6bd9b44`, v2 flags as in the season run.

- `2026_08_NE_MIA`: exit 0, 19 of 20 seeds complete, box scores written. v2 now runs all 121 games.
- Control `2026_08_KC_DEN`: identical to the earlier v2 run in every seed record and box-score line except provenance
  (`configuration_hash`, `reference_sha256`). The new table changes nothing outside MIA week 8.
- Builder: without the rule it reproduces the amendment 6 table byte for byte; the rule fires once, for MIA week 8.
- Results: `SLC-V2-VS-V15-RESULTS-2026-11-04.md` (V1.5 against v2 on 121 games).
