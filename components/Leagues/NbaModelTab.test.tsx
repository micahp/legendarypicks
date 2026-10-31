import React from 'react'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import NbaModelTab from './NbaModelTab'

const models = [
  { id: 'G1', label: 'G1 Elo', version: 'g1-version', projects_scores: false, note: 'Elo model' },
  { id: 'G2', label: 'G2 Efficiency', version: 'g2-version', projects_scores: true, note: 'Efficiency model' },
  { id: 'G3', label: 'G3 Joint scores', version: 'g3-version', projects_scores: true, note: 'Joint score model' },
]

function dateInDays(days: number, hour = 19) {
  const date = new Date()
  date.setDate(date.getDate() + days)
  date.setHours(hour, 0, 0, 0)
  return date.toISOString()
}

function dayLabel(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })
}

function previewGame(gameId: string, scheduled: string, away: string, home: string) {
  return {
    game_id: gameId,
    scheduled_start_utc: scheduled,
    home_team: home,
    away_team: away,
    status: 'preview' as const,
    locked_at_utc: null,
    result: null,
    models: {
      G1: {
        model_version: 'g1-version', home_win_probability: 0.55,
        projected_home_points: null, projected_away_points: null, score_forecast_available: false,
      },
      G2: {
        model_version: 'nba-g2-efficiency-v1-ewma08-reg50-hca2', home_win_probability: 0.57,
        projected_home_points: 111.2, projected_away_points: 108.4, score_forecast_available: true,
      },
      G3: {
        model_version: 'g3-version', home_win_probability: 0.58,
        projected_home_points: 112.1, projected_away_points: 108.9, score_forecast_available: true,
      },
    },
  }
}

const firstGameDay = dateInDays(1, 18)
const secondGameDay = dateInDays(1, 21)
const nextGameDay = dateInDays(2, 19)

