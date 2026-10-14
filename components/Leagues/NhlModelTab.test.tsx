import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import NhlModelTab from './NhlModelTab'

const forecast = (pHome: number) => ({
  forecast_id: 'forecast-1', model_version: 'nhl-prospective-2026-27-v1',
  forecasted_at_utc: '2026-10-14T08:06:15Z', previewed_at_utc: '2026-10-14T13:42:00Z', preview: true,
  home_expected_goals: 3.1, away_expected_goals: 2.7, projected_total_goals: 5.8,
  projected_goal_differential_home: 0.4, home_win_probability: pHome, 'p_over_5.5': 0.5, 'p_over_6.5': 0.3,
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
    expect(screen.queryByText('LOCKED')).toBeNull()
    expect(screen.getByTitle('Models lock 90 mins before kickoff')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Record' }))
    expect(screen.getByText('No graded NHL projections yet.')).toBeTruthy()
  })

  it('shows a locked projection with the LOCKED chip and the Vegas and Model line labels', async () => {
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
    expect(screen.getByText('LOCKED')).toBeTruthy()
    expect(screen.getByText('Vegas line')).toBeTruthy()
    expect(screen.getByText('Vegas total')).toBeTruthy()
  })

  it('shows the Bovada puck line and total in the Vegas columns', async () => {
    const withLines = { ...payload, standings: { WSH: { games_played: 6, wins: 3, losses: 3, overtime_losses: 0, points: 6, standings_date: '2026-10-13' }, MTL: { games_played: 6, wins: 3, losses: 2, overtime_losses: 1, points: 7, standings_date: '2026-10-13' } }, lines: { '2026020106': { home_team: 'WSH', away_team: 'MTL', captured_at_utc: '2026-10-14T14:54:42Z', home_puck_line: -1.5, total_line: 6.5, home_moneyline: -128, away_moneyline: 107, over_price: -115, under_price: -105 } } }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(withLines) }))
    render(<NhlModelTab />)
    await waitFor(() => expect(screen.getByText('MTL @ WSH')).toBeTruthy())
    expect(screen.getByText('3-2-1 · 7 pts')).toBeTruthy()
    expect(screen.getByText('3-3-0 · 6 pts')).toBeTruthy()
    expect(screen.getByText('WSH -1.5')).toBeTruthy()
    expect(screen.getByText('WSH -0.4')).toBeTruthy()
    expect(screen.getByText('+1.1 pts')).toBeTruthy()
    expect(screen.getByText('6.5')).toBeTruthy()
    expect(screen.getByText('-0.7 pts')).toBeTruthy()
    expect(screen.getByText('Under 6.5')).toBeTruthy()
    expect(screen.getByText('+21.1% edge')).toBeTruthy()
  })
})
