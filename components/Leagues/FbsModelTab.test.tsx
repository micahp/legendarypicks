import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import FbsModelTab from './FbsModelTab'

const projection = (pHome: number, frozen: boolean) => ({
  p_home: pHome,
  p_away: 1 - pHome,
  fair_home: pHome >= 0.5 ? -150 : 130,
  fair_away: pHome >= 0.5 ? 130 : -150,
  model_version: 'fbs-g2h-20261017',
  fitted_through: '2026-10-17',
  projected_at_utc: '2026-10-20T10:00:00Z',
  frozen_at_utc: frozen ? '2026-10-20T12:00:00Z' : null,
})

const upcomingGame = {
  game_id: '401',
  kickoff_utc: new Date(Date.now() + 86400000).toISOString(),
  home_team: 'Texas Longhorns',
  away_team: 'Oklahoma Sooners',
  neutral_site: false,
  result: null,
  models: { g2: projection(0.55, true), c2: projection(0.6, true), g2h: projection(0.68, true) },
}

const payload = {
  league: 'ncaaf',
  default_model: 'g2h',
  models: [
    { id: 'g2', label: 'Basic Elo', note: 'Chronological Elo.' },
    { id: 'c2', label: 'Drive + efficiency', note: 'Flat logistic.' },
    { id: 'g2h', label: 'Hierarchical', note: 'Random intercepts.' },
  ],
  records: {
    g2: { frozen: 2, graded: 0, accuracy: null, brier: null, log_loss: null, history: [] },
    c2: { frozen: 2, graded: 0, accuracy: null, brier: null, log_loss: null, history: [] },
    g2h: { frozen: 2, graded: 1, accuracy: 1, brier: 0.12, log_loss: 0.4, history: [{
      game_id: 'past-1', kickoff_utc: '2026-10-18T19:00:00Z', p_home: 0.68, home_win: true,
      home_score: 27, away_score: 17, graded: 1, accuracy: 1, brier: 0.12,
    }] },
  },
  season: 2026,
  games: [upcomingGame],
  ratings: [],
  meta: {},
  state: 'available',
  source: 'test',
}

const serve = (body: unknown) => {
  ;(global as any).fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(body) }))
}

beforeEach(() => serve(payload))

describe('FBS model tab', () => {
  it('defaults to the hierarchical model and shows both sides with fair odds', async () => {
    render(<FbsModelTab />)
    await waitFor(() => expect(screen.getAllByText(/Texas Longhorns/).length).toBeGreaterThan(0))
    expect((screen.getByLabelText('Model') as HTMLSelectElement).value).toBe('g2h')
    expect(screen.getByText('68.0%')).toBeTruthy()
    expect(screen.getByText('32.0%')).toBeTruthy()
  })

  it('shows each team record and no price-feed or fitted-through notes', async () => {
    serve({ ...payload, games: [{ ...upcomingGame, home_record: '5-2', away_record: '3-3' }] })
    render(<FbsModelTab />)
    await waitFor(() => expect(screen.getByText('5-2')).toBeTruthy())
    expect(screen.getByText('3-3')).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/price feed|qualifying wager|fitted through/)
  })

  it('shows no status labels on a projection card', async () => {
    render(<FbsModelTab />)
    await waitFor(() => expect(screen.getAllByText(/Texas Longhorns/).length).toBeGreaterThan(0))
    const card = screen.getByRole('article')
    expect(card.textContent).not.toMatch(/preview|locked|lock|missed|legacy|research|frozen|official|status/i)
    expect(screen.getByText('Venue')).toBeTruthy()
  })

  it('shows a projection the same way whether or not it has been frozen yet', async () => {
    serve({ ...payload, games: [{ ...upcomingGame, models: { g2: projection(0.55, false), c2: projection(0.6, false), g2h: projection(0.68, false) } }] })
    render(<FbsModelTab />)
    await waitFor(() => expect(screen.getByText('68.0%')).toBeTruthy())
    expect(screen.getByRole('article').textContent).not.toMatch(/preview|locked|lock|frozen/i)
  })

  it('shows the neutral-site venue when the game is played on neutral ground', async () => {
    serve({ ...payload, games: [{ ...upcomingGame, neutral_site: true }] })
    render(<FbsModelTab />)
    await waitFor(() => expect(screen.getByText('Neutral site')).toBeTruthy())
  })

  it('shows the graded count with the sample-size caveat on the record tab', async () => {
    render(<FbsModelTab />)
    await waitFor(() => expect(screen.getAllByText(/Texas Longhorns/).length).toBeGreaterThan(0))
    fireEvent.click(screen.getByRole('button', { name: 'record' }))
    expect(screen.getByText('0.1200')).toBeTruthy()
    expect(screen.getByText(/treat the number as an early read/)).toBeTruthy()
  })

  it('lists a graded projection with its final score and result on the record tab', async () => {
    render(<FbsModelTab />)
    await waitFor(() => expect(screen.getAllByText(/Texas Longhorns/).length).toBeGreaterThan(0))
    fireEvent.click(screen.getByRole('button', { name: 'record' }))
    expect(screen.getByText('17–27')).toBeTruthy()
    expect(screen.getByText('✓ Won')).toBeTruthy()
  })

  it('keeps ungraded projections out of the record history', async () => {
    serve({ ...payload, records: { ...payload.records, g2h: { ...payload.records.g2h, graded: 0, history: [] } } })
    render(<FbsModelTab />)
    await waitFor(() => expect(screen.getAllByText(/Texas Longhorns/).length).toBeGreaterThan(0))
    fireEvent.click(screen.getByRole('button', { name: 'record' }))
    expect(screen.getByText('No graded projections yet.')).toBeTruthy()
    expect(screen.queryByText('✓ Won')).toBeNull()
    expect(screen.queryByText('✗ Lost')).toBeNull()
  })

  it('says there are no projections yet when the season has none', async () => {
    serve({ ...payload, games: [], state: 'awaiting_first_projection' })
    render(<FbsModelTab />)
    await waitFor(() => expect(screen.getByText('No projections for 2026 yet.')).toBeTruthy())
  })

  it('renders the saved ratings and does not invent a spread', async () => {
    serve({
      ...payload,
      ratings: [{ team_id: '1', season: 2026, team: 'Texas Longhorns',
        conference: 'SEC', rating: 0.345, games_used: 6,
        as_of_utc: '2026-10-20T12:00:00Z' }],
    })
    render(<FbsModelTab />)
    await waitFor(() => expect(screen.getByText('68.0%')).toBeTruthy())
    expect(screen.queryByText(/Fair spread hint/)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'ratings' }))
    expect(screen.getByText('SEC')).toBeTruthy()
    expect(screen.getByText('0.345')).toBeTruthy()
  })
})
