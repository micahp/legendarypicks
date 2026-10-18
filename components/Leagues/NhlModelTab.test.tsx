import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import NhlModelTab from './NhlModelTab'

const forecast = (pHome: number) => ({
  forecast_id: 'forecast-1', model_version: 'nhl-prospective-2026-27-v1',
  forecasted_at_utc: '2026-10-14T08:06:15Z', previewed_at_utc: '2026-10-14T13:42:00Z', preview: true,
  home_expected_goals: 3.1, away_expected_goals: 2.7, projected_total_goals: 5.8,
  projected_goal_differential_home: 0.4, home_win_probability: pHome, 'p_over_5.5': 0.5, 'p_over_6.5': 0.3,
  p_home_minus_1_5: 0.26, p_home_plus_1_5: 0.8, p_away_minus_1_5: 0.2, p_away_plus_1_5: 0.74,
})

const preview = {
  game_id: 2026020106, game_date: '2026-10-14', scheduled_start_utc: '2026-10-14T23:30:00Z',
  home_team: 'WSH', away_team: 'MTL',
  models: { B3_elo: forecast(0.55), B5_xg_poisson: forecast(0.52), B7_elo_xg_poisson: forecast(0.535) },
}

const payload = {
  model_version: 'per-model-locked', model_versions: {}, default_model: 'B7_elo_xg_poisson',
  frozen_at_utc: null, source: 'test', state: 'awaiting_first_lock', games: [], missed_locks: [],
  previews: [preview],
}

beforeEach(() => {
  ;(global as any).fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(payload) }))
})

