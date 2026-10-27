# NHL shootout completion-marker reconciliation

Date: 2026-10-27  
Scope: explain the 2021 difference between shootout games and `shootout-complete` event rows using the verified PBP and box-score archive. Diagnostic only; no simulator, rule gate, or historical result is changed.

## Result

The eligible 2021 population has 1,292 games. 95 distinct games end in a shootout according to the independently reconciled game summary; the same 95 games have a PBP shootout period and 95 games have at least one completion marker. The archive contains 96 marker event rows because game `2021020336` has two consecutive `shootout-complete` records.

The two records are event IDs 816 and 817, sort orders 695 and 696, both in SO period 5 at 00:00. Both have no event details. The preceding event is `shot-on-goal` (ID 810); the following event is `period-end` (ID 818). The flagged game has 14 attempt events and 3 goals in its SO period. This establishes a duplicate marker record in the archived event stream, not a second shootout game or additional play.

Across all 95 shootout games, the archive contains 702 attempt events and 210 goals. Use **95 distinct games** as the shootout-game denominator; retain **96** only when reporting completion-marker event rows.

## Reconciliation checks

- Eligible 2021 PBP bodies checked against pinned compressed size and SHA-256: 1,292.
- Independent game-summary SO set equals the PBP SO-period set: **True**.
- Independent game-summary SO set equals the distinct marker-game set: **True**.
- Games missing a marker: [].
- Marker games not ending in SO: [].
- Duplicate-marker game IDs: ['2021020336'].

The marker's duplication does not invalidate the 95-game denominator. The event count of 96 is a valid count of records as stored, but must not be reported as 96 shootout games.

## Provenance

PBP manifest SHA-256: `d87e40a3387f014429377cc8dfb010cec8ca2d0e4d03d0b5bdbfacd8de9ca990`  
Box-score manifest SHA-256: `0ba44bcebefecb0a8eefbea995e8f5370583600eec77d0be12be574f308d71a2`  
Game `2021020336` compressed PBP SHA-256: `33b48d86bebd00ae6cc5222ad00f5f0ae232f47d49bd0e25765a8e1ec298e21d`  
Audit script SHA-256: `ebdc0abc223ad7fed415989efdcb7b09e119e758be497d63e125a1abd51890f3`
