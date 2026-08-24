# CONTEXT — 2026-08-11 handoff

Session ran 2026-08-10 evening into 08-11. Branch `fix/kick-viewer-keys`, all work pushed to
`origin/dev`, head `5bee747`. Backend suite 1,027 passing; the 7 `test_news.py` failures and 2
`WCContext` failures are pre-existing isolation breakage, identical with every change stashed.

---

## 1. The question this session ended on — SETTLED

**"Is the problem the rules in MLB?"** No. Grading matches the official line exactly.

The last two disagreements in the whole props audit were pitcher `outs` in game 824490
(2026-07-27, Guardians at Reds):

| pitcher | we graded | statsapi official | Statcast |
|---|---|---|---|
| Chase Burns | 15 | **15** (5.0 IP) | 14 |
| Slade Cecconi | 11 | **11** (3.2 IP) | 10 |

We agree with the official box score. **Statcast is the source that is one short**, for both
pitchers, in the same game. That is a definitional difference, not a defect: official innings
pitched counts every out recorded while the pitcher was in the game, including outs made on
the bases (caught stealing, pickoff, runner out advancing), while a pitch-event-derived count
does not see those. Both pitchers being exactly one short in one game is the shape you would
expect from an inning ending on a baserunning out.

On recent games the two sources agree exactly (Chase Burns 2026-08-08: statcast 16, statsapi
16), so this is an edge case, not a systematic offset.

**Conclusion: dev's MLB prop results are clean.** Nothing is outstanding on the data itself.

---

## 2. What was actually wrong, in the order it was found

Four defects, all in the props path, each found by checking the previous fix:

1. **Settlement had no finality gate for MLB** (`e20b736`). `settle_game`'s "ensure game is
   final" check sat BELOW the MLB branch, which returns before reaching it — dead code for the
   one league with volume (633,865 of 642,045 rows). Props were graded against whatever the box
   score held when the job ran. Game 401816457: first pitch 16:15Z, everything settled 17:00Z,
   45 minutes in. Brady Singer stored at 6 outs and 0 strikeouts; he finished 18 and 3. Games
   that had not started were graded as zeros — two spot-checked were settled ~22 hours BEFORE
   first pitch.

2. **The Bovada parser minted one market key per player** (`a703f29`). It required an uppercase
   team parenthetical to extract a name; without one it emitted the prop anyway with an empty
   player, and canonicalisation slugged the whole description:
   `total_hits,_runs_and_rbis___austin_riley_(atl)`. Also produced ONE nameless `players` row
   (id 28987) holding 3,729 props from Cooper Pratt, Raynel Delgado, Kahlil Watson and others.

3. **gamePk was matched on an exact calendar date** (`651176e`). Publishers disagree about which
   day a game belongs to — Braves-Giants is 06-17 to Statcast and the MLB schedule, 06-18 in
   `prop_games`. Now matched on teams across a three-day window, same day first.

4. **The recap never said who won** (`5c64467`). `gr` carried scores and a winner and none of it
   reached the grounding, so a finished game's facts said only "state: post". Soccer hid it
   because `matchup_context`'s form line contains the scoreline.

### Repairs run against `picks.dev.db`

| run | result |
|---|---|
| Re-grade against finals (`53021ae`) | 614 games re-graded, **19,164 grades on unplayed games deleted**, 0 errors |
| Market key backfill (`5bee747`) | **561,543 keys stripped**, 0 remaining, 614 games re-graded, 0 errors |

Backups, both `VACUUM INTO` + `quick_check`:
`data/picks.dev.db.pre-schema-20260811T043709.369688Z.bak` and `...T051944.075530Z.bak`.

### Verification, same ruler both sides

| ruler | before | after |
|---|---|---|
| ESPN final box score, 12-game sample | 140 / 183 disagree | **0 / 192** |
| Statcast, exact gamePk join, the 10 games ESPN cannot serve | — | **2 / 184** (both the outs definition above) |

---

## 3. Two measurement mistakes I made — read this before trusting a ruler

Both times the data was in better condition than my measurement claimed.

- **Blamed duplicate player rows** for a failed Statcast cross-check. Wrong: only 3 lowercase
  MLB rows have a properly-cased twin, and `'austin riley'` has 122 logs spanning March to
  August. The check failed on the **date join**.
- **Blamed the polluted market keys** for zeros. Wrong: the keys are clean now and Riley is
  still graded 0 — and that 0 is likely correct, because gamePk 824911 has **zero Statcast
  rows at all**. The "39 of 210 disagree" figure was an artifact of a ±1 day window pulling in
  the adjacent game of a series. With an exact gamePk join it is 2 of 184.

`player_game_logs.game_id` holds the MLB gamePk. **Join on it. Never on a date.**

---

## 4. Everything else shipped this session

