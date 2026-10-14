# Match simulator, step 2, 2026-10-14

Status: built and checked against a point-by-point Monte Carlo. Research code. It reads no data and writes nothing.
Its winner probability is not a headline model: the 2026-10-14 backtest found the point-model path loses to Elo on
winners (see `TENNIS-MATCH-BACKTEST-2026-10-14.md`). What the simulator is for is game, set, tiebreak and match-score
distributions. Those outputs are not yet validated against historical outcomes.

## Interface

The simulator takes two serve-point probabilities and a set of scoring rules. It does not import the point model, so
a later point model can replace it without changing this file.

    from tennis_match_sim import match_distribution, monte_carlo

    rules = {"bestOf": 3, "tiebreakAt": 6, "tiebreakPoints": 7,
             "finalSet": "tiebreak", "finalSetTiebreakAt": 6, "finalSetTiebreakPoints": 7}
    exact = match_distribution(0.65, 0.62, rules, first_server="A")
    sampled = monte_carlo(0.65, 0.62, rules, "A", n=100_000)   # the iterations setting

- `serve_a` is P(A wins a point when A serves). `serve_b` is the same for B. Both are inputs, not estimates.
- `match_distribution` returns exact values: `p_a`, `p_b`, `unresolved` (mass still in play after 400 games, which is
  below 1e-30 in every checked case), `match_scores` (winner's and loser's sets), `sets_played`, `total_games`,
  `expected_games`, `p_tiebreak_any`, `p_match_tiebreak` and `set_scores` (set number, winner, winner's games, loser's
  games).
- `monte_carlo` returns the same quantities as frequencies over `n` matches, with the sums needed for standard errors.

## Scoring rules

| Key | Meaning |
|---|---|
| `bestOf` | 3 or 5 |
| `tiebreakAt` | Games at which a tiebreak is played in a set that is not the final set. `None` for advantage sets. |
| `tiebreakPoints` | Points to win one of those tiebreaks |
| `finalSet` | `advantage` (no tiebreak, play on to a two-game lead), `tiebreak` (a tiebreak at `finalSetTiebreakAt` games), or `match_tiebreak` (a tiebreak to `finalSetTiebreakPoints` replaces the final set) |
| `finalSetTiebreakAt`, `finalSetTiebreakPoints` | As above, for the final set |

Conventions. The server alternates every game across the whole match. A set tiebreak counts as one game, so 7-6 is
13 games. A match tiebreak counts as zero games. The first server of a tiebreak is the player who serves the game
it replaces. Each set starts with the player who did not serve the last game of the previous set.

The historical event formats are not mapped here. The rules are inputs. A mapping needs a source for each event and
year. The backtest infers the match tiebreak only from the bracketed third-set score in the data (for example
`[10-8]`).

## Method

- **Game.** Closed form: P = p^4 (1 + 4q + 10q^2) + 20 (pq)^3 * p^2 / (p^2 + q^2), with q = 1 - p. The last term is deuce.
- **Tiebreak.** Exact dynamic programme over (A's points, B's points). The server of each point follows the rotation:
  the first server serves point 0, the other serves points 1 and 2, then the first serves 3 and 4, and so on.
- **Set and match.** Exact dynamic programme over games. The state is sets won, games in the current set, who serves
  next, and whether a tiebreak has been played. Each step is one game.
- **Monte Carlo.** The same rules, played point by point in separate code that shares no functions with the
  dynamic programme. It is the independent check.

## Verification

Unit tests (`backend/test_tennis_match_sim.py`, 44 tests):

- The game closed form equals the first-to-four-by-two race formula, to 1e-12, over a grid of point probabilities.
- The tiebreak dynamic programme equals the race formula when both servers win each point with the same probability,
  for tiebreaks to 7 and to 10, with either player serving first.
- The serve rotation is correct: one point, then two each, starting with the first server.
- Swapping the players and the first server gives the complement. Outcomes sum to one. Set one is played in every match.
- A match tiebreak occurs exactly when the sets are level at one all.
- A better server wins more matches.
- Monte Carlo agrees with the exact distribution, within sampling error.

Monte Carlo at 200,000 matches per case, over 6 formats, 4 serve pairs and 2 first servers (48 cases, seed 1). The
checker compares exact and simulated values for every quantity: match win, expected games, tiebreak and match-tiebreak
frequencies, sets played, match scores, and every set result. That is 7,224 quantities in all.

- Match-level probabilities use exact binomial p-values. Set results use exact Poisson p-values. The mean game count
  uses its sampling standard error.
- Pass rule: no p-value below 0.05 divided by 7,224 (a Bonferroni threshold of 6.9e-6).
- Result: passed. The smallest p-value is 1.3e-4, against the threshold of 6.9e-6. The largest difference between exact and
  simulated match probability is 0.0024, about 2 standard errors.

Verification history, kept on purpose:

1. A first run at 50,000 matches flagged one rare set result (a 19-17 advantage set, z = 4.59). A 400,000-match
   replication with two new seeds gave z = 0.17 and -0.14.
2. A run at 200,000 matches flagged a 22-20 advantage set (z = 5.51). Three checks followed. A set-level test of
   advantage sets over one million sets agreed for every result within 2.3 standard errors. A replicate at seed 9
   gave 5 occurrences against 6.5 expected. Seed 1 gave 1 against 6.5. The fault was in the checker. It used the
   observed count's own variance, which is tiny when a rare result appears once, so the normal z exploded. A Poisson
   standard error gives -2.2 for the same count.
3. The checker was rewritten to use exact tail probabilities, and the 200,000-match run was repeated. That run is the
   result above.

## Limits

- The point probability is constant within a match. There is no momentum, no pressure effect, and no serve variation
  by score. The point model supplies the probability, and the simulator does not model those effects.
- The match probability in the backtest averages over who serves first, because the first server is not known in
  advance.
- Advantage sets can run long. The residual mass past 400 games is reported as `unresolved`.
- The tiebreak dynamic programme drops masses below 1e-15 per state. The total error is far below any reported digit.
- Game and tiebreak outputs are checked. Set-score and total-games outputs have not yet been checked against historical
  outcomes. That is the next validation, and it is separate from the winner decision.

## Commands

    python3 backend/tennis_match_sim.py --serve-a 0.65 --serve-b 0.62 --best-of 3
    python3 backend/tennis_match_sim.py --verify 200000     # exit status 0 only if the verification passes
    python3 -m pytest backend/test_tennis_match_sim.py
