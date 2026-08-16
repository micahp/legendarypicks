## 7. Adding a league

The MANIFEST entry is the contract. `audit_league_stats.py` measures every league
against its own declaration — a league with no entry is reported (`UNVERIFIED
manifest`, never skipped), and a league whose entry is half-empty is reported
for exactly the checks it did not declare. So the order is: **write the MANIFEST
entry, then satisfy each check, in the order below.** Steps 1–3 are cheap (a
declaration, minutes). Step 6 is not (a fetcher needs a publisher that actually
issues the id). This is the entire point: a league's rows must not land before
someone has said what the league claims.

### 7.1 The MANIFEST entry — cheap, do this first

Every league in `backend/audit_league_stats.py`'s `MANIFEST` needs five fields.
Write them from the publisher's own shape, never from what you hope to serve:

| field | what it means | where the truth lives |
|---|---|---|
| `stat_types` | which season surfaces exist (e.g. `season`, `batting`+`pitching`), each with `required` columns and a `qualifier` | the publisher's season/leaderboard endpoint |
| `position_content` | what a position's **log** must record — the keys a log must carry to count as having observed that player, per position class, plus a `coverage` floor | the box-score/event feed, **measured**, not assumed |
| `single_vocabulary` | which categorical columns hold exactly one vocabulary (`position`, `position_group`, `team`…) | the publisher's own vocab/code list |
| `injury_population` | floor for injury-status coverage on active players (only where the league serves injuries) | the league's roster feed |
| (implicit) the league's id column | which external id each row carries, and who issues it | the ingest that created the rows |

`stat_types` may legitimately be `{}` — a league with no leaderboard surface (UFC
is fighters + rankings; WC is dormant). Say that in the entry rather than
omitting it. Same for `position_content`: a league with **no `player_game_logs`
rows at all** cannot have its positions' content declared — record that instead
of declaring content for logs that do not exist.

### 7.2 Then satisfy each check, in this order

Each of the seven checks asks a different question. The league must answer all of
them; a check left undeclared reports `UNVERIFIED` — **which is a failure, never
a skip**. A green light you cannot defend is worse than a red one you can.

| # | check | what it needs from the league | the question it answers |
|---|---|---|---|
| A | `A/required-stats` | for each `stat_type`: the `required` columns and any per-column coverage floor | does the season table hold the stats a page of this league is not honest without? |
| B | `B/position-content` | for each position class: the keys a log must carry, plus a `coverage` share | is a player observed doing his job, or just present? (caught 78 NHL goalies with 64 games and zero saves) |
| C | `C/vocabulary[...]` | which columns are single-vocabulary, and whether a group column is declared | are two ingests writing two vocabularies into one column? |
| D | `D/leaders-reach-logs` | a `stat_types` entry (a leaderboard surface to serve) | can you click a leader and see a game? |
| E | `E/qualifier[...]` | the published qualifier and its unit, per stat type | is the leaderboard's qualifier measurable from a column we hold? |
| F | `F/identity-crosswalk` | a publisher id **and** an `espn_id` (or an explicit single-publisher note) | can a second publisher reach this league at all? |
| G | `G/published-identity` | a publisher id→name map, fetched from the publisher that **issued the id** | does each id point at the person whose name is on the row? |

There is also an eighth check, **`H/injury-population`**, and it is the one
*optional* entry in the manifest: only leagues that serve injuries declare
`injury_population.floor` (NFL does; a league with no injury surface simply
omits it). If a league serves injuries, the floor must be measured against the
live population, not picked to pass.

Two checks are not free:

- **E is a published fact, not a guess.** "NONE PUBLISHED" has been wrong every
  time it was written in this repo (ERA, goalie saves, MLB team/position — all
  published, all one request away). Before writing it, enumerate every publisher
  the league has and read what each returns for a qualification rule; write the
  endpoint, the parameters and the date next to whatever you conclude so the
  claim is falsifiable. A gate still UNVERIFIED with the endpoints you asked
  written next to it is an acceptable outcome.
- **G needs a fetcher, and a fetcher needs a publisher that issues the id.** If
  the league's rows carry only an `espn_id`, ESPN is the issuer and the check is
  answerable (`fetch_identity_names.py` already knows how to ask
  `sports.core.api.espn.com/v2/sports/{sport}/athletes/{id}`). If the rows carry
  no publisher id at all, the honest outcome is that the gate stays UNVERIFIED
  and you say why. **Never invent a map to turn a light green.**

### 7.3 Then the data steps (the old checklist, still true)

1. **Find the ESPN path and confirm the shape.** `football/leagues/college-football`,
   `soccer/leagues/usa.1`, `soccer/leagues/eng.1`. Then
   `GET seasons/<year>` and read `types[]` and `displayName` — **write the type ids you
   found into the ingest as data, not as an assumption.**
2. **Establish the scope.** Is it the whole league, or a published group?
   (`types/<t>/groups?limit=1` — NCAAF returns 2: FBS 80, FCS 81.) Record the group id;
   every expected-count for that league is scoped to it.
3. **Get the three expected totals** with `?limit=1`: events, teams, athletes. Sanity-check
   them against the competition's real shape before trusting them (911 NCAAF games, 380 EPL
   matches, 146 FBS teams). **If a number surprises you, that is a question about the
   definition, not a defect** — see `published-first` §6.
4. **Ingest** with ESPN's start-year season key, ESPN team codes normalised at the boundary,
   and `game_type` NOT NULL drawn from the published `types[]`.
