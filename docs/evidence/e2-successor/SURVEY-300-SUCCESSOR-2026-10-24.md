# E2 successor: 300-seed survey on the repaired engine (2026-10-24)

Engine: `c131fda249dc` on `feat/nfl-sequence-e2-successor-2026-10-24`. Command: `survey_legality_300.py --out-dir docs/evidence/e2-successor`.
Seeds 1–300, regulation-only pool. Every record is checked by the independent legality checker (no engine imports) and by
`rules_matrix`. `valid_full_game` is false for every record; nothing in this survey sets it.

## Verdicts

| verdict | count | meaning |
|---|---:|---|
| `complete_regulation` | 288 / 300 | the game reached the end of regulation |
| `blocked` | 12 / 300 | the engine refused a branch it does not model; never complete |
| `legal_modelled` | 300 / 300 | consistent under the modelled rules (clock, quarters, downs, points, tries, timeouts, possession) |
| `legal_complete_game` | 0 / 300 | modelled-legal, complete regulation, and no unmodelled transition |
| complete, with an unmodelled transition | 288 / 288 | every complete game crosses 2:00 in quarter 2 or 4 |
| matrix FAIL rows | 0 | `rules_matrix` |
| try findings | 0 | `check_conversions` on every try |

**`legal_complete_game` is 0 of 300, and this is the scope guard working, not a fault in the sample.** Each record has
1–2 two-minute-warning
crossings. The engine does not stop the clock at 2:00 in the second and fourth quarters, so a complete game cannot be called
a legal complete game until that stoppage is modelled. The claim the survey supports is `legal_modelled`: 300 of 300.

Blocked records are never complete: `blocked_never_complete = True`.

## Blocked seeds (12)

- seed 36: `overtime_not_modelled`
- seed 55: `overtime_not_modelled`
- seed 114: `overtime_not_modelled`
- seed 163: `overtime_not_modelled`
- seed 175: `overtime_not_modelled`
- seed 185: `overtime_not_modelled`
- seed 194: `thin_kick_cell:field_goal:50+`
- seed 246: `overtime_not_modelled`
- seed 276: `overtime_not_modelled`
- seed 279: `overtime_not_modelled`
- seed 280: `overtime_not_modelled`
- seed 290: `overtime_not_modelled`

## Against the frozen survey

`matches_frozen_survey`: 281 of 300. The frozen survey is `docs/fixtures/e2/survey-per-seed-300.csv`
(a442dcd7, unmodified). Comparison is on status, blocker, complete and matrix FAIL. The 19 differing seeds all
follow the repairs (kick spot, timeout transition, five-second made kick, regulation-only pool that no longer draws overtime):

- seed 9: frozen `blocked` thin_kick_cell:field_goal:50+ → now `complete_regulation`
- seed 36: frozen `complete_regulation` → now `blocked` overtime_not_modelled
- seed 48: frozen `blocked` overtime_not_modelled → now `complete_regulation`
- seed 55: frozen `complete_regulation` → now `blocked` overtime_not_modelled
- seed 78: frozen `blocked` overtime_not_modelled → now `complete_regulation`
- seed 87: frozen `blocked` overtime_not_modelled → now `complete_regulation`
- seed 114: frozen `complete_regulation` → now `blocked` overtime_not_modelled
- seed 163: frozen `complete_regulation` → now `blocked` overtime_not_modelled
- seed 175: frozen `complete_regulation` → now `blocked` overtime_not_modelled
- seed 185: frozen `complete_regulation` → now `blocked` overtime_not_modelled
- seed 194: frozen `complete_regulation` → now `blocked` thin_kick_cell:field_goal:50+
- seed 216: frozen `blocked` thin_kick_cell:field_goal:50+ → now `complete_regulation`
- seed 246: frozen `complete_regulation` → now `blocked` overtime_not_modelled
- seed 267: frozen `blocked` overtime_not_modelled → now `complete_regulation`
- seed 276: frozen `complete_regulation` → now `blocked` overtime_not_modelled
- seed 279: frozen `complete_regulation` → now `blocked` overtime_not_modelled
- seed 280: frozen `complete_regulation` → now `blocked` overtime_not_modelled
- seed 290: frozen `complete_regulation` → now `blocked` overtime_not_modelled
- seed 291: frozen `blocked` overtime_not_modelled → now `complete_regulation`

## Per-seed table

Every seed, one row. The same data is in `legality-survey-300.csv`.