- **MLB + NCAAF merged into dev** (`4542548`) from `feat/new-leagues`. NCAAF was a dead card
  until this: `espn_client.LEAGUES` had no `ncaaf`, so `/api/ncaaf/standings` 404'd. Verified
  after merge: 124 teams, coverage vouches ncaaf 2025 at 888/888.
- **Pregame context** (`f075cb3`, `df0e8ab`, `7340cef`): form, leaders and cross-league
  tournament state read off the ESPN summary payload already fetched. Soccer has no props, so
  the form section was always empty there and Leagues Cup stories were written from strength
  ranks alone. The league-wide record is preview-only — in a recap it invited false causation
  ("extended MLS's record to 23-11-3" on one card, "22 wins, 12 losses" on another, same
  afternoon).
- **Player form from game logs, not the prop board** (`216ed83`). Props exist for MLB, MLS, UFC
  and WC only, so NBA/NFL/NHL stories had no form while 232,669 logs sat unread.
- **Postgame recaps** (`083213b`): a story written before kickoff is a preview by construction,
  so it is replaced once the game is final. `legendarypicks-game-recaps.timer` every 3h as the
  guarantee for games nobody opens; the scoreboard hook does the rest.
- **Props panel on game detail** (`59302c3`): settled lines with their actual values.
  **No hit rate** — we hold both sides of most lines (35 of 51 in one game), so any record
  would describe our storage layout, not our judgement.

---

## 5. Version bump — BLOCKED, and not by the props work

`scripts/release.sh` preflight fails on **12 blocking SCHEMA/SEASONS differences** between prod
and dev. None are props:

```
news_league_summaries        PROD only          (old news shape)
news_narratives.points       PROD only
news_items.conv_id           DEV only
news_narratives.conv_id / fan_voice / paragraph / title   DEV only
team_game_results.result     DEV only
player_game_logs   (mls, 2025), (ncaaf, 2025)             DEV only
team_stats_coverage (mls, 2025), (ncaaf, 2025)            DEV only
```

**Prod runs the old news schema.** Every card this release describes would land on a database
with no column to put it in. Migrate prod, then the gate opens.

Also unresolved: the version line has forked. `package.json` on dev says **0.7.7**; `v0.7.8` was
tagged on a docs commit with no bump; **`v0.7.9` and `v0.7.10` were cut on
`release/ewc-v0.7.10`, which is not an ancestor of dev** (33 commits there, 181 here). Release
notes for **v0.7.11** are written and committed (`3a79e2f`) but that number assumes the fork
stays unreconciled.

**Prod props are untouched** — ~600,944 rows carrying the original defect. Its own run, its own
backup.

---

## 6. Open, in the order I would take them

1. **Migrate prod's news schema** — the only thing between here and a release.
2. **Re-grade prod props** with `regrade_props.py` + `backfill_market_keys.py`, backup first.
3. **Reconcile the version fork** with `release/ewc-v0.7.10` before choosing a number.
4. **MLB dedupe** — 108 duplicate `mlbam_id` groups in dev. `TASK-mlb-dedupe-collisions.md`
   still reads "not started"; blocked on `UNIQUE constraint failed: player_stats.player_id,
   league, season, stat_type`. Commit `d869fa4` looks like it addressed the blocker but the
   dedupe was never re-run.
5. **`total_pitcher_walks` has no grading rule** — 0 of 36 settled in the sample game.
6. **`final_home` never populates for MLB**: the gate writes
   `result["scores"].get(game["home"])` but `game_result` keys scores by ABBREVIATION while
   `prop_games` stores full names. Harmless to grading, but every settlement run re-asks ESPN
   about games it already confirmed.
7. **One blank-name `players` row (28987)** holding 3,729 unattributable props. Quarantined by
   the endpoint, not repaired — the players are recoverable only by name-matching the market
   string, which is the repair that put a pitcher's name on batting rows in v0.7.5.
8. **`test_news.py` isolation** — passes alone (43), fails 7 in the full suite.

---

## 7. Design work — three artifacts, no app code changed

Published for review; the app still ships the old chip layout.

- Board, green/red — https://claude.ai/code/artifact/9b90472e-1fc0-44d4-b6cb-0f7641c7cb5b
- Board, honest-data-ui — https://claude.ai/code/artifact/9af60885-fd66-4d30-808e-545f8204d261
- Player cards — https://claude.ai/code/artifact/0f073f7b-9d9e-4431-943b-2022ff27a0ad

**The line is where the bar ends, not a mark inside it.** Taken from PrizePicks and Underdog,
which both show the number as progress TOWARD a projection rather than a value plotted against
a marker. The earlier version drew a hairline inside the track and gave the fill a hard edge,
so any result landing near its line put two verticals a pixel apart — making the marker fatter
only made a fatter thing to collide with.

`.claude/skills/honest-data-ui/SKILL.md` must be loaded **when writing the spec**, not when
building the UI. It was not, and the first pass broke the signature rule by spending the accent
on wins. Load it before the next surface.
