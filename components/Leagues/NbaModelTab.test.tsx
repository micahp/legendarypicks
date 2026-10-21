import React from 'react'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import NbaModelTab from './NbaModelTab'

const models = [
  { id: 'G1', label: 'G1 Elo', version: 'g1-version', projects_scores: false, note: 'Elo model' },
  { id: 'G2', label: 'G2 Efficiency', version: 'g2-version', projects_scores: true, note: 'Efficiency model' },
  { id: 'G3', label: 'G3 Joint scores', version: 'g3-version', projects_scores: true, note: 'Joint score model' },
]
const payload = {
  state: 'available', default_model: 'G3', models,
  records: {
    G1: { locked: 0, graded: 0, awaiting: 0, missed: 0, winner_brier: null, winner_log_loss: null },
    G2: { locked: 0, graded: 0, awaiting: 0, missed: 0, winner_brier: null, winner_log_loss: null },
    G3: { locked: 0, graded: 0, awaiting: 0, missed: 0, winner_brier: null, winner_log_loss: null },
  },
  games: [{
    game_id: '0022600001', scheduled_start_utc: new Date(Date.now() + 86_400_000).toISOString(),
    home_team: 'DET', away_team: 'BOS', status: 'preview', locked_at_utc: null, result: null,
    models: {
      G1: { model_version: 'g1-version', home_win_probability: 0.55, projected_home_points: null, projected_away_points: null, score_forecast_available: false },
      G2: { model_version: 'g2-version', home_win_probability: 0.57, projected_home_points: 111.2, projected_away_points: 108.4, score_forecast_available: true },
      G3: { model_version: 'g3-version', home_win_probability: 0.58, projected_home_points: 112.1, projected_away_points: 108.9, score_forecast_available: true },
    },
  }],
  benchmark: {
    eligible_games: { train: 5800, validation: 2460, test: 2460 },
    metrics: {
      validation: { G1: { games: 2460, winner_brier: 0.22, winner_log_loss: 0.64, winner_accuracy: 0.64, calibration: { ece_10_bin: 0.03 } } },
      test: {
        G1: { games: 2460, winner_brier: 0.21, winner_log_loss: 0.61, winner_accuracy: 0.65, calibration: { ece_10_bin: 0.04 } },
        G2: { games: 2460, winner_brier: 0.21, winner_log_loss: 0.62, winner_accuracy: 0.65, calibration: { ece_10_bin: 0.05 }, team_points_mae: 9.7, spread_mae: 11.2, total_mae: 15.8 },
        G3: { games: 2460, winner_brier: 0.21, winner_log_loss: 0.61, winner_accuracy: 0.65, calibration: { ece_10_bin: 0.03 }, team_points_mae: 9.7, spread_mae: 11.2, total_mae: 15.8 },
      },
    },
  },
}

beforeEach(() => {
  ;(global as any).fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(payload) }))
})

afterEach(cleanup)

describe('NBA model tab', () => {
  it('compares candidates and explicitly says G1 has no score projection', async () => {
    render(<NbaModelTab />)
    await waitFor(() => expect(screen.getAllByText('G1 Elo').length).toBeGreaterThan(0))
    expect(screen.getByText(/No score projection/)).toBeTruthy()
    expect(screen.getByText('Home win 58.0%')).toBeTruthy()
    expect(screen.getByText(/untouched test 2,460 games/)).toBeTruthy()
  })

  it('labels preview forecasts as not locked', async () => {
    render(<NbaModelTab />)
    await waitFor(() => expect(screen.getByText(/Preview, not locked/)).toBeTruthy())
    expect(screen.getByText(/Only forecasts captured in the T−90 lock window/)).toBeTruthy()
  })

  it('shows only locked prospective games in the grading history', async () => {
    const graded = {
      ...payload.games[0],
      game_id: 'graded-game',
      scheduled_start_utc: '2026-10-20T23:00:00Z',
      status: 'graded' as const,
      result: { home_score: 109, away_score: 102 },
      models: Object.fromEntries(models.map((model) => [model.id, {
        model_version: model.version, home_win_probability: 0.6,
        projected_home_points: 110, projected_away_points: 104,
        score_forecast_available: model.projects_scores,
        grade: { home_score: 109, away_score: 102, winner_brier: 0.16 },
      }])),
    }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({
      ok: true, json: () => Promise.resolve({ ...payload, games: [graded] }),
    }))
    render(<NbaModelTab />)
    await waitFor(() => expect(screen.getByText('Prospective grading')).toBeTruthy())
    expect(screen.getByText('Final 102–109')).toBeTruthy()
    expect(screen.getAllByText(/Brier 0.160/).length).toBe(3)
  })
})