5. **Add the league to `ESPN_PATH` in `backend/reconcile_totals.py`** with its scope group
   and its type ids, and write its checks.
6. **Run the reconcile and land a `team_stats_coverage` row.** A league with no row is
   `unverified`: not offered, not defaulted, anywhere.
7. **Walk §5.** Every league-scoped route answers for the new league the moment it has
   rows — check each one before the season is marked `complete`, not after.
8. **Screenshot two players**: one with a genuine missed game, one in a season we have not
   fully ingested. **If those two look the same, the work is not done.**

### 7.4 The five defect shapes — run these per league

Steps 1–8 answer *"are the rows there?"*; §7.2 answers *"is the league declared?"*. This
answers *"is what's on them true?"* — a different question, and it was never asked until
2026-08-04. Asking it that night turned up roughly ten defects across two leagues — every
single one an instance of one of **five shapes**. There is no sixth yet. Treat this as a
checklist, not a reading: run each one, write the number down, and a league is not
`complete` until all five have an answer.

They matter because **not one of them raises.** Each produces rows of the right shape and
magnitude, in the right column, that nobody spots by looking.

| # | shape | what it looks like | how to measure it |
|---|---|---|---|
| 1 | **An id names the wrong person** | every row has an id; some point at someone else | check **`G/published-identity`** |
| 2 | **Two publishers' vocabularies in one column** | `WHERE position='P'` returns only retired players | check **`C/vocabulary[...]`** |
| 3 | **Two rows for one person** | stats on one row, game logs on the other | check **`F/identity-crosswalk`** |
| 4 | **A display copy diverged from its source** | a denormalised name/team drifts from the spine | join the copy back to `players` and count `<>` |
| 5 | **A value is in the logs but not the season table** | "we have no touchdown data" — we do | `published-first` §2b: surfacing vs acquisition gap |

**Order matters, and it is not the order above.** Shape 1 before shape 3, always: a dedupe
"merges rows that share an id (= provably the same person)", and if shape 1 is unfixed that
sentence is false. On 2026-08-04, 124 of 317 MLB groups were two *different* people, and the
merge would have repointed 408,610 prop rows and 26,491 game logs onto the wrong players
before deleting the originals. A `player_stats` UNIQUE constraint stopped it by luck.

Measured instances, so the sizes are not hypothetical:

1. **223 MLB rows** carried another player's `mlbam_id` — `id=26551 'Eiberson Castellano'`
   against `mlbam_id=703607`, which MLB publishes as Henry Bolte. Cause: Statcast's
   `player_name` is the **pitcher's** name on every pitch row, and the pre-`b03b9c9` batter
   fallback took it while `player_id` came correctly from `batter_id`. NFL (4/24344) and
   NHL (11/840) show only nickname and legal-name variants — `Kenny`/`Kenneth Gainwell` —
   which are the same human. **A red G is not automatically corruption; read the pairs.**
   Where a variant is a same-human alias, record it in `data/name-aliases.json` — that file
   is the reviewed, diff-visible decision; an id absent from it has NO accepted alternate.
2. **MLB `position`** held ESPN's `SP`/`RP` on active rows and MLB's `P` on the rest, so
   neither query could ever return both. Fix is one level from one publisher per column —
   see `DATA-SPINE.md`. The same split applies to `position_group`: when a league declares
   one, check B and C both honor it.
3. **MLB 317 duplicate `mlbam_id` groups; NBA 269 athletes** split across two rows via
   `nba_id`/`espn_id`, their stats and their game logs on different people.
4. **242 MLB `player_stats` rows** disagreed with `players.name` after the dedupe repointed
   them but kept the duplicate's spelling. The leaders endpoint's raw-string guard **503'd in
   production**. Neither table was the authority — the spine held `Heriberto Hernandez`, the
   stats row held the published `Heriberto Hernández`. Write both from the publisher.
5. NFL `rush_td`/`rec_td` read "no such column" while already sitting in
   `player_game_logs`; MLB `pa`/`hits`/`rbi` likewise.

**Diagnosis generalises; repair does not.** The seven audit checks run for every league off a
per-league declaration — that is why shape 1 was answered for four leagues the day the check
was written. The *fixes* are all league-specific (`repair_mlb_identity_names.py`,
`dedupe_mlb.py`, `dedupe_nfl.py`). So audit every league; repair only the ones the product
needs. As of 2026-08-05 **`atp`, `wnba` and `wta` have no MANIFEST entry at all — they are
unmeasured, not passing.** (`ufc` and `wc` were in that list until 2026-08-05; they now have
declarations and measure 0 FAIL / 2 honest UNVERIFIED on the leaderboard checks.)

### Known shape notes for the next three

- **NCAAF** — scope to FBS (`groups/80`, 146 teams). 911 regular-season events, uneven
  per-team schedules, 102,406 athletes league-wide. `expected_players` must be
  group-scoped or it is noise. Postseason is bowls, not a bracket.
- **MLS** (`soccer/leagues/usa.1`, 31 seasons published) — one season type. Calendar-year
  season, so the start-year key reads naturally. Draws exist: any win-rate or
  `_valid_result_pair` logic written for NFL ties is not the same thing.
- **EPL** (`soccer/leagues/eng.1`, 26 seasons published) — one season type, id 1.
  380 matches, 20 teams, **3 relegated and 3 promoted each year**, so a team's league
  membership is a season-scoped fact. Season spans two calendar years; ESPN keys it `2025`
  and labels it `"2025-26 English Premier League"` — use both, invent neither.
