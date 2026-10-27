# Evidence bundle: 2026-10-27 identity incident

Durable copies of the evidence behind the incident diagnosis and the review pack. Each file is listed in
`SHA256SUMS`. To check them:

    cd docs/incidents/2026-10-27-identity-evidence && sha256sum -c SHA256SUMS

## Files

| File | What it is |
|---|---|
| `repair_stale_rows_old_values.json` | Original `team`, `team_code`, `player_id`, and `updated_at` for the three rows changed by the 2026-10-27 repair. |
| `restore_repaired_rows_original_draft.sql` | First draft of the restoration. Superseded by `restore_repaired_rows.py`. Kept for the record. |
| `restore_repaired_rows.py` | Reviewed restoration. Dry run by default. Writes only with `--apply`. Guards every row, expects exactly one row changed per target, and rolls back on any mismatch. |
| `mls_squads_2026-10-27_readonly.json` | Full FotMob (900 players) and MLS Soccer (955 players) squads, fetched read-only with the roster job's own providers on 2026-10-27. |
| `SHA256SUMS` | SHA-256 checksums for the files above. |

## Restoration: before and after

| League | Source | Key | Current (repaired) | Restored to | Guards |
|---|---|---|---|---|---|
| mls | fotmob | 1259117 | Paysandu, no code | Los Angeles FC, LAFC | team, team_code, player_id NULL, updated_at 2026-09-27 |
| lcup | fotmob | 1259117 | Paysandu, no code | Los Angeles FC, LAFC | same |
| mls | fotmob | 1787871 | CD FAS, no code | Red Bull New York, RBNY | team, team_code, player_id NULL, updated_at 2026-09-07 |

Dry run against prod on 2026-10-27, read only: all three guards pass. Expected row counts for `--apply`:
3 target rows matched, 1 row changed per target, 3 changed in total. Nothing was written.

## Not in this bundle

- The MLS snapshot implementation. It is approved for development and not yet built.
- The safeguard for the name-and-club path. Proposal only, in `unsafe-bind-safeguard-proposal.md`.
- The review branch `docs/incident-2026-10-27-review-pack`. It carries nine local dev commits that are not on
  `origin/dev`, including the identity switch and the stale-row check and its revert. It is not for merge.
