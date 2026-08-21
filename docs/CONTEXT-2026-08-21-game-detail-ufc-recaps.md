# Context Summary — Game Detail Snapshot Fallback + UFC Recap Grounding — August 21, 2026

## Boundary at handoff

- Repository: `/root/legendarypicks`, branch `dev`, **not pushed** to origin.
- Managed DEV: frontend `:3096`, backend `:8096`, public tunnel
  `https://resume-stress-education-pros.trycloudflare.com` — all running, none
  restarted.
- **Code changed on dev; prod still runs the old images.** The backend fixes
  below are code fixes, so they reach prod only on a rebuild (the roadmap rule:
  data fixes reach prod the moment they run, code fixes need a rebuild).
- Three commits landed on dev this session, all local-only:
  `f6745b1`, `8846f52`, `f9319c4` (details below).

## 1. Homepage prop-board links land on the Props tab

`f6745b1` — `pages/index.tsx` + `pages/props.tsx`.

- Both homepage "Browse the prop board" CTAs now link `/props?tab=props`
  instead of `/props`, so a visitor lands on the market-first Props tab, not
  the Slate tab.
- `props.tsx` gained `?tab=` deep-link support next to the existing `?date=`
  handling, validated against the TABS keys (a bogus value falls back to
  default).
- Verified live on dev: click-through from the homepage lands on the Props tab
  with the market board and date nav visible. Nav "Props" link untouched.

## 2. Finished games now render from scoreboard snapshots (the big one)

`8846f52` — `backend/_core.py`, `backend/routers/games/game_detail.py`,
`backend/core_stories.py`.

### The fault

Reported URL: `https://resume-stress-education-pros.trycloudflare.com/game/mlb/401877087`
(Braves 2-0 White Sox, a real finished game). It rendered **SCHEDULED**, no
score, AWAY/HOME placeholder teams — while the story below it correctly
described the 2-0 final.

Root cause: the game-detail endpoint's state/score/context chain only consulted
ESPN (`espn.game_result`, walled from this box since 2026-08-04) and
`team_game_results` / `game_context` (season-ingest tables that lag a game that
finished an hour ago). The one table that already had the truth —
`scoreboard_snapshots`, which the scoreboard API serves from — was never read
by the detail path. Same hole on prod.

### Sweep: it was every league, not just MLB

650 finished games across 8 leagues have a snapshot but no `team_game_results`
row (measured 08-20 on dev):

| league | finished games the detail page was blind to |
|---|---|
| mlb | 196 |
| atp | 158 |
| wta | 157 |
| lcup | 42 |
| ufc | 34 |
| mls | 31 |
| nfl | 17 |
| cod | 15 |

612 of them carry scores in the snapshot payload. All of these would have
rendered as SCHEDULED/no-score on the game page.

### The fix

- `_core.py`: three new DB-only helpers, zero ESPN requests:
  `_state_and_score_from_snapshot()`, `_context_from_snapshot()`,
  `_snapshot_result_info()`.
- `game_detail.py`: after `team_game_results` misses, fall back to the snapshot
  for state and final score; when the ESPN context fallback fails (walled), use
  the snapshot's team names. Guarded the two `final_score = _final_score_from_db(...)`
  assignments so a `None` (no DB row yet) can't clobber a snapshot score.
  UFC `outcome_method/round/clock` are now exposed on the detail payload.
- Verified live on dev: MLB 401877087 renders FINAL 2-0 with records (75-53 /
  66-61); UFC finals render FINAL with real fighter names.

## 3. UFC/tennis recaps were hallucinating winners — now grounded

Found while sweeping: the UFC game page for fight 401903488 (Contender Series,
Puga vs Trembley) showed a recap claiming **"T. Trembley defeated R. Puga"** —
the snapshot says **Puga won** (`winner: true`). The recap writer invented the
winner because `generate_game_story` calls `espn.game_result('ufc')`, which
404s (MMA has no summary endpoint), `teams` came back empty, and the generator
bailed before ever grounding the result.

