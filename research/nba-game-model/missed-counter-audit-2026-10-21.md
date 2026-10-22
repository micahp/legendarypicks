# NBA missed-counter reconciliation audit — 2026-10-21

## Scope and source snapshot

This is a read-only audit on branch `research/nba-missed-counter-audit-2026-10-21`, based on `research/nba-missed-payload-proof-2026-10-21` at `7fa69ed623b6a328f2b9ce54dfcfb0f3baeef544`. The export implementation cited below was read from the Git object `origin/dev` at `04a421cfb2b17c2e5c64518da04ecf257f122bc6`, not from a working-tree file. I extracted those committed modules under `/tmp` to execute the export against the copies.

Both dev databases were copied using SQLite source connections opened with `mode=ro`; the copies were chmod `0444` and queried with `mode=ro`. `LP_DB_PATH` and `NBA_MODEL_DB_PATH` pointed at those copies. No sweep was run and no database was written.

Scratch copies:

- `/tmp/nba-missed-counter-audit-z8fb65is/picks.dev.db`
- `/tmp/nba-missed-counter-audit-z8fb65is/nba-model.dev.sqlite3`

## Current copied-data result

At export time `2026-10-22T04:00:39Z`, the committed `04a421cf` `export_payload(season=2027)` returned **25 games**: 3 `locked` and 22 `preview`; it returned no `missed` or `unlocked` game rows. `records[model].missed` was **3 for each of G1, G2, and G3**.

At `2026-10-22T04:02:50Z`, the copied picks schedule had 14 qualifying tipped games. The model copy had 9 missed-event rows, all for the same three games that each have all three `late-preview-v1` locks. Their locks were made at the preview timestamp; their events were recorded at tipoff:

- `0022600005`: scheduled `02:00Z`, locked/previewed `01:52Z`, event `02:00Z`.
- `0022600092`: scheduled `02:00Z`, locked/previewed `01:52Z`, event `02:00Z`.
- `0022600093`: scheduled `02:30Z`, locked/previewed `02:22Z`, event `02:30Z`.

The other 11 tipped schedule games had neither a lock nor a missed event in this fresh copy. They also had no preview rows, so the committed exporter omitted them. This differs from the earlier 36-row payload artifact on the base branch: the old artifact represented those 11 games as missed and had 14 event pairs per model; the current copied model DB has only the 9 late-lock event rows.

The brief's expected class counts `11/3/3/0` and event total 14 were **not reproduced** from these current copies. The table separates the exact API payload from the 36-row union of tipped schedule games and future preview games:

| Class | Tipped schedule games (14) | Exact export games (25) | Schedule + preview audit union (36) | Missed event pairs counted per model |
|---|---:|---:|---:|---:|
| (a) No locks + missed event | 0 | 0 | 0 | G1 0 · G2 0 · G3 0 |
| (b) Locks + no missed event | 0 | 0 | 0 | G1 0 · G2 0 · G3 0 |
| (c) Locks + stale missed event | 3 | 3 | 3 | G1 3 · G2 3 · G3 3 |
| (d) No locks + no event | 11 | 22 | 33 | G1 0 · G2 0 · G3 0 |
| **Total** | **14** | **25** | **36** | **G1 3 · G2 3 · G3 3** |

The 36-row audit union is not the API payload: it adds the 11 schedule games missing from the exporter to its 22 future previews and 3 locks. The exporter itself contains 25 rows. In the tipped-only subset, class (d)'s 11 games are `0022600001`, `0022600002`, `0022600003`, `0022600004`, `0022600085`–`0022600089`, `0022600090`, and `0022600091`.

## Counting path and surfaces

In `origin/dev` `04a421cf`, `backend/nba_model_store.py:656-659` selects `(game_id, model)` pairs from `nba_model_lock_events` for `missed_t90_window`. `_record` stores the supplied integer as the `missed` field at `:618-624`; the per-model value is the number of event pairs for that model at `:756-766` (specifically `:758`). **The counter and the `status: "missed"` assignment use the same event set**, not different queries. The counter counts model/event pairs. The game-row status is assigned at game level from membership in that set at `:701-706`, after locked games are created at `:663-670` and excluded from preview processing at `:697-700`. Past preview rows without locks are assigned `status: "unlocked"` at `:729-734`.

The API route passes the exported payload through at `backend/routers/nba_model.py:55-65`. The proposed UI on this branch displays the value as `Missed: {record.missed}` at `components/Leagues/NbaModelTab.tsx:190`; `origin/dev` `04a421cf` only declares the field in its component type at `:48` and does not render that label.

