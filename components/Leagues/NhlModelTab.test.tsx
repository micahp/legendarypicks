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

const previewPick = {
  market: 'total' as const, side: 'over' as const, line: 5.5, price: null,
  model_probability: .5, market_probability: null, edge: null, expected_value: null,
  line_source: null, line_captured_at_utc: null, settlement_basis: 'official_final_score',
  rule_version: 'leeway-2', provenance: 'preview' as const, result: null,
}

const preview = {
  game_id: 2026020106, game_date: '2026-10-14', scheduled_start_utc: '2026-10-14T23:30:00Z',
  home_team: 'WSH', away_team: 'MTL',
  models: {
    B3_elo: { ...forecast(0.55), pick: previewPick, pick_status: 'selected' as const },
    B5_xg_poisson: { ...forecast(0.52), pick: previewPick, pick_status: 'selected' as const },
    B7_elo_xg_poisson: { ...forecast(0.535), pick: previewPick, pick_status: 'selected' as const },
  },
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
  it('shows previews without a status label and keeps them out of the record', async () => {
    render(<NhlModelTab />)
    await waitFor(() => expect(screen.getByText('MTL @ WSH')).toBeTruthy())
    expect(screen.queryByText(/preview|not locked|pending/i)).toBeNull()
    expect(screen.getByText('Model Pick')).toBeTruthy()
    expect(screen.getByTitle('Models lock 90 mins before kickoff')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Record' }))
    expect(screen.getByText('No locked NHL model picks yet.')).toBeTruthy()
  })

  it('keeps archived lines visible after the live market moves', async () => {
    const lockedAt = '2026-10-14T17:30:00Z'
    const locked = {
      game_id: 2026020107, game_date: '2026-10-14', scheduled_start_utc: '2026-10-14T19:00:00Z',
      forecasted_at_utc: '2026-10-14T08:06:15Z', locked_at_utc: lockedAt,
      home_team: 'COL', away_team: 'DAL',
      feature_snapshot: { elo_pre_game: { home: 1500, away: 1500 }, xg_features: {} },
      models: {
        B3_elo: { ...forecast(0.6), locked_at_utc: lockedAt, grade: null, pick: null,
          pick_status: 'missing', locked_quote: { home_team: 'COL', away_team: 'DAL', captured_at_utc: lockedAt,
            home_puck_line: -1.5, total_line: 6.5, home_moneyline: -120, away_moneyline: 100,
            over_price: -110, under_price: -110, home_puck_price: -110, away_puck_price: -110 } },
        B5_xg_poisson: { ...forecast(0.5), locked_at_utc: lockedAt, grade: null },
        B7_elo_xg_poisson: { ...forecast(0.45), locked_at_utc: lockedAt, grade: null,
          locked_quote: { home_team: 'COL', away_team: 'DAL', captured_at_utc: lockedAt,
            home_puck_line: -1.5, total_line: 6.5, home_moneyline: -120, away_moneyline: 100,
            over_price: -110, under_price: -110, home_puck_price: -110, away_puck_price: -110 } },
      },
      result: null,
      markets: { source: 'Kalshi', usable: false, comparison_usable_at_lock: false, sides: [] },
    }
    const live = { home_team: 'COL', away_team: 'DAL', captured_at_utc: '2026-10-14T18:00:00Z',
      home_puck_line: 1.5, total_line: 7, home_moneyline: 110, away_moneyline: -130,
      over_price: -110, under_price: -110, home_puck_price: -110, away_puck_price: -110 }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ ...payload, games: [locked], previews: [], lines: { '2026020107': live } }) }))
    render(<NhlModelTab />)
    await waitFor(() => expect(screen.getByText('DAL @ COL')).toBeTruthy())
    expect(screen.getByText('Pick-time puck line')).toBeTruthy()
    expect(screen.getByText('Pick-time total')).toBeTruthy()
    expect(screen.getByText('COL -1.5')).toBeTruthy()
    expect(screen.getByText('6.5')).toBeTruthy()
    expect(screen.getByText(/Market has moved since this pick was frozen/)).toBeTruthy()
    expect(screen.getByText(/uses the pick-time line/)).toBeTruthy()
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
    expect(screen.getByText('Over 5.5')).toBeTruthy()
  })

  it('renders the frozen pick and probability without betting diagnostics', async () => {
    const frozen = {
      market: 'spread', side: 'away', line: 1.5, price: -240, model_probability: 0.74,
      market_probability: 0.679, edge: 0.0608, expected_value: 0.048, line_source: 'bovada',
      line_captured_at_utc: '2026-10-14T14:54:42Z', settlement_basis: 'official_final_score',
      provenance: 'lock', rule_version: 'goal-diff-1', result: null,
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
    expect(screen.getByText('74% model probability')).toBeTruthy()
    expect(screen.getAllByText('Model Pick').length).toBeGreaterThan(0)
    expect(screen.queryByText(/probability edge|estimated EV/i)).toBeNull()
    // The market columns are the frozen basis, not the live line.
    expect(screen.getByText('Pick-time puck line')).toBeTruthy()
    expect(screen.getByText('Pick-time total')).toBeTruthy()
  })

  it('renders a negative-EV selection as a Model Pick', async () => {
    const pick = {
      market: 'ml', side: 'home', line: null, price: -110, model_probability: 0.5,
      market_probability: 0.52, edge: -0.02, expected_value: -0.045, line_source: 'bovada',
      line_captured_at_utc: '2026-10-14T14:54:42Z', settlement_basis: 'official_final_score',
      provenance: 'lock', rule_version: 'leeway-2', result: null,
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
        B3_elo: { ...forecast(0.6), grade: null, pick },
        B5_xg_poisson: { ...forecast(0.5), grade: null, pick },
        B7_elo_xg_poisson: { ...forecast(0.45), grade: null, pick },
      },
      result: null,
      markets: { source: 'Kalshi', usable: false, sides: [] },
    }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ ...payload, games: [locked], previews: [] }) }))
    render(<NhlModelTab />)
    await waitFor(() => expect(screen.getByText('MTL @ WSH')).toBeTruthy())
    expect(screen.getByText('WSH ML')).toBeTruthy()
    expect(screen.getByText('50% model probability')).toBeTruthy()
    expect(screen.getAllByText('Model Pick').length).toBeGreaterThan(0)
    expect(screen.queryByText(/lean|qualifying wager|estimated EV/i)).toBeNull()
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
      settlement_basis: 'official_final_score', provenance: 'preview',
      rule_version: 'goal-diff-1', push_probability: .15,
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
    expect(screen.queryByText('Pick-time puck line')).toBeNull()
    expect(screen.queryByText('Pick-time total')).toBeNull()
  })

  it('keeps a stale-quote selection visible without wager qualification messaging', async () => {
    const stale = {
      market: 'total', side: 'under', line: 6.5, price: -110,
      model_probability: .66, push_probability: 0, market_probability: .5,
      edge: .16, expected_value: .20,
      line_source: 'bovada', line_captured_at_utc: '2026-10-14T16:00:00Z',
      settlement_basis: 'official_final_score', provenance: 'lock',
      quote_fresh: false, quote_age_seconds: 5400,
      rule_version: 'goal-diff-1', result: null,
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
    expect(screen.getByText('Model Pick')).toBeTruthy()
    expect(screen.getByText('Under 6.5')).toBeTruthy()
    expect(screen.getByText('66% model probability')).toBeTruthy()
    expect(screen.queryByText(/stale|qualif|estimated EV|lean/i)).toBeNull()
  })

  it('shows a selection with no posted price and no invented probability', async () => {
    const pick = {
      market: 'spread' as const, side: 'away' as const, line: 1.5, price: null,
      model_probability: null, market_probability: null, edge: null, expected_value: null,
      line_source: 'bovada', line_captured_at_utc: '2026-10-14T16:29:00Z',
      settlement_basis: 'official_final_score', provenance: 'lock' as const,
      rule_version: 'leeway-2', quote_fresh: false, result: null,
    }
    const locked = {
      game_id: 2026020112, game_date: '2026-10-14', scheduled_start_utc: '2026-10-14T19:00:00Z',
      forecasted_at_utc: '2026-10-14T08:06:15Z', locked_at_utc: '2026-10-14T17:30:00Z',
      home_team: 'WSH', away_team: 'MTL',
      feature_snapshot: { elo_pre_game: { home: 1500, away: 1500 }, xg_features: {} },
      models: {
        B3_elo: { ...forecast(.6), grade: null, pick },
        B5_xg_poisson: { ...forecast(.5), grade: null, pick },
        B7_elo_xg_poisson: { ...forecast(.45), grade: null, pick },
      },
      result: null, markets: { source: 'Kalshi', usable: false, sides: [] },
    }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({
      ok: true, json: () => Promise.resolve({ ...payload, games: [locked], previews: [] }),
    }))
    render(<NhlModelTab />)
    await screen.findByText('MTL @ WSH')
    expect(screen.getByText('Model Pick')).toBeTruthy()
    expect(screen.getByText('MTL +1.5')).toBeTruthy()
    expect(screen.queryByText(/0%|model probability|qualif|lean/i)).toBeNull()
  })

  it('shows the same frozen pick and pending grade in Projections and Record', async () => {
    const pick = {
      market: 'spread' as const, side: 'away' as const, line: 1.5,
      model_probability: .74, line_captured_at_utc: '2026-10-14T16:29:00Z',
      settlement_basis: 'official_final_score', rule_version: 'goal-diff-1',
      provenance: 'lock' as const, result: null,
    }
    const locked = {
      game_id: 2026020113, game_date: '2026-10-14', scheduled_start_utc: '2026-10-14T19:00:00Z',
      forecasted_at_utc: '2026-10-14T08:06:15Z', locked_at_utc: '2026-10-14T17:30:00Z',
      home_team: 'WSH', away_team: 'MTL',
      feature_snapshot: { elo_pre_game: { home: 1500, away: 1500 }, xg_features: {} },
      models: {
        B3_elo: { ...forecast(.6), grade: null, pick },
        B5_xg_poisson: { ...forecast(.5), grade: null, pick },
        B7_elo_xg_poisson: { ...forecast(.45), grade: null, pick },
      },
      result: null, markets: { source: 'Kalshi', usable: false, sides: [] },
    }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({
      ok: true, json: () => Promise.resolve({ ...payload, games: [locked], previews: [] }),
    }))
    render(<NhlModelTab />)
    await screen.findByText('MTL @ WSH')
    expect(screen.getByText('MTL +1.5')).toBeTruthy()
    expect(screen.getByText('74% model probability')).toBeTruthy()
    expect(screen.queryByText('Pending')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Record' }))
    expect(screen.getByText('MTL +1.5 74%')).toBeTruthy()
    expect(screen.getAllByText('Pending')).toHaveLength(2)
  })

  it('shows an explicit missing pick when the frozen forecast supports none', async () => {
    const locked = {
      game_id: 2026020110, game_date: '2026-10-14', scheduled_start_utc: '2026-10-14T19:00:00Z',
      forecasted_at_utc: '2026-10-14T08:06:15Z', locked_at_utc: '2026-10-14T17:30:00Z',
      home_team: 'WSH', away_team: 'MTL',
      feature_snapshot: { elo_pre_game: { home: 1500, away: 1500 }, xg_features: {} },
      models: {
        B3_elo: { ...forecast(0.6), projected_total_goals: null, home_expected_goals: null,
          away_expected_goals: null, grade: null, pick: null, pick_status: 'missing' },
        B5_xg_poisson: { ...forecast(0.5), projected_total_goals: null, home_expected_goals: null,
          away_expected_goals: null, grade: null, pick: null, pick_status: 'missing' },
        B7_elo_xg_poisson: { ...forecast(0.45), projected_total_goals: null, home_expected_goals: null,
          away_expected_goals: null, grade: null, pick: null, pick_status: 'missing' },
      },
      result: null,
      markets: { source: 'Kalshi', usable: false, sides: [] },
    }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ ...payload, games: [locked], previews: [] }) }))
    render(<NhlModelTab />)
    await waitFor(() => expect(screen.getByText('MTL @ WSH')).toBeTruthy())
    expect(screen.getByText('Model Pick')).toBeTruthy()
    expect(screen.getByText('Missing')).toBeTruthy()
    expect(screen.queryByText(/qualif|recommendation|lean/i)).toBeNull()
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
      provenance: 'lock', rule_version: 'goal-diff-1',
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
    // The Record shows the frozen total and server-computed settlement.
    fireEvent.click(await screen.findByRole('button', { name: 'Record' }))
    expect(screen.getByText('Over 5.5 53%')).toBeTruthy()
    expect(screen.getByText('Loss')).toBeTruthy()
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
      settlement_basis: 'official_final_score', provenance: 'lock', rule_version: 'goal-diff-1',
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
    expect(screen.getByText('Push')).toBeTruthy()
    expect(screen.queryByText('Loss')).toBeNull()
  })

  it('grades all frozen model picks and marks a missing frozen pick explicitly', async () => {
    const grade = {
      official_home_goals: 2, official_away_goals: 3,
      statistical_home_goals: 2, statistical_away_goals: 3,
      official_winner: 'away' as const, shootout_decided: false,
      home_win_brier: 0.25, home_win_logloss: 0.69,
      home_goal_error: 0, away_goal_error: 0,
      graded_at_utc: '2026-10-15T14:35:05Z',
    }
    const pick = (side: 'home' | 'away', won: boolean) => ({
      market: 'ml' as const, side, line: null, price: -110,
      model_probability: side === 'home' ? 0.52 : 0.48,
      market_probability: 0.5, edge: side === 'home' ? 0.02 : -0.02,
      expected_value: -0.05, line_source: 'bovada',
      line_captured_at_utc: '2026-10-14T17:20:00Z',
      settlement_basis: 'official_final_score',
      provenance: 'lock' as const, rule_version: 'goal-diff-1', result: { won },
    })
    const game = {
      game_id: 2026020199, game_date: '2026-10-14',
      scheduled_start_utc: '2026-10-14T19:00:00Z',
      forecasted_at_utc: '2026-10-14T17:24:00Z', locked_at_utc: '2026-10-14T17:30:00Z',
      home_team: 'WSH', away_team: 'MTL',
      feature_snapshot: { elo_pre_game: { home: 1500, away: 1500 }, xg_features: {} },
      models: {
        B3_elo: { ...forecast(0.52), grade, pick: pick('home', false) },
        B5_xg_poisson: { ...forecast(0.48), grade, pick: null },
        B7_elo_xg_poisson: { ...forecast(0.48), grade, pick: pick('away', true) },
      },
      result: grade, markets: { source: 'Kalshi', usable: false, sides: [] },
    }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({
      ok: true, json: () => Promise.resolve({ ...payload, games: [game], previews: [] }),
    }))
    render(<NhlModelTab />)
    fireEvent.click(await screen.findByRole('button', { name: 'Record' }))
    expect(screen.getByText('Win')).toBeTruthy()
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'B3_elo' } })
    expect(screen.getByText('Loss')).toBeTruthy()
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'B5_xg_poisson' } })
    expect(screen.getAllByText('Missing')).toHaveLength(2)
    expect(screen.queryByText(/lean|qualifying wager|no pick recorded/i)).toBeNull()
  })

  it('compares forecast accuracy across all three models in a tooltip, including missing picks', async () => {
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
    expect(screen.getAllByText('Missing')).toHaveLength(4)
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'B3_elo' } })
    expect(screen.getAllByText('0.2000').length).toBeGreaterThan(0)
    expect(screen.getByText('· Selected')).toBeTruthy()
  })

  it('shows all-market Brier for graded games without model picks', async () => {
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
    expect(screen.queryAllByText('0.16')).toHaveLength(0)
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