### The fix (per-league result shapes, not one winner line)

- `core_stories.py`: when `espn.game_result` fails or a finished game has no
  scores, pull teams + result from the snapshot:
  - **UFC**: winner flag + finish method/round/clock → "Roman Puga defeated
    Taner Trembley by decision in round three, ending the bout at the 5:00
    mark" (verified).
  - **Tennis (atp/wta)**: winner = more sets won; the grounding names each
    side's sets ("Parks 1-6 Eala; ...") because a bare "1-6 | 6-4 | 2-6" was
    read backwards by the model (measured 08-20). Verified: WTA 182216 →
    "Eala defeated Parks 6-1, 4-6, 6-2".
  - **Soccer (mls/lcup/wc)**: uses the publisher's winner flag + draw/stage,
    already in the snapshot.

### Snapshot caveat

`outcome_method/round/clock` only exist for fights captured **after** the code
landed (`b9646f7`, 2026-08-19). Snapshots written before that (all older UFC
finals) carry the winner flag but no method — recaps say "won" without the
finish detail. `needs_refresh` retires a finished day, so nothing re-fetches
automatically; the 08-18 Contender Series slate was re-captured manually this
session (`scoreboard_store.save('ufc','2026-08-18',...)`) to prove the fix.

## 4. Tests

53 relevant tests pass: `test_postgame_story`, `test_espn_ufc_outcome`,
`test_game_detail_live_status`, `test_finality_gate_completed`,
`test_settlement_ufc_mls`, `test_link_prop_games_ufc`, `test_cod_scoreboard`.

`test_story_form_season.py` has one failing case (MLS: asserts logs are stale
at 2025, dev now has 2026) — **pre-existing data drift**, confirmed by
stash-testing on a clean tree. Not caused by this work.

## 5. UFC data we are throwing away — documented

`f9319c4` — `docs/UFC-DATA-THROWN-AWAY.md` (measured 08-20). Highlights:

- **Fights without props: everything.** The stats ingest targets
  `props JOIN prop_games`, so a card nobody prices gets zero stats, zero logs,
  and the game page says "Detailed stats aren't available for this sport yet."
- **Player page renders 5 of 48 stored fields** (Opponent/Date/Result/Sig Str/
  Takedowns). Knockdowns, the 9-cell strike breakdown, advances, reversals,
  submissions, control time, fight time, method are stored and never shown.
- **No UFC boxscore surface on the game page** (`hasGameTabs` is false for
  ufc); the model tab zeroes UFC projections.
- **`fetch_stats` shape loss**: keeps `name → value` only, reads
  `categories[0]` only, drops per-round splits, displayValue, and the
  opponent's stats unless the opponent is also priced.
- **Discarded entirely**: the fight timeline (`details[]`), officials, venue,
  broadcasts, per-round `linescores`, and the capability flags
  (`boxscoreAvailable`, `playByPlayAvailable`, ...) that exist on objects we
  already hold.

The doc ends with a size-of-fix table; biggest win per effort is targeting the
scoreboard card for stats instead of prop-linked fights only.

## Commits on dev (local-only, not pushed)

| commit | what |
|---|---|
| `f6745b1` | homepage prop CTAs → `/props?tab=props` + `?tab=` deep link |
| `8846f52` | detail endpoint snapshot fallback + recap winner grounding |
| `f9319c4` | docs/UFC-DATA-THROWN-AWAY.md |

## Do not regress

- Never let `_final_score_from_db` (None) clobber a snapshot final score.
- The detail path must stay DB-only on the request path — zero ESPN requests.
- Keep the per-league result shapes separate: UFC winner flag, tennis sets,
  soccer winner flag, scores for the rest. One generic "winner" line will
  mis-ground again.
- Do not restart dev services/tunnel to publish these changes; the backend at
  :8096 auto-reloads on code writes.
- Do not push or rebuild prod without separate authorization.
