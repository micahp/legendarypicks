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
    g2: { graded: 0, forecasts: 2, late: 0, legacy: 0, missed: 0, brier: null, log_loss: null, accuracy: null },
    c2: { graded: 0, forecasts: 2, late: 0, legacy: 0, missed: 0, brier: null, log_loss: null, accuracy: null },
    g2h: { graded: 1, forecasts: 2, late: 0, legacy: 0, missed: 0, brier: 0.12, log_loss: 0.4, accuracy: 1 },
  },
  season: 2026,
  games: [
    {
      game_id: '401',
      kickoff_utc: new Date(Date.now() + 86400000).toISOString(),
      home_team: 'Texas Longhorns',
      away_team: 'Oklahoma Sooners',
      status: 'locked',
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

  it('shows each team record and no price-feed or fitted-through notes', async () => {
    const withRecords = { ...payload, games: [{ ...payload.games[0], home_record: '5-2', away_record: '3-3' }] }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(withRecords) }))
    render(<FbsModelTab />)
    await waitFor(() => expect(screen.getByText('5-2')).toBeTruthy())
    expect(screen.getByText('3-3')).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/price feed|qualifying wager|fitted through/)
  })

  it('shows graded count with the sample-size caveat on the record tab', async () => {
    render(<FbsModelTab />)
    await waitFor(() => expect(screen.getAllByText(/Texas Longhorns/).length).toBeGreaterThan(0))
    fireEvent.click(screen.getByRole('button', { name: 'record' }))
    expect(screen.getByText('0.1200')).toBeTruthy()
    expect(screen.getByText(/treat the number as an early read/)).toBeTruthy()
  })

  it('shows a graded stored forecast in the record like any other, with no status label', async () => {
    const legacy = {
      ...payload.games[0],
      game_id: 'legacy-game',
      kickoff_utc: new Date(Date.now() - 86400000).toISOString(),
      status: 'legacy',
      locked_at_utc: null,
      late: true,
      result: { home_score: 27, away_score: 17, home_win: true },
    }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({
      ok: true, json: () => Promise.resolve({ ...payload, games: [legacy] }),
    }))
    render(<FbsModelTab />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'record' })).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: 'record' }))
    expect(screen.queryByText(/No games have started yet/)).toBeNull()
    expect(screen.getByText('✓ Won')).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/Legacy|not official|excluded/i)
  })

  it('shows a preview with no status label and keeps it out of the record', async () => {
    const preview = {
      ...payload.games[0],
      game_id: 'preview-game',
      status: 'preview',
      locked_at_utc: null,
      models: { g2: forecast(0.55), c2: forecast(0.6), g2h: forecast(0.68) },
    }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({
      ok: true, json: () => Promise.resolve({ ...payload, games: [preview] }),
    }))
    render(<FbsModelTab />)
    await waitFor(() => expect(screen.getByText('68.0%')).toBeTruthy())
    expect(document.body.textContent).not.toMatch(/Preview, not locked|Locked before kickoff|Forecast status/)
    fireEvent.click(screen.getByRole('button', { name: 'record' }))
    expect(screen.getByText(/No games have started yet in the locked window/)).toBeTruthy()
  })

  it('shows no missed-window text on the record tab and no forecast for it', async () => {
    const missed = {
      ...payload.games[0],
      game_id: 'missed-game',
      kickoff_utc: new Date(Date.now() - 86400000).toISOString(),
      status: 'missed',
      locked_at_utc: null,
      late: false,
      result: { home_score: 10, away_score: 14, home_win: false },
      models: {},
    }
    ;(global as any).fetch = jest.fn(() => Promise.resolve({
      ok: true, json: () => Promise.resolve({
        ...payload,
        records: { ...payload.records, g2h: { ...payload.records.g2h, missed: 1 } },
        games: [missed],
      }),
    }))
    render(<FbsModelTab />)
    await waitFor(() => expect(screen.getByRole('button', { name: 'record' })).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: 'record' }))
    expect(document.body.textContent).not.toMatch(/Missed lock windows|Legacy rows/)
    expect(screen.queryByText('✓ Won')).toBeNull()
    expect(screen.queryByText('✗ Lost')).toBeNull()
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