describe('NHL model tab previews', () => {
  it('shows unlocked projections without a LOCKED chip and keeps them out of the record', async () => {
    render(<NhlModelTab />)
    await waitFor(() => expect(screen.getByText('MTL @ WSH')).toBeTruthy())
    expect(screen.getByText('UNLOCKED')).toBeTruthy()
    expect(screen.queryByText('LOCKED')).toBeNull()
    expect(screen.getByTitle('Models lock 90 mins before kickoff')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Record' }))
    expect(screen.getByText('No graded NHL projections yet.')).toBeTruthy()
  })

  it('shows a locked projection without a status chip and with the Vegas and Model line labels', async () => {
    const lockedAt = '2026-10-14T17:30:00Z'
    const locked = {
      game_id: 2026020107, game_date: '2026-10-14', scheduled_start_utc: '2026-10-14T19:00:00Z',
      forecasted_at_utc: '2026-10-14T08:06:15Z', locked_at_utc: lockedAt,
      home_team: 'COL', away_team: 'DAL',
      feature_snapshot: { elo_pre_game: { home: 1500, away: 1500 }, xg_features: {} },
      models: {
        B3_elo: { ...forecast(0.6), locked_at_utc: lockedAt, grade: null },
        B5_xg_poisson: { ...forecast(0.5), locked_at_utc: lockedAt, grade: null },
        B7_elo_xg_poisson: { ...forecast(0.45), locked_at_utc: lockedAt, grade: null },
      },
      result: null,
      markets: { source: 'Kalshi', usable: false, comparison_usable_at_lock: false, sides: [] },
    }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ ...payload, games: [locked], previews: [] }) }))
    render(<NhlModelTab />)
    await waitFor(() => expect(screen.getByText('DAL @ COL')).toBeTruthy())
    expect(screen.queryByText('LOCKED')).toBeNull()
    expect(screen.getByText('Puck line')).toBeTruthy()
    expect(screen.getByText('Vegas total')).toBeTruthy()
  })

  it('shows the Bovada puck line and total in the Vegas columns', async () => {
    const withLines = { ...payload, standings: { WSH: { games_played: 6, wins: 3, losses: 3, overtime_losses: 0, points: 6, standings_date: '2026-10-13' }, MTL: { games_played: 6, wins: 3, losses: 2, overtime_losses: 1, points: 7, standings_date: '2026-10-13' } }, lines: { '2026020106': { home_team: 'WSH', away_team: 'MTL', captured_at_utc: '2026-10-14T14:54:42Z', home_puck_line: -1.5, home_puck_price: 200, away_puck_price: -240, total_line: 6.5, home_moneyline: -128, away_moneyline: 107, over_price: -115, under_price: -105 } } }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(withLines) }))
    render(<NhlModelTab />)
    await waitFor(() => expect(screen.getByText('MTL @ WSH')).toBeTruthy())
    expect(screen.getByText('3-2-1 · 7 pts')).toBeTruthy()
    expect(screen.getByText('3-3-0 · 6 pts')).toBeTruthy()
    expect(screen.getByText('WSH -1.5')).toBeTruthy()
    expect(screen.getByText('WSH -0.4')).toBeTruthy()
    expect(screen.getByText('1.1 goals (MTL)')).toBeTruthy()
    expect(screen.getByText('6.5')).toBeTruthy()
    expect(screen.getByText('-0.7 goals')).toBeTruthy()
    // No pick in the payload: the browser never invents one, so the card reads n/a.
    expect(screen.getByText('n/a')).toBeTruthy()
  })

  it('renders the frozen pick and its edge from the payload', async () => {
    const frozen = {
      market: 'spread', side: 'away', line: 1.5, price: -240, model_probability: 0.74,
      market_probability: 0.679, edge: 0.0608, expected_value: 0.048, line_source: 'bovada',
      line_captured_at_utc: '2026-10-14T14:54:42Z', settlement_basis: 'official_final_score',
      provenance: 'lock', priced: true, qualifies: true, rule_version: 'ev-max-1', result: null,
      quote: { home_team: 'WSH', away_team: 'MTL', captured_at_utc: '2026-10-14T14:54:42Z',
               home_puck_line: -1.5, total_line: 6.5, home_moneyline: -128, away_moneyline: 107,
               over_price: -115, under_price: -105, home_puck_price: 200, away_puck_price: -240 },
    }
    const locked = {
      game_id: 2026020107, game_date: '2026-10-14', scheduled_start_utc: '2026-10-14T19:00:00Z',
      forecasted_at_utc: '2026-10-14T08:06:15Z', locked_at_utc: '2026-10-14T17:30:00Z',
      home_team: 'WSH', away_team: 'MTL',
      feature_snapshot: { elo_pre_game: { home: 1500, away: 1500 }, xg_features: {} },
      models: {
        B3_elo: { ...forecast(0.6), grade: null, pick: frozen },
        B5_xg_poisson: { ...forecast(0.5), grade: null, pick: frozen },
        B7_elo_xg_poisson: { ...forecast(0.45), grade: null, pick: frozen },
      },
      result: null,
      markets: { source: 'Kalshi', usable: false, comparison_usable_at_lock: false, sides: [] },
    }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ ...payload, games: [locked], previews: [] }) }))
    render(<NhlModelTab />)
    await waitFor(() => expect(screen.getByText('MTL @ WSH')).toBeTruthy())
    expect(screen.getByText('MTL +1.5')).toBeTruthy()
    expect(screen.getByText('+6.1% probability edge')).toBeTruthy()
    expect(screen.getByText('+4.8% estimated EV')).toBeTruthy()
    // The market columns are the frozen basis, not the live line.
    expect(screen.getByText('Locked puck line')).toBeTruthy()
    expect(screen.getByText('Locked total')).toBeTruthy()
  })

  it('reports a negative-expected-value candidate as a lean with no qualifying bet', async () => {
    const lean = {
      market: 'ml', side: 'home', line: null, price: -110, model_probability: 0.5,
      market_probability: 0.52, edge: -0.02, expected_value: -0.045, line_source: 'bovada',
      line_captured_at_utc: '2026-10-14T14:54:42Z', settlement_basis: 'official_final_score',
      provenance: 'lock', priced: true, qualifies: false, rule_version: 'ev-max-1', result: null,
      quote: { home_team: 'WSH', away_team: 'MTL', captured_at_utc: '2026-10-14T14:54:42Z',
               home_puck_line: -1.5, total_line: 6.5, home_moneyline: -110, away_moneyline: -110,
               over_price: -110, under_price: -110, home_puck_price: -110, away_puck_price: -110 },
    }
    const locked = {
      game_id: 2026020109, game_date: '2026-10-14', scheduled_start_utc: '2026-10-14T19:00:00Z',
      forecasted_at_utc: '2026-10-14T08:06:15Z', locked_at_utc: '2026-10-14T17:30:00Z',
      home_team: 'WSH', away_team: 'MTL',
      feature_snapshot: { elo_pre_game: { home: 1500, away: 1500 }, xg_features: {} },
      models: {
        B3_elo: { ...forecast(0.6), grade: null, pick: lean },
        B5_xg_poisson: { ...forecast(0.5), grade: null, pick: lean },
        B7_elo_xg_poisson: { ...forecast(0.45), grade: null, pick: lean },
      },
      result: null,
      markets: { source: 'Kalshi', usable: false, sides: [] },
    }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ ...payload, games: [locked], previews: [] }) }))
    render(<NhlModelTab />)
    await waitFor(() => expect(screen.getByText('MTL @ WSH')).toBeTruthy())
    expect(screen.getByText('No positive estimated betting EV')).toBeTruthy()
    expect(screen.getByText('Model lean')).toBeTruthy()
    expect(screen.getByText('-4.5% estimated EV')).toBeTruthy()
  })

  it('calls an unlocked forecast quote a current line, not a locked line', async () => {
    const quote = {
      home_team: 'WSH', away_team: 'MTL', captured_at_utc: '2026-10-14T14:54:42Z',
      home_puck_line: -1.5, total_line: 6, home_moneyline: -128, away_moneyline: 107,
      over_price: -110, under_price: -110, home_puck_price: 200, away_puck_price: -240,
    }
    const previewPick = {
      market: 'total', side: 'under', line: 6, price: -110,
      model_probability: .54, market_probability: .5, edge: .04, expected_value: .03,
      line_source: 'bovada', line_captured_at_utc: quote.captured_at_utc,
      settlement_basis: 'official_final_score', provenance: 'preview', priced: true,
      qualifies: true, rule_version: 'ev-max-2-settlement', push_probability: .15,
      quote, result: null,
    }
    const value = {
      ...payload,
      previews: [{ ...preview, models: {
        B3_elo: { ...forecast(.55), pick: previewPick },
        B5_xg_poisson: { ...forecast(.52), pick: previewPick },
        B7_elo_xg_poisson: { ...forecast(.535), pick: previewPick },
      } }],
      lines: { '2026020106': quote },
    }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(value) }))
    render(<NhlModelTab />)
    await screen.findByText('MTL @ WSH')
    expect(screen.getByText('Puck line')).toBeTruthy()
    expect(screen.getByText('Vegas total')).toBeTruthy()
    expect(screen.queryByText('Locked puck line')).toBeNull()
    expect(screen.queryByText('Locked total')).toBeNull()
  })

  it('explains when an apparently positive EV comes from a stale frozen quote', async () => {
    const stale = {
      market: 'total', side: 'under', line: 6.5, price: -110,
      model_probability: .66, push_probability: 0, market_probability: .5,
      edge: .16, expected_value: .20,
      line_source: 'bovada', line_captured_at_utc: '2026-10-14T16:00:00Z',
      settlement_basis: 'official_final_score', provenance: 'lock',
      priced: true, quote_fresh: false, quote_age_seconds: 5400,
      qualifies: false, rule_version: 'ev-max-2-settlement', result: null,
    }
    const game = {
      game_id: 2026020111, game_date: '2026-10-14', scheduled_start_utc: '2026-10-14T19:00:00Z',
      forecasted_at_utc: '2026-10-14T08:06:15Z', locked_at_utc: '2026-10-14T17:30:00Z',
      home_team: 'WSH', away_team: 'MTL',
      feature_snapshot: { elo_pre_game: { home: 1500, away: 1500 }, xg_features: {} },
      models: {
        B3_elo: { ...forecast(.6), grade: null, pick: stale },
        B5_xg_poisson: { ...forecast(.5), grade: null, pick: stale },
        B7_elo_xg_poisson: { ...forecast(.45), grade: null, pick: stale },
      },
      result: null, markets: { source: 'Kalshi', usable: false, sides: [] },
    }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({
      ok: true, json: () => Promise.resolve({ ...payload, games: [game], previews: [] }),
    }))
    render(<NhlModelTab />)
    await screen.findByText('MTL @ WSH')
    expect(screen.getByText('Odds too old or unverified to qualify')).toBeTruthy()
    expect(screen.getByText('+20.0% estimated EV (unverified price)')).toBeTruthy()
    expect(screen.getByText('Model lean')).toBeTruthy()
  })

  it('says there is no priced recommendation when a locked game has no pick', async () => {
    const locked = {
      game_id: 2026020110, game_date: '2026-10-14', scheduled_start_utc: '2026-10-14T19:00:00Z',
      forecasted_at_utc: '2026-10-14T08:06:15Z', locked_at_utc: '2026-10-14T17:30:00Z',
      home_team: 'WSH', away_team: 'MTL',
      feature_snapshot: { elo_pre_game: { home: 1500, away: 1500 }, xg_features: {} },
      models: {
        B3_elo: { ...forecast(0.6), grade: null, pick: null },
        B5_xg_poisson: { ...forecast(0.5), grade: null, pick: null },
        B7_elo_xg_poisson: { ...forecast(0.45), grade: null, pick: null },
      },
      result: null,
      markets: { source: 'Kalshi', usable: false, sides: [] },
    }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ ...payload, games: [locked], previews: [] }) }))
    render(<NhlModelTab />)
    await waitFor(() => expect(screen.getByText('MTL @ WSH')).toBeTruthy())
    expect(screen.getByText('No priced recommendation yet')).toBeTruthy()
    expect(screen.queryByText('Model pick')).toBeNull()
  })

  it('grades the frozen pick in the record instead of a moneyline guess', async () => {
    const grade = {
      official_home_goals: 3, official_away_goals: 2, statistical_home_goals: 2, statistical_away_goals: 2,
      official_winner: 'home', shootout_decided: true, home_win_brier: 0.2, home_win_logloss: 0.5,
      home_goal_error: 1, away_goal_error: 0, graded_at_utc: '2026-10-15T14:35:05Z',
    }
    // The rule sent this game to the total. Home won on the moneyline the old record graded,
    // so a moneyline guess would read Pick ✓ while the frozen over 5.5 actually lost.
    const frozen = {
      market: 'total', side: 'over', line: 5.5, price: -115, model_probability: 0.53,
      market_probability: 0.52, edge: 0.01, expected_value: 0.02, line_source: 'bovada',
      line_captured_at_utc: '2026-10-14T17:00:00Z', settlement_basis: 'official_final_score',
      provenance: 'lock', priced: true, qualifies: true, rule_version: 'ev-max-1',
      result: { won: false },
    }
    const graded = {
      game_id: 2026020108, game_date: '2026-10-14', scheduled_start_utc: '2026-10-14T19:00:00Z',
      forecasted_at_utc: '2026-10-14T08:06:15Z', locked_at_utc: '2026-10-14T17:30:00Z',
      home_team: 'WSH', away_team: 'MTL',
      feature_snapshot: { elo_pre_game: { home: 1500, away: 1500 }, xg_features: {} },
      models: {
        B3_elo: { ...forecast(0.6), grade, pick: frozen },
        B5_xg_poisson: { ...forecast(0.5), grade, pick: frozen },
        B7_elo_xg_poisson: { ...forecast(0.45), grade, pick: frozen },
      },
      result: grade,
      markets: { source: 'Kalshi', usable: false, sides: [] },
    }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ ...payload, games: [graded], previews: [] }) }))
    render(<NhlModelTab />)
    // A graded game leaves the projections view; the record is where it is read.
    fireEvent.click(await screen.findByRole('button', { name: 'Record' }))
    expect(screen.getByText('Over 5.5 53%')).toBeTruthy()
    expect(screen.getByText('Pick ✗ Lost')).toBeTruthy()
  })
  it('reports a frozen integer-total push as a push rather than a loss', async () => {
    const grade = {
      official_home_goals: 4, official_away_goals: 2,
      statistical_home_goals: 4, statistical_away_goals: 2,
      official_winner: 'home' as const, shootout_decided: false,
      home_win_brier: .2, home_win_logloss: .5, home_goal_error: 0, away_goal_error: 0,
      graded_at_utc: '2026-10-15T14:35:05Z',
    }
    const pushPick = {
      market: 'total', side: 'under', line: 6, price: -110,
      model_probability: .46, push_probability: .14,
      market_probability: .5, edge: .02, expected_value: .09,
      line_source: 'bovada', line_captured_at_utc: '2026-10-14T17:28:00Z',
      settlement_basis: 'official_final_score', provenance: 'lock', priced: true,
      qualifies: true, rule_version: 'ev-max-2-settlement',
      result: { won: null, push: true, settlement: 'push' },
    }
    const game = {
      game_id: 2026020108, game_date: '2026-10-14',
      scheduled_start_utc: '2026-10-14T19:00:00Z',
      forecasted_at_utc: '2026-10-14T08:06:15Z',
      locked_at_utc: '2026-10-14T17:30:00Z',
      home_team: 'WSH', away_team: 'MTL',
      feature_snapshot: { elo_pre_game: { home: 1500, away: 1500 }, xg_features: {} },
      models: {
        B3_elo: { ...forecast(.6), grade, pick: pushPick },
        B5_xg_poisson: { ...forecast(.5), grade, pick: pushPick },
        B7_elo_xg_poisson: { ...forecast(.45), grade, pick: pushPick },
      },
      result: grade,
      markets: { source: 'Kalshi', usable: false, sides: [] },
    }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({
      ok: true, json: () => Promise.resolve({ ...payload, games: [game], previews: [] }),
    }))
    render(<NhlModelTab />)
    fireEvent.click(await screen.findByRole('button', { name: 'Record' }))
    expect(screen.getByText('Pick ↔ Push')).toBeTruthy()
    expect(screen.queryByText('Pick ✗ Lost')).toBeNull()
  })

  it('compares prospective Brier and goals accuracy across all three models in a tooltip, including unpriced games', async () => {
    const graded = (id: number, brier: number, logLoss: number, homeError: number, awayError: number) => {
      const grade = {
        official_home_goals: 3, official_away_goals: 2, statistical_home_goals: 3, statistical_away_goals: 2,
        official_winner: 'home' as const, shootout_decided: false,
        home_win_brier: brier, home_win_logloss: logLoss,
        home_goal_error: homeError, away_goal_error: awayError,
        graded_at_utc: '2026-10-15T14:35:05Z',
      }
      return {
        game_id: id, game_date: '2026-10-14', scheduled_start_utc: '2026-10-14T19:00:00Z',
        forecasted_at_utc: '2026-10-14T08:06:15Z', locked_at_utc: '2026-10-14T17:30:00Z',
        home_team: 'WSH', away_team: 'MTL',
        feature_snapshot: { elo_pre_game: { home: 1500, away: 1500 }, xg_features: {} },
        models: {
          B3_elo: { ...forecast(0.6), grade: { ...grade, home_win_brier: 0.2 } },
          B5_xg_poisson: { ...forecast(0.5), grade: { ...grade, home_win_brier: 0.25 } },
          B7_elo_xg_poisson: { ...forecast(0.55), grade, pick: null },
        },
        result: grade,
        markets: { source: 'Kalshi', usable: false, sides: [] },
      }
    }
    const games = [
      graded(2026020108, 0.04, 0.2, 1, -2),
      graded(2026020109, 0.16, 0.6, -3, 0),
    ]
    ;(global as any).fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ ...payload, games, previews: [] }) }))
    render(<NhlModelTab />)
    await screen.findByRole('button', { name: /Model accuracy/ })
    fireEvent.mouseEnter(screen.getByRole('button', { name: /Model accuracy/ }))
    expect(screen.getByRole('tooltip')).toBeTruthy()
    expect(screen.getByText('0.1000')).toBeTruthy()
    expect(screen.getByText('Game lines · Brier scores')).toBeTruthy()
    expect(screen.getByText('Home −1.5')).toBeTruthy()
    expect(screen.getByText('Over 5.5')).toBeTruthy()

    // The fixture varies only the Brier per model, so log loss and goal error are the same
    // for all three and each value appears once per model row. The assertion is that the
    // value is shown, not that it is unique.
    expect(screen.getAllByText('0.4000').length).toBeGreaterThan(0)
    expect(screen.getAllByText('1.500').length).toBeGreaterThan(0)
    expect(screen.getAllByText('2').length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('button', { name: 'Record' }))
    expect(screen.getByText('0.1000')).toBeTruthy()
    expect(screen.getAllByText('No pick recorded')).toHaveLength(2)
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'B3_elo' } })
    expect(screen.getAllByText('0.2000').length).toBeGreaterThan(0)
    expect(screen.getByText('· Selected')).toBeTruthy()
  })

  it('shows all-market Brier for graded unpriced games, including a frozen-line comparison', async () => {
    const grade = {
      official_home_goals: 4, official_away_goals: 3,
      statistical_home_goals: 3, statistical_away_goals: 3, official_winner: 'home' as const,
      shootout_decided: true, home_win_brier: 0.16, home_win_logloss: 0.51,
      home_goal_error: 0, away_goal_error: 0, graded_at_utc: '2026-10-15T14:35:05Z',
    }
    const graded = {
      game_id: 2026020108, game_date: '2026-10-14', scheduled_start_utc: '2026-10-14T19:00:00Z',
      forecasted_at_utc: '2026-10-14T08:06:15Z', locked_at_utc: '2026-10-14T17:30:00Z',
      home_team: 'WSH', away_team: 'MTL',
      feature_snapshot: { elo_pre_game: { home: 1500, away: 1500 }, xg_features: {} },
      models: {
        ...Object.fromEntries((['B3_elo','B5_xg_poisson','B7_elo_xg_poisson'] as const).map(key => [
          key, {
            ...forecast(0.6), grade, pick: null,
            line_grades: {
              version: 'line-brier-v1',
              reference: {
                home_minus_1_5: { probability: .3, outcome: 0, brier: .09 },
                away_minus_1_5: { probability: .2, outcome: 0, brier: .04 },
                over_5_5: { probability: .6, outcome: 1, brier: .16 },
                over_6_5: { probability: .4, outcome: 0, brier: .16 },
              },
              locked_market: { total_over: { line: 6.5, probability: .65, outcome: 1, brier: .1225,
                ...(key === 'B5_xg_poisson' ? {} : { market_brier: .2 }) } },
            },
          },
        ])),
      },
      result: grade, markets: { source: 'Kalshi', usable: false, sides: [] },
    }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ ...payload, games: [graded], previews: [] }) }))
    render(<NhlModelTab />)
    fireEvent.mouseEnter(await screen.findByRole('button', { name: 'Model accuracy' }))
    expect(screen.getByText('Game lines · Brier scores')).toBeTruthy()
    expect(screen.getByText('Home −1.5')).toBeTruthy()
    expect(screen.getByText('Over 6.5')).toBeTruthy()
    expect(screen.getAllByText('0.0900').length).toBe(3)
    // A model score without its matched market score must not inflate the displayed sample.
    expect(screen.getAllByText('0.1225').length).toBe(2)
    expect(screen.getAllByText('0.2000').length).toBe(2)
    expect(screen.getAllByText('0.16').length).toBe(0)
  })

  it('does not invent Brier scores before games are graded', async () => {
    render(<NhlModelTab />)
    await screen.findByRole('button', { name: /Model accuracy/ })
    expect(screen.queryByRole('tooltip')).toBeNull()
    fireEvent.mouseEnter(screen.getByRole('button', { name: /Model accuracy/ }))
    expect(screen.getByRole('tooltip')).toBeTruthy()
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(9)
    expect(screen.getAllByText('0').length).toBeGreaterThan(0)
  })

  it('opens on hover and keyboard focus and closes when hover ends', async () => {
    render(<NhlModelTab />)
    const button = await screen.findByRole('button', { name: 'Model accuracy' })
    expect(screen.queryByRole('tooltip')).toBeNull()
    fireEvent.mouseEnter(button)
    expect(screen.getByRole('tooltip')).toBeTruthy()
    fireEvent.mouseLeave(button)
    expect(screen.queryByRole('tooltip')).toBeNull()
    fireEvent.focus(button)
    expect(screen.getByRole('tooltip')).toBeTruthy()
    fireEvent.blur(button, { relatedTarget: null })
    expect(screen.queryByRole('tooltip')).toBeNull()
  })

  it('pins the tooltip on tap and dismisses on Escape or outside click', async () => {
    render(<NhlModelTab />)
    const button = await screen.findByRole('button', { name: 'Model accuracy' })
    fireEvent.click(button)
    expect(screen.getByRole('tooltip')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Close model accuracy tooltip' }))
    expect(screen.queryByRole('tooltip')).toBeNull()
    fireEvent.click(button)
    expect(screen.getByRole('tooltip')).toBeTruthy()
    fireEvent.keyDown(button, { key: 'Escape' })
    expect(screen.queryByRole('tooltip')).toBeNull()
  })

})
