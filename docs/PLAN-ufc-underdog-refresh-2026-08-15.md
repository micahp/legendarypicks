# UFC Underdog refresh — plan

## Goal

Make the public Underdog UFC board a second, continuously refreshed source on
the existing `/props` slate without creating duplicate fighters or quietly
discarding source mismatches.

## Published inputs and scope

- **Props and count oracle:** one `GET`
  `https://api.underdogfantasy.com/beta/v5/over_under_lines` per run. The
  endpoint is an unfiltered bulk book; do not fan out requests or re-fetch it
  for each fight. The parser reports its number of scheduled MMA source games,
  fighters, and balanced primary-line props before it writes anything.
- **Event identity:** Underdog `solo_games.id` and `players.id` are the source
  keys. The existing `players.id` and `prop_games.id` remain LegendaryPicks'
  canonical keys.
- **Board:** scheduled UFC fights only; existing five balanced whole-fight
  markets (`significant_strikes`, `submissions`, `knockouts`, `fight_time`,
  `finishes`). No UI/styling changes and no attempt to compare a non-overlapping
  Bovada decision line with an Underdog stat/outcome line.

## Identity and write contract

1. Add `player_source_ids(source, league, source_player_key, player_id, ...)`
   and `prop_game_source_ids(source, league, source_game_key, game_id, ...)`.
   A native key can map to exactly one canonical row.
2. Resolve an incoming fighter by an existing source-key mapping first, then
   by a single exact canonical name or reviewed `name_alias`. Never use fuzzy
   matching and never insert `players` from an Underdog display name.
3. When no safe mapping exists, write/update one `unresolved_players` record
   keyed by `source='underdog'`, league, and the native player id, with a reason.
   Skip that entire fight; do not create an empty game or partial board.
4. With two resolved fighters, find an existing same-date UFC game by the two
   canonical fighter ids already attached to props. If none exists, create a
   single canonical game only after both fighter identities are safe. Bind the
   native source-game id, rejecting any source-key conflict.
5. Upsert only `source='underdog'` props. The run prints parsed, resolved,
   skipped, and written counts and exits non-zero when a non-empty source board
   yields no eligible props, so a timer cannot look healthy while doing nothing.

## Verification and promotion

1. Unit-test source-key reuse, exact/alias resolution, an unresolved name,
   key conflicts, idempotent prop upserts, and no-player-creation behavior.
2. Copy the managed DEV SQLite database with the SQLite backup API; record a
   pre/post fingerprint and `PRAGMA quick_check`. Run one actual Underdog fetch
   against that disposable clone only after unit tests pass.
3. Compare clone counts to the source parser's reported scheduled MMA count;
   inspect the current card rows and confirm no duplicate `players` were
   created. Resolve the one-letter Kaua/Kaue discrepancy only through a reviewed
   alias/source-key binding; otherwise let it remain loudly queued.
4. Merge the verified code to managed `dev`, make one controlled live DEV
   refresh, then re-run fingerprints, integrity, source/market counts and the
   existing `/api/props/slate` contract. Do not restart the managed frontend,
   backend, or tunnel.
5. Install a DEV-only systemd oneshot and 30-minute timer, protected by
   non-blocking `flock`, only after the live refresh passes. Production is out
   of scope.

## Explicit non-goals

- No PrizePicks bypass (the public API is currently blocked) and no Sleeper
  player-directory scrape presented as a props source.
- No backfill, no broad provider dump, no fuzzy athlete consolidation, no
  production data/service changes.

## Evidence recorded during implementation

- The one controlled Underdog request published **5 scheduled MMA games, 10
  fighters, and 66 balanced UFC props**. Before the reviewed correction, the
  clone accepted 52 props across four games and loudly rejected the 14-prop
  Kaua/Kaue game; its `players` count stayed 53,340.
- One ESPN scoreboard request for 2026-08-15 returned UFC event `600059185` and
  published the fighter as **Kauê Fernandes**. The review migration changes the
  existing row to that canonical display name, retains `Kaua Fernandes` and
  `Kaue Fernandes` as aliases, and binds only Underdog native id
  `7c2bea83-5af4-44e3-952a-6b2bcd6f94e9`.
- The managed DEV and disposable clone both already had 78 legacy
  `props.player_id` foreign-key residues. The clone added none; that pre-existing
  repair remains out of this task's scope.