const payload = {
  season: 2027,
  state: 'available',
  default_model: 'G3',
  models,
  records: {
    G1: { locked: 0, graded: 0, awaiting: 0, missed: 0, winner_brier: null, winner_log_loss: null },
    G2: { locked: 0, graded: 0, awaiting: 0, missed: 0, winner_brier: null, winner_log_loss: null },
    G3: { locked: 0, graded: 0, awaiting: 0, missed: 0, winner_brier: null, winner_log_loss: null },
  },
  games: [
    previewGame('game-1', firstGameDay, 'BOS', 'DET'),
    previewGame('game-2', secondGameDay, 'NYK', 'PHI'),
    previewGame('game-3', nextGameDay, 'LAL', 'CHI'),
  ],
  benchmark: {
    eligible_games: { train: 5800, validation: 2460, test: 2460 },
    metrics: {
      validation: {
        G1: { games: 2460, winner_brier: 0.22, winner_log_loss: 0.64, winner_accuracy: 0.64, calibration: { ece_10_bin: 0.03 } },
      },
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
  it('shows projections grouped under day headings and removes the research header', async () => {
    render(<NbaModelTab />)
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Projections · G3 Joint scores' })).toBeTruthy())

    expect(screen.getByText('DET win probability 58.0%')).toBeTruthy()
    expect(screen.getByText('PHI win probability 58.0%')).toBeTruthy()
    expect(screen.getByText('CHI win probability 58.0%')).toBeTruthy()
    expect(screen.getByText('Projected score: BOS 108.9 – DET 112.1')).toBeTruthy()
    expect(screen.getByText('Projected score: NYK 108.9 – PHI 112.1')).toBeTruthy()
    expect(screen.getByText('Projected score: LAL 108.9 – CHI 112.1')).toBeTruthy()
    expect(screen.queryByText(/2026–27 projections/)).toBeNull()
    expect(screen.getAllByRole('heading', { name: dayLabel(firstGameDay) })).toHaveLength(1)
    expect(screen.getAllByRole('heading', { name: dayLabel(nextGameDay) })).toHaveLength(1)
    expect(screen.queryByText('Upcoming forecasts')).toBeNull()
    expect(screen.queryByText('Research candidates')).toBeNull()
    expect(screen.queryByText('Research only')).toBeNull()
    expect(screen.queryByText('NBA game model · 2026–27')).toBeNull()
    expect(screen.queryByText(/Brier/)).toBeNull()
    expect(screen.queryByText(/SportsDataverse/)).toBeNull()
  })

  it('keeps every Brier score inside the Model accuracy tooltip', async () => {
    render(<NbaModelTab />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Model accuracy' })).toBeTruthy())
    expect(screen.queryByText('Brier ↓')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Model accuracy' }))
    expect(screen.getByRole('tooltip')).toBeTruthy()
    expect(screen.getByText('Brier ↓')).toBeTruthy()
    expect(screen.getByText(/G3 Joint scores · Test/)).toBeTruthy()
    expect(screen.getAllByText('0.2100').length).toBeGreaterThan(0)
    expect(screen.getByText(/Unlocked preview grades are excluded/)).toBeTruthy()
  })

  it('lists model-specific locked forecasts in Record and excludes unlocked preview grades', async () => {
    const lockedGame = {
      ...previewGame('locked-game', '2026-10-20T23:00:00Z', 'BOS', 'DET'),
      status: 'graded' as const,
      result: { home_score: 109, away_score: 102 },
      models: {
        ...previewGame('locked-game', '2026-10-20T23:00:00Z', 'BOS', 'DET').models,
        G3: {
          ...previewGame('locked-game', '2026-10-20T23:00:00Z', 'BOS', 'DET').models.G3,
          locked_at_utc: '2026-10-20T21:30:00Z',
          grade: { home_score: 109, away_score: 102, home_win: true, winner_brier: 0.16 },
        },
      },
    }
    const secondLockedBase = previewGame('locked-game-2', '2026-10-20T20:00:00Z', 'NYK', 'PHI')
    const secondLockedGame = {
      ...secondLockedBase,
      status: 'graded' as const,
      result: { home_score: 105, away_score: 98 },
      models: {
        ...secondLockedBase.models,
        G3: {
          ...secondLockedBase.models.G3,
          locked_at_utc: '2026-10-20T18:30:00Z',
          grade: { home_score: 105, away_score: 98, home_win: true, winner_brier: 0.18 },
        },
      },
    }
    const unlockedGame = {
      ...previewGame('unlocked-game', '2026-10-19T23:00:00Z', 'PHI', 'NYK'),
      status: 'unlocked' as const,
      result: { home_score: 118, away_score: 111 },
      models: {
        ...previewGame('unlocked-game', '2026-10-19T23:00:00Z', 'PHI', 'NYK').models,
        G3: {
          ...previewGame('unlocked-game', '2026-10-19T23:00:00Z', 'PHI', 'NYK').models.G3,
          grade: { home_score: 118, away_score: 111, home_win: true, winner_brier: 0.09 },
        },
      },
    }
    const olderBase = previewGame('older-game', '2026-10-19T23:00:00Z', 'LAL', 'CHI')
    const olderGame = {
      ...olderBase,
      status: 'graded' as const,
      result: { home_score: 112, away_score: 106 },
      models: {
        ...olderBase.models,
        G3: {
          ...olderBase.models.G3,
          locked_at_utc: '2026-10-19T21:30:00Z',
          grade: { home_score: 112, away_score: 106, home_win: true, winner_brier: 0.14 },
        },
      },
    }
    const recordPayload = {
      ...payload,
      records: {
        ...payload.records,
        G3: { locked: 2, graded: 2, awaiting: 0, missed: 1, winner_brier: 0.17, winner_log_loss: 0.5 },
      },
      games: [lockedGame, secondLockedGame, unlockedGame],
    }
    const firstPage = {
      season: 2027, model: 'G3', games: [lockedGame, secondLockedGame],
      record: recordPayload.records.G3, has_more: true, next_before: '2026-10-20',
    }
    const olderPage = {
      season: 2027, model: 'G3', games: [olderGame],
      record: recordPayload.records.G3, has_more: false, next_before: null,
    }
    ;(global as any).fetch = jest.fn((url: string) => {
      const isRecordRequest = String(url).includes('/api/nba/model/record?')
      const responsePayload = !isRecordRequest
        ? payload
        : String(url).includes('before=') ? olderPage : firstPage
      return Promise.resolve({ ok: true, json: () => Promise.resolve(responsePayload) })
    })

    render(<NbaModelTab />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Record' })).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: 'Record' }))
    await waitFor(() => expect(screen.getByText('BOS at DET')).toBeTruthy())

    expect(screen.getByRole('heading', { name: '2026–27 record · G3 Joint scores' })).toBeTruthy()
    expect(screen.getByText('BOS at DET')).toBeTruthy()
    expect(screen.getByText('Projected score: BOS 108.9 – DET 112.1')).toBeTruthy()
    expect(screen.getByText('Final BOS 102 – DET 109 · DET won')).toBeTruthy()
    expect(screen.queryByText(/· Locked \d/)).toBeNull()
    const recordDay = screen.getByRole('heading', { name: dayLabel(lockedGame.scheduled_start_utc) })
    expect(screen.getAllByRole('heading', { name: dayLabel(lockedGame.scheduled_start_utc) })).toHaveLength(1)
    expect(within(recordDay.parentElement as HTMLElement).getByText('BOS at DET')).toBeTruthy()
    expect(within(recordDay.parentElement as HTMLElement).getByText('NYK at PHI')).toBeTruthy()
    expect(screen.getAllByText('Graded').length).toBeGreaterThanOrEqual(3)
    expect(screen.queryByText('PHI at NYK')).toBeNull()
    expect(screen.queryByText(/Brier/)).toBeNull()
    expect(within(screen.getByText('Missed locks').parentElement as HTMLElement).getByText('1')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Load older dates' }))
    await waitFor(() => expect(screen.getByText('LAL at CHI')).toBeTruthy())
    expect(screen.getByRole('heading', { name: dayLabel(olderGame.scheduled_start_utc) })).toBeTruthy()
  })

  it('updates projections and record content when a different model is selected', async () => {
    render(<NbaModelTab />)
    await waitFor(() => expect(screen.getByLabelText('Model')).toBeTruthy())
    fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'G1' } })
    expect(screen.getByRole('heading', { name: 'Projections · G1 Elo' })).toBeTruthy()
    expect(screen.getAllByText(/No score projection/)).toHaveLength(3)
    fireEvent.change(screen.getByLabelText('Model'), { target: { value: 'G2' } })
    expect(screen.getByRole('heading', { name: 'Projections · G2 Efficiency' })).toBeTruthy()
    expect(screen.queryByText('nba-g2-efficiency-v1-ewma08-reg50-hca2')).toBeNull()
  })
})
