# SLC execution path: silent failures and fabricated defaults

Repo: `slc` (branch `slc-v2`, HEAD `d490757e6`). Audit date: 2026-11-08.
Method: read the 17 scoped files in full, then followed every call site that touched a reported output, a
legality check or a tracked counter (`slc_engine.py`, `pre_event.py`, `render_slc_run_report.py`,
`render_week8_matchup_report.py`, `pregame_batch.py`, `football_assertions.py`, `slc_config.py`).
Pattern hits (`except`, `.get(key, default)`, `or 0`, `assert`, `warnings`) were then inspected in context;
hits that are properly guarded are in **Appendix A**, not in the findings. Empirical counts were taken from the
committed Sunday smoke bundle (`docs/research/slc-sunday-smoke-2026-11-08/`) and one committed full-stack batch
payload (`docs/research/slc-week8-player-workload-10k-2026-10-30/.../seed-4382.json`). The dev SQLite database
(`/root/legendarypicks/backend/data/picks.dev.db`) is not in this workspace, so fallback frequencies that need
the database could not be measured; every such finding says so.

## Bottom line

- **Findings: 1 HIGH, 5 MEDIUM, 7 LOW.**
- **The single worst is `slc_outputs.py:81`** (with `:39` and the guard at `:444`): a player row with no
  `roster_eligible` field is written to the box score as `roster_eligible: true`. All 13 Sunday-smoke snapshots
  are plain depth-chart snapshots that carry no such field (497/497 player rows), yet all 497 box-score player
  rows report `true`, and the `ILLEGAL_STATE` refusal at `:444` can therefore never fire for that snapshot
  format. The report renderer already accepts `None` as "unknown" for this column
  (`render_week8_matchup_report.py:197-198`); the writer never emits it.
- **Direct question 1 — does the batch RUN report its fallback/level counts anywhere a reader would see them?**
  **Yes in the machine record, no in the reader-facing artifacts.** `run_batch` aggregates them into
  `execution_verification.fallback_events` and (with blocker fixes) `blocker_resolution.counts_by_level /
  runtime_metrics / fallback_usage_by_team_situation` of the batch JSON, and each seed's ledger row carries its
  own `outcome.playcall.fallback_events`. But the console summary, `smoke-table.csv`, and
  `render_slc_run_report.py` never print or read them. Empirically the 13 `valid_full_game: true` smoke seeds
  carry 368-602 recorded fallback events each (19-24 distinct kinds), and the reader-facing table shows only
  "valid" with no fallback column.
- **Direct question 2 — does any code path turn a missing value into a plausible number?** **Yes, several**
  (F1-F6 and F10-F12 below). The most direct are `roster_eligible` missing -> `true` (F1), a missing team
  cell/event ratio -> neutral `1.0` (F3), a missing call-conditioned grouping cell -> unconditioned grouping
  (F4), a missing play-extras row -> `timeout=0 / out_of_bounds=0` (F5), and a missing role-specific yard field
  -> `yards_gained` (F6).
- Doctrine compliance of the 19 `except` sites in scope: **0 bare `except:`, 0 `assert` used for control flow,
  0 exceptions re-raised with their cause discarded**; 11 sites retain or re-raise the failure with evidence,
  2 only protect a type coercion, and 6 substitute a silent value (the sites in F4/F5/F7/F9/F12 below).

## Findings

### F1 (HIGH) - missing `roster_eligible` becomes `true`, and the roster-legality check can never fire

`scripts/nfl_sequence/slc_outputs.py:81`, `:39`, guard at `:444`:

```python
# slc_outputs.py:81  (_roster_index)
                'roster_eligible': bool(player.get('roster_eligible', True)),
# slc_outputs.py:39  (_depth_chart_qb1)
        if player.get('pos_abb') != 'QB' or not player.get('roster_eligible', True):
# slc_outputs.py:444  (build_boxscore)
        if meta is not None and not meta['roster_eligible'] and has_opportunity:
```

The field is optional in the input and defaults to the *permissive* value. The report renderer treats absence
as unknown, so the schema clearly has an unknown state:

```python
# render_week8_matchup_report.py:197-198
                    eligible = player.get('roster_eligible')
                    eligible_label = 'unknown' if eligible is None else str(bool(eligible)).lower()
```

