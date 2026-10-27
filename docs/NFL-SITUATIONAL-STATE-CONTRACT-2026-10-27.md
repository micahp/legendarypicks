# NFL situational state contract (v1)

Status: contract only, for review. No code reads or writes this contract yet. It defines what each layer may contain, when
it is frozen, and which parts a forecast or a simulator may use. It changes nothing in production. Dev-only.

Contract id: `lp-nfl-situational-state-1`. Rule regime: `nfl-rules-regime-v1` (see section 6).

## 1. Principle

Three kinds of information stay in separate layers, so that the same research can support retrospective splits and
future simulations without leaking one into the other.

| Layer | Question it answers | Frozen when | May a forecast use it? |
|---|---|---|---|
| Pregame | What could reasonably be predicted before kickoff? | At the cutoff of the forecast (see section 3) | Yes, if the cutoff rule is met |
| In-game | What decisions are possible on the next play? | Evolves play by play inside a simulation | Only inside a simulation run |
| Postgame | What actually happened? | After the game is final | Never as an input. Training and evaluation labels only |

The historical record tells us what happened. The frozen pregame state tells us what we could reasonably predict. The
simulator's evolving state decides which plays are possible next.

## 2. Pregame layer

Every field carries a source, a publication or observation time, and a confidence label (`verified`, `published`,
`derived`, `reconstructed`, or `unknown`). A field with no known time is never treated as verified.

| Group | Fields | Source (current) | Time basis | Confidence |
|---|---|---|---|---|
| Schedule | game id, season, week, game type, gameday, kickoff ET, weekday, teams, home or away | `nfl_schedule` | Schedule publication time (not stored; treat as known before season start for the regular season) | `published` |
| Calendar windows | ET window, venue-local window, body-clock window | Derived from kickoff and venue state | Same as schedule | `derived` |
| Venue | stadium, roof, surface, venue state, dated capacity, international flag | `nfl_game_context`, capacity history | Venue is known pregame; capacity is the dated figure for the season | `published` or `reconstructed` |
| Rest and travel | days since last game, bye, time-zone shift to kickoff, division | Derived from schedule | Computed from prior completed games only | `derived` |
| Forecast | temperature, wind, precipitation at the frozen cutoff | Frozen NWS forecast with issue time (2026 only so far) | Forecast issue time, which must precede the cutoff | `published` for 2026; none before 2026 |
| Officials | referee and crew | `nfl_game_officials`, `nfl_schedule.referee` | Publication time not stored; unknown | `unknown` until the publication time is verified |
| Expected starters | QB1, RB1, WR1 identity | Historical depth chart, usage prior, frozen full-depth roster (2026) | Depth chart time is unknown for history; the frozen roster has a time | `reconstructed` for history, `verified` only for frozen 2026 snapshots |
| Availability | include or exclude decision per player | Frozen availability snapshot (2026) | Freeze time, which must precede the cutoff | `published` for 2026 snapshots; none for history |
| Prior team strength | ratings from prior games only | Computed from games before the cutoff | Strictly prior games | `derived` |

Market prices, spreads and totals are never pregame fields for an independent model. The `market_spread` and
`market_total` columns in `game_projections` stay in a sealed external evaluation layer.

## 3. Cutoff rule

A pregame state is frozen at a cutoff `T`. Every field must satisfy its time basis before `T`.

- For a 2026 game with a frozen forecast, `T` is the forecast cutoff recorded in that snapshot.
- For a historical game, `T` is the scheduled kickoff minus a fixed margin (proposed: 24 hours). Any field whose publication
  time is unknown is excluded from strict tests and reported as a sensitivity case.
- A game is eligible for a test only if every field the model uses is available before `T`. The eligible-game list is
  written before the test runs, and it is the same for every model being compared.

## 4. In-game layer

Evolves inside a simulation and is never stored as history. It holds: quarter, clock in seconds, score, possession, down,
distance, yard line, personnel, drive index and drive history, and workload (snap counts and touches so far).

Legal game-rule state is part of this layer: timeouts remaining, the two-minute and end-of-half rules, overtime rules for
the season's rule regime, and kickoff rules. The rule regime is named explicitly (section 6).

The simulator reads the pregame layer at the start of a run, then maintains the in-game layer play by play. Historical
in-game values are reconstructed from play-by-play for research, never for pregame features.

## 5. Postgame layer

The full box score (`team_box_score`), actual weather, attendance and attendance percentage, final participation, officiating
outcomes, and player production. These are labels and research context. A postgame value may appear as a feature only
in a retrospective split, never in a forecast or a simulation input. Attendance and actual weather are postgame context.

## 6. Versions, snapshots and rule regimes

Every simulation or forecast records:

- its context snapshot id (a content hash of the pregame layer at the cutoff);
- its model version (for example `nfl-team-strength-S3 v1`);
- its rule-regime version;
- its eligibility list id;
- the time at which each pregame field was published or observed.

A rule regime is a dated set of game rules: overtime format, kickoff spot and touchback rules, the two-point and extra-point
rules, the timeout count, and any change to the playoff or tiebreak format. Historical games are grouped by regime, and a
comparison across regimes must say so. The regime version for each season is set once, and it is not changed afterwards.

Snapshots are immutable. A snapshot that is superseded is kept, and the new one carries a new id.

## 7. What the contract forbids

- Postgame values in any pregame field.
- Betting odds or market prices as an input to an independent model.
- A field with unknown publication time in a strict test.
- A rating revised after kickoff in a forecast made before that kickoff.
- Using 2026 games to choose, tune or confirm a model. The 2026 season is the sealed holdout.
- Changing an existing snapshot in place.

## 8. Open items

1. Officials' publication time. Until it is known, crew data is a sensitivity case only.
2. Historical forecasts. Only 2026 has frozen forecasts with issue times. Strict weather tests wait for archived forecasts
   (E1).
3. Historical availability. Only the 2026 frozen snapshots exist. Strict S4 tests cannot run on history.
4. The depth-chart publication time for 2010 to 2024. Until it is known, historical starter identity is `reconstructed`.
5. The rule-regime table. The regimes need to be listed season by season and reviewed.
