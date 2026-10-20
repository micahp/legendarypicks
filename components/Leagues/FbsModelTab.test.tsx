import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import FbsModelTab from './FbsModelTab'

const forecast = (pHome: number) => ({
  p_home: pHome,
  p_away: 1 - pHome,
  fair_home: pHome >= 0.5 ? -150 : 130,
  fair_away: pHome >= 0.5 ? 130 : -150,
  model_version: 'fbs-g2h-20261017',
  fitted_through: '2026-10-17',
})

const payload = {
  league: 'ncaaf',
  default_model: 'g2h',
  models: [
    { id: 'g2', label: 'Basic Elo', note: 'Chronological Elo.' },
    { id: 'c2', label: 'Drive + efficiency', note: 'Flat logistic.' },
    { id: 'g2h', label: 'Hierarchical', note: 'Random intercepts.' },
  ],
  records: {
    g2: { graded: 0, forecasts: 2, late: 0, brier: null, log_loss: null, accuracy: null },
    c2: { graded: 0, forecasts: 2, late: 0, brier: null, log_loss: null, accuracy: null },
    g2h: { graded: 1, forecasts: 2, late: 0, brier: 0.12, log_loss: 0.4, accuracy: 1 },
  },
  season: 2026,
  games: [
    {
      game_id: '401',
      kickoff_utc: new Date(Date.now() + 86400000).toISOString(),
      home_team: 'Texas Longhorns',
      away_team: 'Oklahoma Sooners',
      locked_at_utc: '2026-10-20T12:00:00Z',
      late: false,
      result: null,
      models: { g2: forecast(0.55), c2: forecast(0.6), g2h: forecast(0.68) },
    },
  ],
  ratings: [],
  meta: {},
  state: 'available',
  source: 'test',
}

beforeEach(() => {
  ;(global as any).fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(payload) }))
})

describe('FBS model tab', () => {
  it('defaults to the hierarchical model and shows both sides with fair odds', async () => {
    render(<FbsModelTab />)
    await waitFor(() => expect(screen.getAllByText(/Texas Longhorns/).length).toBeGreaterThan(0))
    expect((screen.getByLabelText('Model') as HTMLSelectElement).value).toBe('g2h')
    expect(screen.getByText('68.0%')).toBeTruthy()
    expect(screen.getByText('32.0%')).toBeTruthy()
  })

  it('states that nothing is a qualifying wager without a price feed', async () => {
    render(<FbsModelTab />)
    await waitFor(() => expect(screen.getByText(/no NCAAF moneyline or spread price feed/)).toBeTruthy())
  })

  it('shows graded count with the sample-size caveat on the record tab', async () => {
    render(<FbsModelTab />)
    await waitFor(() => expect(screen.getAllByText(/Texas Longhorns/).length).toBeGreaterThan(0))
    fireEvent.click(screen.getByRole('button', { name: 'record' }))
    expect(screen.getByText('0.1200')).toBeTruthy()
    expect(screen.getByText(/treat the number as an early read/)).toBeTruthy()
  })

  it('never labels a late research forecast as an official win', async () => {
    const late = {
      ...payload.games[0],
      game_id: 'late-game',
      kickoff_utc: new Date(Date.now() - 86400000).toISOString(),
      locked_at_utc: null,
      late: true,
      result: { home_score: 27, away_score: 17, home_win: true },
    }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({
      ok: true, json: () => Promise.resolve({ ...payload, games: [late] }),
    }))
    render(<FbsModelTab />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'record' })).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: 'record' }))
    expect(screen.getByText(/No games have started yet in the locked window/)).toBeTruthy()
    expect(screen.queryByText('✓ Won')).toBeNull()
  })

  it('renders the saved ratings and does not invent a spread', async () => {
    ;(global as any).fetch = jest.fn(() => Promise.resolve({
      ok: true, json: () => Promise.resolve({
        ...payload,
        ratings: [{ team_id: '1', season: 2026, team: 'Texas Longhorns',
          conference: 'SEC', rating: 0.345, games_used: 6,
          as_of_utc: '2026-10-20T12:00:00Z' }],
      }),
    }))
    render(<FbsModelTab />)
    await waitFor(() => expect(screen.getByText('68.0%')).toBeTruthy())
    expect(screen.queryByText(/Fair spread hint/)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'ratings' }))
    expect(screen.getByText('SEC')).toBeTruthy()
    expect(screen.getByText('0.345')).toBeTruthy()
  })

})