What goes wrong silently:

- **FROM** "the snapshot never asserted this player's roster eligibility" **TO** `roster_eligible: true` on
  every player row of every box score. The output record carries a claim the input did not make, and the
  renderer's `unknown` branch for this column is unreachable.
- The `ILLEGAL_STATE` legality refusal at `:444` ("SLC participant {key} has a stat opportunity but is not
  roster-eligible") is disabled for every snapshot format that does not carry the field (plain
  `pregame_snapshot.build` output), because `meta['roster_eligible']` is always `True`.
- **Does the run record that it happened?** No. Nothing in the batch payload or the box score says that the
  field was absent or defaulted.

Empirical, committed artifacts (all 13 smoke snapshots, all 13 smoke boxscores):

```
snapshots 13; players 497; without roster_eligible 497
boxscore player rows 497; roster_eligible values {'True': 497}
```

The Sunday smoke bundle's 13 snapshots are plain depth-chart snapshots (`2026_09_CIN_ATL.json` home player
keys: `gsis_id, ingested_at, player_id, player_name, pos_abb, pos_rank, snapshot_at, source, team`), and those
runs all claim `valid_full_game: true` in `smoke-table.csv`. The committed test that exercises `:444`
sets the flag explicitly (`test_slc_boxscore_invariants.py:41`, asserting the `ILLEGAL_STATE` refusal at
`:50-54`), i.e. it proves the guard works only on a snapshot format the smoke runs did not use.

Output affected: reported boolean per player; a legality refusal path.

Obvious targeted fix (keep the unknown state, and stop treating absence as eligible in the two consumers):

```python
'roster_eligible': player['roster_eligible'] if isinstance(player.get('roster_eligible'), bool) else None,
...
if meta is not None and meta.get('roster_eligible') is False and has_opportunity:
...
if player.get('pos_abb') != 'QB' or player.get('roster_eligible') is False:   # :39
```

(`share_distributions.eligible_players:204` uses `p.get('roster_eligible', True)` too; with the writer fixed,
that is still only a chooser default, but it means a marker of `False` is the only thing that excludes a
player from the participant model.)

### F2 (MEDIUM) - fallback/level counters are produced but never reach the reader-facing artifacts

Counters are produced per seed and aggregated:

```python
# simulate_pregame_batch.py:683
    fallback_events = defaultdict(int)
# simulate_pregame_batch.py:692-693
        for name, count in (playcall.get('fallback_events') or {}).items():
            fallback_events[name] += int(count)
# simulate_pregame_batch.py:717
        'fallback_events': dict(sorted(fallback_events.items())),
# simulate_pregame_batch.py:1147
        'execution_verification': _execution_verification(outcomes, profile_manifest),
```

and per seed, in the ledger:

```python
# simulate_pregame_batch.py:501-502
    if decisions is not None:
        outcome['playcall'] = slc_engine.summary(decisions, record)
```

`_execution_verification` also carries `blocker_resolution.counts_by_level`,
`blocker_resolution.runtime_metrics` and `blocker_resolution.fallback_usage_by_team_situation`
(`simulate_pregame_batch.py:762-765`); one committed full-stack payload contains, for a single seed:
`fg_fallback_level:league_distance_curve: 8`, `fg_rejection_reason:beyond_observed_maximum: 17`,
`player_outcome_no_history_receiver: 3`, etc.

But the human/reader path is empty:

- the end-of-run console line prints only validation coverage (`simulate_pregame_batch.py:1189-1191`:
  `wrote {out}: {valid}/{games} valid games, ... ties, ... blocked`); no fallback count;
- the aggregate summary from `pregame_batch.summarize_outcomes` has no fallback field
  (`pregame_batch.py:99-122`);
- `render_slc_run_report.py` has **no** occurrence of `fallback` or `execution_verification` (grep);
- the committed smoke bundle does not include the batch JSON at all, and `smoke-table.csv`'s columns are
  `game_id,seeds_requested,seed_status,complete_game,valid_full_game,blocker,away_points,home_points,
  validation_error,reconciliation_status,evaluation_class,verified,unverified_inputs,snapshot_sha256,
  snapshot_as_of,built_at_utc,snapshot_date_utc,kickoff_utc` - no fallback/level column.

