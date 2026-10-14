import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import KalshiLivePanel, { KalshiLive, KalshiMatch, ageNowS, visibleMatches } from './KalshiLivePanel'

const match = (over: Partial<KalshiMatch> = {}): KalshiMatch => ({
  milestone_id: 'm1',
  title: 'Pohankova vs Wang',
  tour: 'WTA',
  status: 'live',
  finished: false,
  game_score_p1: '40',
  game_score_p2: '30',
  advantage: '',
  server_side: '1',
  sets_p1: ['6', '5'],
  sets_p2: ['4', '3'],
  sets_won_p1: 1,
  sets_won_p2: 1,
  p1: 'Pohankova',
  p2: 'Wang',
  polled_at: '2026-10-13T12:00:00+00:00',
  age_s: 2,
  ...over,
})

const live = (over: Partial<KalshiLive> = {}): KalshiLive => ({
  available: true,
  reason: null,
  generated_at: '2026-10-13T12:00:01+00:00',
  matches: [match()],
  ...over,
})

function mockFetch(body: KalshiLive | null, ok = true) {
  ;(global as any).fetch = jest.fn(() =>
    Promise.resolve({ ok, status: ok ? 200 : 500, json: () => Promise.resolve(body) }),
  )
}

afterEach(() => {
  jest.restoreAllMocks()
  delete (global as any).fetch
})

describe('age and drop rules', () => {
  it('adds the time since the response arrived to the server age', () => {
    expect(ageNowS(match({ age_s: 2 }), 1_000, 4_000)).toBe(5)
  })

  it('drops a match once its age passes 60 seconds', () => {
    const fetchedAt = 0
    const rows = visibleMatches(live({ matches: [match({ age_s: 59 }), match({ milestone_id: 'm2', age_s: 2 })] }), fetchedAt, 2_000)
    expect(rows.map((m) => m.milestone_id)).toEqual(['m2'])
    expect(visibleMatches(live({ matches: [match({ age_s: 59 })] }), 0, 2_000)).toEqual([])
  })
})

describe('KalshiLivePanel', () => {
  it('renders nothing when the day is not today', () => {
    mockFetch(live())
    const { container } = render(<KalshiLivePanel league="wta" active={false} />)
    expect(container.innerHTML).toBe('')
    expect((global as any).fetch).not.toHaveBeenCalled()
  })

  it('shows both players, the point score, set games and the age label', async () => {
    mockFetch(live())
    render(<KalshiLivePanel league="wta" active />)
    expect(await screen.findByText('Pohankova')).toBeTruthy()
    expect(screen.getByText('Wang')).toBeTruthy()
    expect(screen.getByText('40')).toBeTruthy()
    expect(screen.getByText('30')).toBeTruthy()
    expect(screen.getByLabelText('serving')).toBeTruthy()
    expect(screen.getByText(/Kalshi, \d+s ago/)).toBeTruthy()
    expect((global as any).fetch).toHaveBeenCalledWith('/api/wta/kalshi-live', { cache: 'no-store' })
  })

  it('says why points are unavailable instead of showing an empty list', async () => {
    mockFetch(live({ available: false, reason: 'poller stale since 11:55:00 UTC', matches: [] }))
    render(<KalshiLivePanel league="atp" active />)
    expect(await screen.findByText('Point scores unavailable: poller stale since 11:55:00 UTC')).toBeTruthy()
  })

  it('says there are no live matches when the file is fine and empty', async () => {
    mockFetch(live({ matches: [] }))
    render(<KalshiLivePanel league="atp" active />)
    expect(await screen.findByText('No live Kalshi matches.')).toBeTruthy()
  })

  it('says the request failed and shows no score when the endpoint errors', async () => {
    mockFetch(null, false)
    render(<KalshiLivePanel league="atp" active />)
    await waitFor(() => expect(screen.getByText('Point scores unavailable: the request failed.')).toBeTruthy())
    expect(screen.queryByText('40')).toBeNull()
  })

  it('renders a dash for a missing value, never a zero', async () => {
    mockFetch(live({ matches: [match({ game_score_p2: '', server_side: '', sets_p2: [], sets_won_p2: null })] }))
    render(<KalshiLivePanel league="wta" active />)
    await screen.findByText('Pohankova')
    expect(screen.queryByLabelText('serving')).toBeNull()
    expect(screen.getAllByText('–').length).toBeGreaterThanOrEqual(3)
    expect(screen.queryByText('0')).toBeNull()
  })
})
