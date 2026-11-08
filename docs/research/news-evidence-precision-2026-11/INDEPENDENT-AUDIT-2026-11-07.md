# News evidence audit — 2026-11-07

The audit recommends one label correction: update 645787 (Kerby Joseph) changes from IO / borderline=no to ID;IO / borderline=yes. Its PUP-R field is a non-game roster status, while the headline says “Remains out for Week 9” and the text reports coach Dan Campbell saying Joseph will not play against Miami in Week 9. Under RUBRIC.md, the game-specific OUT statement and PUP status support both codes. This interpretation treats the coach’s explicit no-play statement as a game-week OUT designation; it is retained as borderline because the text does not quote a formal game-status report.

## Method and limits

The rubric and both sample files were opened before the first judgment ledger was posted in the conversation. Labels were opened afterward. README.md and results.txt were not opened during the blind phase. The tables below are reconciled judgments after comparison, not an untouched blind-label artifact. The initial ledger covered 17 starter candidates, six status edge cases and all nine development records; five additional status cases were documented after label exposure. The 11 status cases here are the reviewer-selected edge set, not an independently recovered externally specified list of IDs. No claim of a second fully blinded review is made for the added cases.

The samples contain 277 precision records and nine separate development records. The precision sample has 165 nonempty injury_status fields: 99 QUESTIONABLE, eight OUT, three DOUBTFUL, 25 IR, 24 IR-R, five PUP-R and one RESERVE-DNR. Game-week values apply as ID when tied to a relevant upcoming game. IR-R and PUP-R remain non-game statuses: a practice window does not establish activation. Text mentions about other players or past games do not create subject claims.

## Comparison and corrections to the initial reviewer ledger

- Add ID to 645994, 645892 and 645771: their QUESTIONABLE fields were omitted from the initial starter-focused calls.
- Add IO to 645829: its IR-R field applies even though the possible starting role is hypothetical.
- Add SE to 645952 and 646053: each includes an expectation phrase as well as a definite starting statement; 645952 also includes coach confirmation.
- Remove SE from 645860: past starts and an expectation of retaining a role do not explicitly establish an upcoming start under the role-description clarification.
- Correct the transcription 645013 to 646013.
- Withdraw initial borderline=yes flags for 646008, 645952, 645902, 645860, 645807, 646013, 645992, 645977, 646054 and 646053. Their reconciled flag is no.

These are corrections to the reviewer’s initial ledger, not additional defects in the existing labels. After reconciliation, all starter and development labels agree with the existing CSVs. The remaining recommended CSV change is 645787. The four pre-existing borderline=yes entries (645969, 645834, 645810 and 645791) are supported; 645787 becomes the fifth.

The no-upcoming-game exceptions matter: 645834 is a free agent after removal from IR, and 645810 was cut from the practice-squad injured list, so their QUESTIONABLE fields are out of scope and both receive none. Update 645791 is currently on practice-squad IR and receives IO despite an OUT field and no upcoming game. Update 645969 receives both ID and IO because the text explicitly lists QUESTIONABLE for Thursday while the field remains IR-R. Forecast IR placement in 645773 does not establish current IO.

## Starter and coach examples

| update_id | Codes | Borderline | Evidence |
|---|---|---|---|
| 646008 | SE | no | should resume his role as starting slot CB |
| 646006 | SN | no | Will resume his role as one of the starting CBs; definite upcoming starter role. |
| 645994 | ID;SE | no | QUESTIONABLE field; in line for a conditional second start. |
| 645978 | SN | no | will be back in his starting role |
| 645970 | SE | no | will likely be back in his starting role |
| 645965 | SE | no | should be back in his starting role at FS |
| 645952 | SN;SE;CC | no | coach Minter named him starter Tuesday; still projects to start |
| 645902 | none | no | could step in as starter in Week 10: hypothetical, not this game |
| 645895 | SE | no | set to start Sunday per reporter, not a coach statement |
| 645892 | ID;SE | no | QUESTIONABLE field; slated to start Sunday per reporter. |
| 645860 | none | no | Comes up huge in Week 8 win |
| 645835 | SE | no | likely back in his starting role at RG |
| 645807 | SE | no | Listed as a starting receiver on an unofficial depth chart for Sunday; expected, not confirmed. |
| 645777 | SN;CC | no | coach Minter confirmed Fagnano will start Thursday |
| 645771 | ID;SE | no | favorite to start for Baltimore |
| 645829 | IO | no | could be moved into a starting role: hypothetical |
| 645873 | none | no | could start: hypothetical |

## Status edge cases

| update_id | Codes | Borderline | Evidence |
|---|---|---|---|
| 646013 | ID | no | QUESTIONABLE field; Limited practice Wednesday |
| 645992 | ID | no | QUESTIONABLE field; Limited Wednesday |
| 645969 | ID;IO | yes | IR-R field and text says questionable Thursday while still on IR pending activation; status sources conflict. |
| 645787 | ID;IO | yes | PUP-R field; headline says out for Week 9 and coach says will not play against Miami. Both game-week OUT and non-game PUP status; retain borderline for field/text eligibility interpretation. |
| 645791 | IO | yes | OUT field conflicts with practice-squad IR; no upcoming game, so field is off-scope. |
| 645977 | IO | no | PUP-R |
| 645834 | none | yes | QUESTIONABLE field conflicts with removal from IR/free-agent status; no upcoming game. |
| 645810 | none | yes | QUESTIONABLE field conflicts with cut from practice-squad injured list; no upcoming game. |
| 645925 | IO | no | IR-R field; Limited in return Wednesday |
| 645773 | ID | no | field OUT; text says IR-bound |
| 645877 | IO | no | IR-R field; Returning to practice Wednesday |

## Current-feed development sample

| update_id | Codes | Borderline | Evidence |
|---|---|---|---|
| 646054 | ID | no | QUESTIONABLE field; text says out Monday, no start claim for Murray |
| 646053 | SN;SE | no | headline says in line to draw start; analysis says Wentz will get QB assignment |
| 646052 | ID | no | QUESTIONABLE field; conditional start is for Sanders, not Watson |
| 646051 | ID | no | QUESTIONABLE field; practice update only |
| 646050 | ID | no | QUESTIONABLE field; practice update only |
| 646049 | ID | no | QUESTIONABLE field; practice update only |
| 646048 | none | no | kicking rotation described; no start decision |
| 646047 | none | no | past-game tackle recap; no start claim |
| 646046 | none | no | past-game tackle recap; no start claim |

## Validation

The CSV was parsed and compared with its Git baseline: only update 645787 changed, with row order, row count and all other records preserved. The report tables cover 17 starter cases, 11 status cases and nine development cases. Historical classifier score files remain historical and were not regenerated; this report makes no new classifier-performance claim.