Empirically, each of the 13 `valid_full_game: true` smoke seeds has 368-602 recorded fallback events over
19-24 kinds (CIN_ATL: 415 events, 20 kinds), e.g. `kick decision: historical share of this situation cell
(not yet modelled): 11`, `no_source_rows_at_exact_yardline: 20`, `no_source_rows_for_current_streak: 8`,
`no_target_identity_match_in_event_cell: 10`, plus hundreds of `decision_row_missing_category_*`. A reader of
the table sees "valid" and no hint of any of it.

What goes wrong silently: a defect that only shows up as a rising fallback count (e.g. every target-role
draw finding no identity match) is visible only to someone who opens the per-seed ledger or the batch JSON.
`valid_full_game` is a rules/input-provenance claim, not evidence that the model ran without fallbacks; the
table does not say so.

Fix: one line in the console summary and a fallback column set in the smoke table are enough to stop this
being a "counter nobody reads"; the data already exists.

### F3 (MEDIUM) - a missing team-tendency cell silently becomes the league ratio `1.0`

`scripts/nfl_sequence/team_tendency.py:39-43`:

```python
    def ratio(self, side, team, cell, event):
        by_team = self.ratios[side]
        if team not in by_team:
            raise ValueError(f'no {side} tendency for team {team!r} in the prior seasons')
        return by_team[team].get(cell_name(cell), {}).get(event, 1.0)
```

- **FROM** the team's own event ratio in this situation cell (e.g. `0.83` or `1.27`) **TO** `1.0`, i.e. the
  league/base mix, whenever the team has no prior-season sample in the cell (or the cell has no count for that
  event). The whole-team miss raises; the cell miss does not.
- **Does the run record it?** No. The only recorded team-tendency fallback is the whole-team miss, caught at

```python
# slc_playcall.py:780-786  (_outcome_weight)
            try:
                weight *= self.team_outcomes.ratio(side, team, cell, event)
            except ValueError:  # no prior-season sample for this team
                self._current_team_outcome_fallbacks.append(
                    f'no_prior_sample:{side}:{team}:{event}'
                )
```

Because `ratio` returns `1.0` instead of raising, the `except` never sees the cell miss, and no
`no_prior_sample` entry is produced. (The non-SLC `TendencySampler.sample` at `team_tendency.py:136-147` uses
the same `ratio`, so `--team-tendency` runs are affected the same way.)

This layer is on in the shipped full-stack runs: `slc_config.py:9-10` sets `playcall_team_outcomes: True` for
`V1_OPTIONS`/`v1_full_stack`, and the Sunday smoke seeds ran `--slc-profile v1_full_stack`. The 19-24 fallback
kinds recorded per smoke seed contain no team-tendency entry, so this fallback fired, or did not, invisibly.

Output affected: which historical outcome type is drawn, i.e. reported team/player stats and scores, and it
is not measurable from any artifact. (Counts cannot be measured here: the dev database is not in the
workspace.)

Fix: append a counted fallback event (the same `_current_team_outcome_fallbacks` mechanism) inside `ratio`
when the cell/event lookup misses, or return a sentinel the caller can count.

### F4 (MEDIUM) - a missing call-conditioned grouping cell silently falls back to the unconditioned transition

`scripts/nfl_sequence/participation_field.py:216-228`:

```python
    def _group_probs(self, team, cell, prev, call):
        if call is not None and self.conditions_on_call:
            if self.marginal_by_cell_call.get((cell, call)):
                ...
                return self._shrunk(marginal, league_counts, team_counts)
            self.status['call_cell_missing'] += 1
        marginal = self.marginal_by_cell.get(cell)
        if not marginal:
            return {}
        return self._shrunk(marginal, self.league_transitions.get((cell, prev), Counter()),
                            self.team_transitions.get((team, cell, prev), Counter()))
```

- **FROM** a grouping/lineup transition conditioned on the called play type (run vs dropback; the v4 table
  feature) **TO** the unconditioned transition, in any situation cell where the league has no call-conditioned
  sample. The layer still counts as applied.