Written reports that quote 14 are historical snapshots: `docs/NBA-LOCK-SWEEP-REPORT-VISIBILITY-2026-10-21.md:63-67` calls 14 both missed games and per-model missed counts; `research/nba-game-model/missed-payload-proof-2026-10-21.md:15,21` explains 14 as the counter from its earlier copy, and its JSON has `records.*.missed = 14` at lines 6422, 6437, and 6452. No README quote was found. Those artifacts should remain historical and be labeled according to the snapshot/meaning they measured.

## Stale-event contract

The late-lock path in `backend/nba_model_store.py:451-462` inserts lock rows; it does not delete or update lock events. `record_missed_windows` skips adding an event when a lock already exists and otherwise uses `INSERT OR IGNORE` at `:470-491`; it has no cleanup for an event that predates a late lock. No `DELETE` or `UPDATE` of `nba_model_lock_events` exists in the inspected `04a421cf` backend.

The table at `backend/nba_model_store.py:136-143` restricts `event_type` to `missed_t90_window` and has primary key `(game_id, model, event_type)`. Under the current check, a different superseding event type cannot be inserted. If the check were expanded, the key would permit an additional event row for that type, but would not replace the original missed event; the counter query would also need explicit supersession semantics.

## Candidate meanings and change surfaces

| Choice | Meaning and count in the earlier 36-row proof | Consequence for ledger/API/UI and written reports | Proposal-only files and lines |
|---|---|---|---|
| (i) Count games currently in `missed` state | 11 missed games per model | Aligns `records.*.missed` with the 11 missed cards in that earlier payload. It changes the field from event count 14 to game count 11; event rows remain untouched. On the fresh copy, the exact exporter has zero missed rows and the 11 no-lock tipped games are absent, so deriving 11 also requires restoring schedule-backed missed rows. Historical 14 reports must be labeled as event counts/as-of their old snapshot. | `backend/nba_model_store.py:758-766` for the counter; `:697-734` and `backend/routers/nba_model.py:55-65` if schedule-backed game rows are the source; branch UI `components/Leagues/NbaModelTab.tsx:190` can keep the label; annotate the cited historical report/proof lines above. |
| (ii) Count `missed_t90_window` events | 14 event pairs per model in the earlier copy; 3 in this fresh copy | Preserves the event ledger and old value for its original snapshot. It can exceed the missed game-card count when a late lock follows an event. The UI label `Missed` and the report row calling 14 “games with status=missed” are ambiguous/misleading unless called event counts. | Keep `backend/nba_model_store.py:656-659,758` and the API field. Relabel `components/Leagues/NbaModelTab.tsx:190` as missed events; clarify `docs/NBA-LOCK-SWEEP-REPORT-VISIBILITY-2026-10-21.md:66-67` and the proof report. |
| (iii) Split `missed` (11) and `late_locked` (3) | Shows both game-state and late-lock counts; totals 14 event pairs in the earlier copy | Makes the old discrepancy explicit without discarding the event history. On the fresh copy it would be 0 emitted missed rows + 3 late-locked rows until the 11 schedule games are represented again. Existing `missed: 14` reports remain historical event totals, not the new `missed` field. | Add both fields in `backend/nba_model_store.py:756-766` and represent schedule-backed misses via `:697-734`/router `:55-65`; extend the feature UI record type at `components/Leagues/NbaModelTab.tsx:48` and display both at `:190`; annotate the report/proof artifacts above. |

## Real-file hash check

Main-file SHA-256 before the copies, at `2026-10-21 22:58:20 CDT`:

- `backend/data/picks.dev.db`: `0f433747b4858e8919e58e18ddc9b795e2bc3a9227b9d0278721bee73a0d9ed6`
- `backend/data/nba-model.dev.sqlite3`: `904995d294a926a35e2312824d2f1196978d6478c1d570a640b003789f7bc6490`

Final main-file SHA-256 after the copy/export, at `2026-10-21 23:05:16 CDT`:

- `backend/data/picks.dev.db`: `0f433747b4858e8919e58e18ddc9b795e2bc3a9227b9d0278721bee73a0d9ed6` (unchanged)
- `backend/data/nba-model.dev.sqlite3`: `f40b4d750c9acbb3695e96257363a4b8d1714fd642de48ee92794642fb95599d` (changed; main-file mtime advanced from `22:52:01` to `23:02:27` CDT)

The live picks DB WAL was present and changed during the audit; at `23:04:18 CDT` it was 5,417,832 bytes. Thus the unchanged picks main-file hash alone does not prove an unchanged logical SQLite state. The model-file drift occurred while dev services were active; the audit used read-only source connections and did not write either real DB. The supplied preview-timer schedule is a plausible background writer, but the observed model mtime was `23:02`, so this audit cannot attribute that write to a specific timer tick.

## Recommendation

Recommendation (proposal only): have Micah choose whether `missed` means current game state or per-model event count before changing the field or its UI label; make no semantic change until that choice is explicit.
