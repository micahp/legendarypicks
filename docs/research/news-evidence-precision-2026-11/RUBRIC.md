# Gold rubric for the news-evidence classifier (fixed before labelling)

Subject: the update's Player element. A claim counts only if it is about the subject.
Each item gets a set of codes. Labels were written from the text and the status field,
before the classifier was run on the sample.

- SN starter_named: the text says the subject starts, or was named starter, for the upcoming game
  as a decision already made ("named Week 9 starter", "will start", "is starting Sunday").
- SE starter_expected: a reporter or analyst expects or projects the subject to start ("expected to
  start", "in line to start", "likely to start", "set to start", "slated to start", "should start",
  "favored to start"). Not an official decision.
- CC coach_confirmation_reported: a coach or team statement confirms the start decision for the subject.
- ID injury_designation: a game-week designation (OUT, DOUBTFUL, QUESTIONABLE, PROBABLE) for the upcoming
  game, in the Injury Status field or stated in the text.
- IO injury_status_other: a non-game status (IR, PUP, suspended, and similar) in the status field or text.

Not a claim (no code): negated or ruled-out starts ("will not start", "unlikely to start"), hypothetical
("could start", "might start", "competing for the job"), role descriptions without a start decision ("the
team's No. 1 back", "lead RB"), fantasy and projection talk, and designations for a past game only.

Ambiguous (code "?"): the sentence is about two players and the text does not say which one is the subject.
Ambiguous items are counted and excluded from the scores. They are not scored as wrong.

## Independent-review clarifications (2026-11-05)

The rules above were frozen before initial labelling. After the blind second review, these interpretations were applied to the corrected labels:

- A definite future statement that a player will resume a starting role (for example, one of the starting cornerbacks) is SN. A player listed as a starter on an unofficial depth chart for an upcoming game is SE, since it reports an expectation rather than a confirmed team decision.
- General role descriptions do not establish a start decision. “No. 1 running back,” “continue to lead the offense,” and game-specific kicking duties are not SN/SE/CC without an explicit starting claim. A coach assigning kicking duties does not alone count as coach confirmation of a start.
- “DNP to start Week N” describes when the player may be inactive, not that the player will start.
- ID requires a relevant upcoming game. A status field on a player with no team or upcoming game is out of scope when the accompanying roster transaction says the player is a free agent or on a practice squad. A current non-game status such as practice-squad IR remains IO.
- If the field reports IR/PUP and the text reports a game-week designation for the upcoming game, label both IO and ID. Keep the item borderline when those sources conflict on game eligibility.