| seed | status | blocker | complete regulation | legal (modelled) | legal complete game | unmodelled transitions | matrix FAIL | vs frozen survey |
|---:|---|---|:-:|:-:|:-:|---:|---:|---|
| 1 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 2 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 3 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 4 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 5 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 6 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 7 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 8 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 9 | complete_regulation | – | True | True | False | 2 | 0 | differs |
| 10 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 11 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 12 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 13 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 14 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 15 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 16 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 17 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 18 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 19 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 20 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 21 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 22 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 23 | complete_regulation | – | True | True | False | 1 | 0 | same |
| 24 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 25 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 26 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 27 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 28 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 29 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 30 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 31 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 32 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 33 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 34 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 35 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 36 | blocked | overtime_not_modelled | False | True | False | 2 | 0 | differs |
| 37 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 38 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 39 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 40 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 41 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 42 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 43 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 44 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 45 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 46 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 47 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 48 | complete_regulation | – | True | True | False | 2 | 0 | differs |
| 49 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 50 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 51 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 52 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 53 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 54 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 55 | blocked | overtime_not_modelled | False | True | False | 2 | 0 | differs |
| 56 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 57 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 58 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 59 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 60 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 61 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 62 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 63 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 64 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 65 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 66 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 67 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 68 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 69 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 70 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 71 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 72 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 73 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 74 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 75 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 76 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 77 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 78 | complete_regulation | – | True | True | False | 2 | 0 | differs |
| 79 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 80 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 81 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 82 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 83 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 84 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 85 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 86 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 87 | complete_regulation | – | True | True | False | 2 | 0 | differs |
| 88 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 89 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 90 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 91 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 92 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 93 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 94 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 95 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 96 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 97 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 98 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 99 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 100 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 101 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 102 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 103 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 104 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 105 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 106 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 107 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 108 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 109 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 110 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 111 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 112 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 113 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 114 | blocked | overtime_not_modelled | False | True | False | 2 | 0 | differs |
| 115 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 116 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 117 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 118 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 119 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 120 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 121 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 122 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 123 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 124 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 125 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 126 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 127 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 128 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 129 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 130 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 131 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 132 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 133 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 134 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 135 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 136 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 137 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 138 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 139 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 140 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 141 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 142 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 143 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 144 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 145 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 146 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 147 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 148 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 149 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 150 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 151 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 152 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 153 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 154 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 155 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 156 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 157 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 158 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 159 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 160 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 161 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 162 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 163 | blocked | overtime_not_modelled | False | True | False | 2 | 0 | differs |
| 164 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 165 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 166 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 167 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 168 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 169 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 170 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 171 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 172 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 173 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 174 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 175 | blocked | overtime_not_modelled | False | True | False | 2 | 0 | differs |
| 176 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 177 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 178 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 179 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 180 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 181 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 182 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 183 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 184 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 185 | blocked | overtime_not_modelled | False | True | False | 2 | 0 | differs |
| 186 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 187 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 188 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 189 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 190 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 191 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 192 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 193 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 194 | blocked | thin_kick_cell:field_goal:50+ | False | True | False | 1 | 0 | differs |
| 195 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 196 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 197 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 198 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 199 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 200 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 201 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 202 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 203 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 204 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 205 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 206 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 207 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 208 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 209 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 210 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 211 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 212 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 213 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 214 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 215 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 216 | complete_regulation | – | True | True | False | 2 | 0 | differs |
| 217 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 218 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 219 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 220 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 221 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 222 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 223 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 224 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 225 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 226 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 227 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 228 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 229 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 230 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 231 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 232 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 233 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 234 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 235 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 236 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 237 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 238 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 239 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 240 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 241 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 242 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 243 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 244 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 245 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 246 | blocked | overtime_not_modelled | False | True | False | 2 | 0 | differs |
| 247 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 248 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 249 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 250 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 251 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 252 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 253 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 254 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 255 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 256 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 257 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 258 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 259 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 260 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 261 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 262 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 263 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 264 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 265 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 266 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 267 | complete_regulation | – | True | True | False | 2 | 0 | differs |
| 268 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 269 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 270 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 271 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 272 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 273 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 274 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 275 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 276 | blocked | overtime_not_modelled | False | True | False | 2 | 0 | differs |
| 277 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 278 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 279 | blocked | overtime_not_modelled | False | True | False | 2 | 0 | differs |
| 280 | blocked | overtime_not_modelled | False | True | False | 2 | 0 | differs |
| 281 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 282 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 283 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 284 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 285 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 286 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 287 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 288 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 289 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 290 | blocked | overtime_not_modelled | False | True | False | 2 | 0 | differs |
| 291 | complete_regulation | – | True | True | False | 2 | 0 | differs |
| 292 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 293 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 294 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 295 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 296 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 297 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 298 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 299 | complete_regulation | – | True | True | False | 2 | 0 | same |
| 300 | complete_regulation | – | True | True | False | 2 | 0 | same |