- **Does the run record it?** Only in `Field.status`, and nothing serializes `Field.status`. `grep -n '\.status'`
  over `scripts/nfl_sequence/*.py` finds it only in `participation_field.py:194/223/250/265/299/362` and
  `test_participation_field.py:102/152`; the batch summary builds `lineup` from each decision's lineup record
  (`slc_engine.py:980-999`), not from `Field.status`, and only reports `short_snaps` and
  `cell_fallbacks` there. The sibling counter `status['cell_fallback']` (`:250`) *is* visible because the
  substituted cell is copied into the decision (`pre_event.py:442-443` -> `lineup_summary` `cell_fallbacks`);
  `call_cell_missing` has no such path.
- Output affected: grouping/personnel counters, which players are on the field (`on_field`), and therefore
  the reported player snaps and the participant allocation behind player stats. Severity MEDIUM because it
  hides behind a counter nobody reads (the task's MEDIUM definition).

Fix: surface `field.status` in the `lineup` summary (one key), or raise in `pre_event` when a call-conditioned
cell is missing, as the grouping-missing path already does at `pre_event.py:439-440`.

### F5 (MEDIUM) - a missing play-extras row becomes `timeout=0` and `out_of_bounds=0`

`scripts/nfl_sequence/e2_reference.py:293` (docstring `:268-269`):

```python
        t, t_team, oob = flags.get((g, int(p)), (0, '', 0))
```

```python
    From the rebuilt play_extras CSV: timeout called (and by which team) and out_of_bounds. A play with no entry in the
    CSV has timeout 0 and out_of_bounds 0.
```

- **FROM** "this play's timeout/out-of-bounds flags are unknown (no extras row)" **TO** "no timeout was taken,
  the runner stayed in bounds". The default is the optimistic event.
- Downstream: `game_state._apply_timeouts` (`:1007-1020`) charges no timeout for that play, and
  `_record_clock_transitions` (`:1036-1041`) omits the `team_timeout`/`runner_out_of_bounds` stoppage from
  `clock_transition.stoppages`, which is a reported per-play record (`state_before/after.home_timeouts`,
  `clock_transition`).
- **Does the run record it?** No. `pool_scope` (`e2_reference.py:790-797`) counts pool exclusions and overtime
  rows, but there is no count of plays whose extras row was missing. The fallback is disclosed only in this
  docstring; no artifact carries the count, so "the extras file is complete for the window" is assumed, not
  measured.

Output affected: per-play timeout counts and clock-stoppage annotation (not the sampled runoff, which comes
from the same source row). Severity MEDIUM: a missing source row produces a legal-looking, different event.

Fix: count `len(rows) - len(flags_matched)` into `pool_scope` (or refuse if any play in the E1 pool has no
extras row), which makes the assumption checkable.

### F6 (MEDIUM) - missing/not-loaded role yardage silently becomes the play's `yards_gained`

`scripts/nfl_sequence/game_stats.py:120-124`:

```python
def _player_yards(play, field, fallback):
    """Use the source's role-specific box-score field when supplied; otherwise retain transition yardage."""
    context = play.get('participants', {}).get('sampled_play_context') or {}
    value = context.get(field)
    return fallback if value is None else int(value)
```

Callers pass the play's transition yardage as `fallback` (`game_stats.py:45,54,56,154,172,179`).

- **FROM** the source's `passing_yards` / `receiving_yards` / `rushing_yards` **TO** the play's
  `yards_gained` whenever the role-specific field was not loaded or not copied onto the play.
- The role fields exist in the play context only when the player-outcomes layer loaded them:
  `e2_reference.py:275` (`player_yardage = ... if include_player_yardage else ''`),
  `e2_reference.py:300-301`, and `game_state.py:316-318` copies them only `if field in facts`. So in every
  run where `--playcall-player-outcomes` is off (the S0 control, the manual/custom configurations, any ablation
  that disables `player_conditioned_outcomes`), this fallback is taken on every player yard line.
- **Does the run record it?** No per-run count. The substitution is named only in the player-outcomes layer's
  own note (`slc_engine.py:445-450`), i.e. exactly in the configuration where it is not needed; in the
  flags-off path the box-score note (`game_stats.py:203-217`) does not mention it, and `player_outcomes.py:347`
  documents the fallback only for the layer that supplies the fields.

Output affected: reported per-player passing/rushing/receiving yards. Severity MEDIUM: the values are usually
equal for the retained plays (the SLC pool already excludes laterally inconsistent completions,
`slc_engine.py:503-540`), but the run cannot tell a reader that the source quantity was missing, and a stored
box score cannot be distinguished from one that used the role fields.

Fix: record the count in the stats block (e.g. `player_yardage_fallbacks`), the way `pool_scope` records the
lateral/completion filters.

### F7 (LOW) - unparsable stored v1 lock params silently revert to the configured sigma

`scripts/nfl_sequence/simulate_pregame_batch.py:264-267`, `:294`:

```python
            try:
                params = json.loads(params_json)
            except (TypeError, ValueError):
                params = {}
...
                'win_probability_sigma_points': params.get('sigma', V1_CONFIG['sigma']),
```

FROM the stored lock's fitted parameters TO `{}` and then to the hard-coded `V1_CONFIG` default
(`sigma = 13.295`, `fit_games = None`). These fields are written into `payload['baseline_v1']`, so a malformed
`params_json` produces a baseline block that claims the default sigma rather than the stored one. The projected
points/margin come from the DB row and are unaffected, and `status` stays `available`, so nothing flags the
substitution. No fix needed for the projected comparison; a one-line note or a status downgrade would close it.

### F8 (LOW) - a touchdown drive with no recorded scorer silently credits the offense

`scripts/nfl_sequence/game_stats.py:91-92`:

```python
        if d['terminal'] == 'touchdown':
            scorer = d.get('touchdown_scored_by') or d['offense_team']
```

FROM "the record does not say who scored" TO "the offense scored", which then increments `touchdowns` /
`offensive_touchdowns` for that team. The current engine always sets `touchdown_scored_by` on a scored drive
(`game_state.py:1551-1552`, `:1418-1419`), so this is a latent fallback rather than an observed defect; there is
no guard that raises if the field is absent.

### F9 (LOW) - an unparsable QB depth rank quietly drops that QB from QB1 selection

`scripts/nfl_sequence/slc_outputs.py:45-48`:

```python
        try:
            rank = int(player.get('pos_rank'))
        except (TypeError, ValueError):
            continue
```

A QB whose `pos_rank` cannot be parsed is skipped; if that leaves the team without a QB the function returns
`None`, and every QB line is written with `starter: null`, `starter_basis: 'unknown'` (`:67-69`) instead of the
run refusing an incomplete depth chart. `pregame_snapshot.apply_full_depth_roster_snapshot` validates the rank
(`pregame_snapshot.py:197`), but a plain built snapshot does not go through that path.

### F10 (LOW) - a missing point-split/streak bucket silently applies a zero shift

`scripts/nfl_sequence/point_splits.py:60-64`:

```python
def shift_for(table, team_index, bucket):
    """The log-odds shift for one team in one score bucket; zero when the team is unknown."""
    if team_index is None:
        return 0.0
    return table['shift'].get((int(team_index), int(bucket)), 0.0)
```

and the same pattern in `scripts/nfl_sequence/streak_splits.py:95-98`. FROM the fitted team-by-bucket deviation
TO no effect. Unlike the whole-team failure in F3 these do not raise and are not counted as fallbacks; the
aggregate summary has `point_splits_evaluated`/`point_splits_nonzero` and the streak equivalents
(`slc_engine.py:961-968`), so a *missing bucket* is only visible as evaluated-minus-nonzero, not as an unknown.
Severity LOW because zero is the documented neutral shift for an unknown team and the layer is a research
ablation.

### F11 (LOW) - a missing prior-season streak state silently becomes the `NONE` bucket

`scripts/nfl_sequence/streak_splits.py:142-146`:

```python
def attach(rows, games):
    """Set row['streak'] to the offense's streak bucket going into the game (NONE when unknown) on each pool row."""
    for row in rows:
        row['streak'] = games.get(str(row['game_id']), {}).get(row.get('posteam'), 'NONE')
    return rows
```

`games` is built only from completed prior-season games (`slc_engine.py:548-564` selects
`home_score IS NOT NULL`), so a pool play from a game absent from that set is labelled `NONE` - a legitimate
"no streak" bucket that the outcome-lift table then uses (`slc_playcall.py:275`, `:518-519`) - rather than
being left unknown or excluded. The run does not count how many pool rows were labelled this way.

### F12 (LOW) - a malformed clock contributes zero possession seconds without clearing `complete`

`scripts/nfl_sequence/slc_outputs.py:169-190` and `:328`:

```python
def _period_time(quarter, clock):
    """Return elapsed game seconds for a quarter/clock pair when both are known."""
    try:
        return (int(quarter) - 1) * 900 + (900 - int(clock))
    except (TypeError, ValueError):
        return None
...
    if start is None or end is None or end < start:
        return 0
...
            line['possession_seconds'] = line.get('possession_seconds', 0) + sum(
                _play_period_seconds(play, label) for play in period_plays)
```

Every other conversion failure in this module sets the quarterly record's `complete = False`
(`slc_outputs.py:132-134`, `:246-250`, `:260-264`); this one adds `0` to a reported field
(`team_stats[team][period]['possession_seconds']`, also aggregated into the box-score distributions) and leaves
`quarter_by_quarter.complete` untouched. Also `end_period = _period_label(drive.get('end_quarter',
last_state.get('quarter')))` (`:243`) returns `None` for an unparsable value without flagging, and that drive
then contributes no `drives_ended` count (`:280-281`). Reachable only for records with malformed clock/drive
fields (a valid game is validated by `game_state.validate_game`); severity LOW.

### F13 (LOW) - pool rows are dropped without a counter at one branch of both pool builders

`scripts/nfl_sequence/e1_drive.py:176-177` (and `:210-211` in `build_pools`):

```python
            if row['play_type'] not in PLAY_TYPES or row['down'] is None or not 1 <= row['down'] <= 4:
                continue
```

Every other exclusion in `build_pool` goes through `classify()` and increments the published
`excluded` Counter, which ends up in `outcome_pool.excluded_from_pool` / `pool_scope`. Non-scrimmage
`play_type` rows and rows without a down are dropped here without a count, so the exclusion census under-reports
why a row is absent from the pool. No reported forecast number depends on it; severity LOW (provenance census,
not output).

## What the run does with fallbacks: counter inventory

| Counter (producer) | Where it lands | Reader-facing? |
|---|---|---|
| `fallback_events` per seed (`slc_engine.py:868-970`, from all layers) | `outcome.playcall.fallback_events` in `<out>.seeds.jsonl`; aggregated to `execution_verification.fallback_events` (`simulate_pregame_batch.py:692-693`, `:717`) | **No.** Not printed; not in `smoke-table.csv`; not read by `render_slc_run_report.py` |
| `layer_execution` per layer (`slc_engine.py:936-969`) | per-seed summary; aggregated to `execution_verification.layers` + `fallback_events` | **No.** |
| `blocker_resolution.counts_by_level` / `runtime_metrics` / `fallback_usage_by_team_situation` (`slc_engine.py:1002-1073`) | `execution_verification.blocker_resolution` (`simulate_pregame_batch.py:722-765`) | **No.** |
| `Field.status` (participation field: `call_cell_missing`, `cell_fallback`, `no_league_cell`, `unsupported_grouping`, `short`) | only in-process; `lineup_summary` (`slc_engine.py:980-999`) re-derives `short_snaps`/`cell_fallbacks` from decisions | **No.** (`call_cell_missing` therefore disappears) |
| `_TimeoutSamplingGuard.describe()` (`game_state.py:677-679`) | `drive['timeout_sampling_guard']` when anything was excluded | only inside the raw record, not summarized |
| `pool_scope` filters (`slc_engine.py:181-185`, `e2_reference.py:790-797`) | batch payload `pregame_snapshot.model_reference.pool_scope` | **Yes** (in the JSON) |
| `execution_verification` aggregate block (`simulate_pregame_batch.py:661-766`, assigned `:1147`) | batch JSON only | **Yes**, if the reader opens the JSON; absent from the committed smoke bundle |

## Appendix A - pattern hits inspected and judged guarded (not findings)

`except` sites in scope (19 total; no bare `except:` and no `assert` statements at all in the scoped files):

| Site | Construct | Why it is not a silent failure |
|---|---|---|
| `e1_drive.py:368` | `except (AssertionError, ValueError)` around `reducer.apply_play` | Re-raised as `FootballAssertionError` with the play/decision context, `from invalid` (cause retained) |
| `game_state.py:595` | `_TimeoutSamplingGuard._facts` returns `{}` on unparsable key | Latent default, but the pool and the participant table come from the same SQL window (`e1_drive.py:87-89` vs `e2_reference.py:262-303,766-768`), so a miss is a construction bug; a malformed key would fail earlier. Would matter if the windows ever diverge. |
| `game_state.py:1279` | `except (ValueError, TypeError, KeyError)` in blocked-kick projection | Row kept as unresolved, reason recorded on the outcome, game blocks |
| `game_state.py:2085` | `except Exception` in `validate_game` | Re-raised as `FootballAssertionError` with evidence context, `from exc` (cause retained); `football_assertions.classify_failure` may default an untyped error to `ILLEGAL_STATE` but the context is preserved |
| `participation_field.py:114` | `readable()` catches and returns `False` | `unsupported_grouping` is then raised by `pre_event.py:439-440`; test-covered |
| `pregame_snapshot.py:39`, `:89` | parse/read failures | Re-raised as `ValueError` `from exc` |
| `simulate_pregame_batch.py:266` | malformed lock params | Finding F7 (metadata only) |
| `simulate_pregame_batch.py:494` | per-seed catch-all | Designed boundary: the seed gets an `error` row, `--max-simulation-errors` defaults to 0 (stop at the first), and the failure envelope is attached (`:503-509`) |
| `simulate_pregame_batch.py:529` | box-score build failure | Seed becomes `validation_error`, `boxscore_error` and `assertion_failure` retained (`:538-562`) |
| `simulate_pregame_batch.py:948` | v1 baseline failure | `baseline.status='unavailable'` with the reason; the statistical batch is retained deliberately |
| `slc_playcall.py:236` | `except (TypeError, ValueError): pass` around `np.isnan` | Only protects the NaN type coercion; the value is then compared to 0 |
| `slc_outputs.py:47` | QB rank parse | Finding F9 (starter metadata only) |
| `slc_outputs.py:132`, `:248`, `:262` | conversion failures | Set the quarterly record's `complete=False` |
| `slc_outputs.py:162`, `:173`, `:184` | period/time conversion | Finding F12; the `:162` call sites at `:144/:232/:253` do set `complete=False`, only `:243` does not |
| `game_state.py:1809`, `:1836`, `:1926` | skip clock/transition checks | Only when `record['valid_full_game']` is already False; documented compatibility with pre-annotation research records |
| `slc_outputs.py:29-30` | `_int_or_zero` | Zero-fills the *published* team line, where a missing key really means "no such event"; the `record=None` error box score is marked `error` and carries `boxscore_error` (`simulate_pregame_batch.py:556-562`) |
| `game_stats.py:42`, `:149` | `out['yards_gained'] or 0` | Scrimmage-yard ints are enforced by `e1_drive.check_drive:517-525`; `None` is not reachable for a credited scrimmage play |
| `game_stats.py:132` | `part.get('attribution', ATTRIBUTION)` | Default label only; mixed labels raise at `:134-136` and `:198-199` |
| `game_state.py:1520-1526` | distance-unaware FG redraw when `field_goal_result` absent | `special_teams` is supplied whenever the kick tables exist (`game_state.py:1440-1441`) and always fills `field_goal_result`; legacy compatibility branch |
| `decision_layer.py:221-232` | uniform prior if the league cell is empty | Unreachable through `draw()`, which skips categories with no league cell (`:251-252`) |
| `formation_layer.py:106-109` | team with no history in the situation -> league cell | Documented in the docstring and `choose()` renormalises; a model default, not a data gap |
| `formation_layer.py:26-36`, `defense_layer.py:57`, `:90` | unmatched participation -> `UNKNOWN` | The label is stored per play; `UNKNOWN` is never chosen as a decision and is renormalised away |
| `slc_playcall.py:752-763` | `_label_lift` returns 1.0 with no labelled rows | Documented in the docstring ("has no lift (1.0)"); labelled rows are the charted subset |
| `slc_outputs.py:587-598` | player-stats-exceed-snaps check only when a realism block exists | Only reachable with `--export-plays`; the check is opt-in with the export, not silently wrong |
| `simulate_pregame_batch.py:679-682`, `:696-697` | raise for layers with no counter / disabled layers reporting applications | Fail loud |
| `simulate_pregame_batch.py:574-575` | refuses to overwrite an existing ledger without `--resume` | Fail loud |
| `team_tendency.py:40-42` | whole-team tendency missing raises | The `except ValueError` at the call site records it (`slc_playcall.py:780-786`) |
| `slc_playcall.py:530-534` and `:472-476` | all conditioned outcome weights zero | Falls back to the unmodified baseline weights **and** sets `outcome_weight_fallback` on the decision, which reaches `fallback_events` |
| `game_state.py:1621-1622` | missing `evaluation.verified` -> `valid_full_game=False` | Conservative direction; also blocks the claim |
| `slc_outputs.py:328` (`_play_period_seconds`) | cross-period play contributes only to its starting period | Definitional limitation of the period split, not a missing-input default; the zero-value case is F12 |

No scoped file uses `assert` for control flow (repo-wide grep finds only `compare_safety_arm.py:19` and
`evaluate_try_policy.py:175`, both outside the execution path), and no scoped file emits `warnings.warn`; the
only progress/validation prints are stderr progress lines in `simulate_pregame_batch.py:1058` and the partial
ledger-line message at `:592`.

## Appendix B - what a reader can see, by artifact

| Artifact | Shows fallback/level counts? |
|---|---|
| batch JSON (`--out`) | **Yes**: `execution_verification.fallback_events`, `blocker_resolution.counts_by_level/runtime_metrics/fallback_usage_by_team_situation`; `pregame_snapshot.model_reference.pool_scope` for filter counts |
| `<out>.seeds.jsonl` | **Yes, per seed**: `outcome.playcall.fallback_events`, `layer_execution`, `blocker_resolution`, `research_integration` |
| console summary | **No** (`simulate_pregame_batch.py:1189-1191` prints valid/tie/blocked counts only) |
| `<out>.boxscores.jsonl` + `aggregate_boxscores` | **No** fallback field; the box score carries `reconciliation` only |
| `smoke-table.csv` (bundle) | **No**; 18 columns, none about fallbacks |
| `render_slc_run_report.py` rendered report | **No**; the script never reads `execution_verification` or `fallback_events` |

## Evidence commands (repeatable)

```
# 13/13 smoke snapshots lack roster_eligible; 497/497 box-score player rows report true
python - <<'PY'
import json, collections
from pathlib import Path
snaps = sorted(Path('docs/research/slc-sunday-smoke-2026-11-08/snapshots').glob('*.json'))
missing = total = 0
for p in snaps:
    s = json.loads(p.read_text())
    for side in ('home', 'away'):
        for pl in s['rosters'][side]['players']:
            total += 1; missing += 'roster_eligible' not in pl
print(len(snaps), total, missing)
cnt = collections.Counter(); n = 0
for p in Path('docs/research/slc-sunday-smoke-2026-11-08/smoke-runs').glob('*.boxscores.jsonl'):
    for line in p.read_text().splitlines()[1:]:
        for pl in json.loads(line)['players']:
            cnt[str(pl.get('roster_eligible'))] += 1; n += 1
print(n, dict(cnt))
PY

# 13/13 valid seeds carry 368-602 recorded fallback events each, 19-24 kinds
python - <<'PY'
import json
from pathlib import Path
for p in sorted(Path('docs/research/slc-sunday-smoke-2026-11-08/smoke-runs').glob('*.seeds.jsonl')):
    for r in map(json.loads, p.read_text().splitlines()[1:]):
        o = r['outcome']; fb = (o.get('playcall') or {}).get('fallback_events') or {}
        print(p.name, o['valid_full_game'], sum(fb.values()), len(fb))
PY
```

## Limitations

- No dev database in this workspace: F3/F4/F5/F6 frequencies (how often the fallback fires in a real game) could
  not be measured, only the code path and the absence of a record. Frequencies stated in F2 come from committed
  artifacts only.
- This audit covers the 17 named files plus the call sites they lead to; it does not attempt a full-repo sweep.
  `slc_engine.py` and `pre_event.py` were read only where the scoped files call them.
- The Sunday smoke bundle was produced by a host tree whose four files are uncommitted (see
  `docs/research/slc-sunday-smoke-2026-11-08/manifest.json`); the findings above are stated against the local
  `d490757e6` files, which match the host for `game_legality.py` but not necessarily byte-for-byte elsewhere.
