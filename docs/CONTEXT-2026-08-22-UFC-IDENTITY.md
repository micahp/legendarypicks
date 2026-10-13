# Context Summary — UFC Underdog Identity Repair — August 22, 2026

## Scope and boundary

- Repository: `/root/legendarypicks`, managed `dev` worktree.
- Target database: `/root/legendarypicks/backend/data/picks.dev.db` only.
- This repair does not touch production, services, the public tunnel, or Git
  remotes.
- The write is limited to reviewed UFC canonical display labels, `name_alias`,
  and immutable Underdog source-key bindings.  The subsequent scheduled or
  explicitly-run ingest is responsible for publishing props.

## Observed August 22 UFC coverage gap

The current DEV database has 179 `source='underdog'` UFC props across 9 of the
13 fights on the `2026-08-22` card. Four fights had no linked Underdog props.
The raw retained RotoWire archive
`backend/data/rotowire-archive/rotowire-2026-08-22.json.gz` independently
contains UnderDog offers for both fighters in these two wholly absent fights:

| Fight | Raw publisher names | Current canonical names | Result before repair |
|---|---|---|---|
| Roman Dolidze vs Reinier de Ridder | Roman Dolidze; Reinier de Ridder | Roman Dolidze; Reinier De Ridder | rejected |
| Serghei Spivac vs Vitor Petrino | Serghei Spivac; Vitor Petrino | Sergey Spivak; Vitor Petrino | rejected |

The direct Underdog writer (`backend/ingest_underdog_props.py`) is the current
UFC writer. RotoWire is a retained comparison relay here, not the writer. The
writer correctly fails closed: if either native fighter id cannot resolve to
one canonical player, it rejects the entire fight.

## Independent ESPN authority

One live ESPN UFC scoreboard request for card `600060493` confirms the
publisher spellings exactly:

- `401887539`: Roman Dolidze vs **Reinier de Ridder**
- `401887540`: **Serghei Spivac** vs Vitor Petrino

ESPN also confirms the canonical short forms needed for the two partial
UnderDog failures: `Wes Schultz` (UnderDog `Wesley Schultz`) and `Chris
Padilla` (UnderDog `Christopher Padilla`).

## Authorized repair plan

Use ESPN’s published display names as canonical, retain historical/alternate
spellings as reviewed aliases, and bind only the observed immutable UnderDog
native ids. The repair must be atomic, refuse ambiguous identities or a
conflicting key, and be tested on a disposable SQLite fixture before applying
to DEV.

| Canonical ESPN display | Preserved alias / source display |
|---|---|
| Reinier de Ridder | Reinier De Ridder |
| Serghei Spivac | Sergey Spivak |
| Wes Schultz | Wesley Schultz |
| Chris Padilla | Christopher Padilla |

Before the DEV apply, back up the absolute database path and fingerprint the
affected identity and props tables. After it, verify `PRAGMA quick_check`, the
four UnderDog source-key bindings, and a bounded single fetch/ingest coverage
report. Do not claim production parity: production has no current UnderDog UFC
props and is out of scope.

## Completed DEV repair

- Backup: `backend/data/picks.dev.db.pre-ufc-identity-20260822.bak`.
- `apply_reviewed_ufc_identity.py --apply` bound all four reviewed native
  UnderDog ids and corrected the two ESPN canonical display labels.
- Focused identity suite: **10/10 passed**.
- One low-priority UnderDog bulk refresh returned **13 scheduled fights, 26
  fighters, and 170 balanced props**. All **13/13** source games resolved; it
  rejected **0** games and queued **0** fighters.
- Database verification found the four formerly missing fights with 13, 13, 14,
  and 12 UnderDog props respectively (Spivac/Petrino, Dolidze/de Ridder,
  McVey/Schultz, Haqparast/Padilla). `PRAGMA quick_check` passed.
