# NBA missed-payload proof — 2026-10-21

Branch: `research/nba-missed-payload-proof-2026-10-21`, based on `3fc0ad81a6dd01487bb45c543a8f09097782421b`.

## Component behavior

The sectioning test was added and run against the base first. It failed there because `BOS at DET` was reachable inside the `Upcoming forecasts` region; the other four tests passed. The component now filters `status: "missed"` out of Upcoming and renders those rows under `Missed lock windows ({count})`, reusing the existing forecast card markup.

The updated Jest run passed all six tests, including the real-export render and a programmatic key/type subset check between the hand-written fixture and a real missed row.

## Scratch-copy export

The runner and export used `/tmp/nba-missed-payload-proof-mdlxtg83/nba-model.dev.sqlite3` and `/tmp/nba-missed-payload-proof-mdlxtg83/picks.dev.db`, with `NBA_MODEL_DB_PATH` and `LP_DB_PATH` pointed at those copies. Export time was `2026-10-22T03:49:19Z`. The complete payload is in [missed-payload-proof-2026-10-21.json](./missed-payload-proof-2026-10-21.json).

At `2026-10-22T03:51:47Z`, the copied payload status counts before the repeat sweep were 11 `missed`, 3 `locked`, and 22 `preview` (36 total). The repeat sweep reported `missed_window_games: 11` and `missed_lock_events: 0`; the corresponding events were already present. The after-sweep status counts were unchanged: 11 `missed`, 3 `locked`, and 22 `preview`. Each model's `records.missed` is 14.

The 11 exported missed IDs exactly match the qualifying tipped schedule games with no lock:

`0022600001`, `0022600002`, `0022600003`, `0022600004`, `0022600085`, `0022600086`, `0022600087`, `0022600088`, `0022600089`, `0022600090`, `0022600091`.

Three other tipped games have all three model locks and also retain stale `missed_t90_window` events: `0022600005`, `0022600092`, and `0022600093`. The exporter correctly emits those three as `locked`, not `missed`; their stale events nevertheless inflate each model's missed counter to 14. Therefore the requested assertion that the real export contains 14 missed game rows does not hold for this DB snapshot. The API/lock data was not changed because those edits are outside this task's scope.

Every exported `missed` row was programmatically checked for an empty `models` object, populated team IDs, and a scheduled start before export time. The UI test renders a missed row from this exact JSON payload under the separate missed heading and confirms a future preview remains under Upcoming.

## Real DB hash check

Hashes captured before the copies were made:

- `backend/data/picks.dev.db`: `d7d19b174ce82dbf4a6df6959611a33289c82ebc085fa9fb7fe4b4c86a9a4d63`
- `backend/data/nba-model.dev.sqlite3`: `1680ace4b528e827e2312824d2f1196978d6478c1d570a640b003789f7bc6490`

Hashes checked after the scratch sweep/export:

- `backend/data/picks.dev.db`: `7a413b7d07f0fa91c73cdc46e8ebf94217db0e19e6a09845357844092a203654`
- `backend/data/nba-model.dev.sqlite3`: `1680ace4b528e827e2312824d2f1196978d6478c1d570a640b003789f7bc6490`

The model DB hash is unchanged. The picks DB hash differs. Its main file and WAL modification times advanced to `2026-10-21 22:50` local while the dev service was active, indicating an external concurrent write; this task's sweep and export were directed only at the scratch copies. The requested identical-hash condition for the picks DB cannot be claimed.

## Scope

Changes are limited to `NbaModelTab.tsx`, its Jest test, and these scratch-proof artifacts. No API, lock rule, gate, model version, or coefficient was changed.

This UI change separates all `status: "missed"` rows it receives from Upcoming. The measured export contains 11 such rows, not 14; a merged build will therefore show 11 missed games separately for this snapshot, while the three locked games remain represented as locked.
