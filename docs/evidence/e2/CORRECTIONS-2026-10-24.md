# Corrections to the frozen E2 evidence package (a442dcd7)

The evidence package at `a442dcd7` is frozen and is not edited. Its corrections are recorded here, on the successor branch.

## Legality fixture count

The package counts the independent legality tests as **14 tests: two positive and twelve negative fixtures**.

- Positive (must pass): the frozen seed-1 record is legal; a blocked record that is not complete is legal.
- Negative fixtures (must fail, each on its named check): a clock that rises inside a quarter; a quarter that falls; points that
  disagree with the drives; a drive index out of sequence; a timeout count of four; timeouts that do not reset at halftime; a
  blocked record marked complete; a down of five; a field position of 120; a punt that returns the ball to the punting side; a
  complete game ending above zero; a touchdown recorded with three points.

The package does not describe these as "fourteen negative fixtures". The sentence that counts the tests reads "14 tests, two
positive and twelve negative", and the split is correct. The split is now pinned by `FixtureSplit` in
`scripts/nfl_sequence/evidence_e2/test_legality.py`, which fails if the counts change.

## Other changes made on this branch

The engine repairs on this branch change the engine's behaviour. They are listed in the branch's commit messages and in
`docs/SEQUENCE-E2-SUCCESSOR-REPAIRS-2026-10-24.md`. The frozen survey CSV and the frozen fixtures are not regenerated, so they
still describe `a442dcd7`.
