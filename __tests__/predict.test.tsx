import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import PredictPage from '../pages/predict'

const mockRouter = {
  query: {} as Record<string, string>,
  isReady: true,
  push: jest.fn(),
}
jest.mock('next/router', () => ({ useRouter: () => mockRouter }))
jest.mock('../lib/deviceId', () => ({ getDeviceId: () => 'test-device' }))
jest.mock('../lib/analytics', () => ({ trackPickMade: jest.fn() }))

const ok = (payload: any) => Promise.resolve({ ok: true, status: 200, json: async () => payload })
const emptyRecord = { wins: 0, losses: 0, voids: 0, streak: 0 }

describe('multi-sport predict page', () => {
  beforeEach(() => {
    mockRouter.query = {}
    mockRouter.push.mockReset()
  })

  it('keeps the existing esports endpoints and title selector', async () => {
    ;(global as any).fetch = jest.fn((input: string) => {
      if (input.startsWith('/api/esports/predict')) return ok({
        schema_version: 'v1', selected_title: { slug: 'cod', label: 'Call of Duty' },
        titles: [{ slug: 'cod', label: 'Call of Duty', match_count: 0, live_count: 0, result_count: 0, next_start: null }],
        matches: [], match_count: 0, has_more: false, building: false, error: null, source: 'stored',
      })
      if (input === '/api/esports/picks/me') return ok({ picks: [], record: emptyRecord })
      throw new Error(`unexpected fetch ${input}`)
    })
    render(<PredictPage />)
    expect(await screen.findByText('Call of Duty matches')).toBeTruthy()
    expect((global.fetch as jest.Mock)).toHaveBeenCalledWith('/api/esports/picks/me', expect.objectContaining({ headers: { 'X-Device-Id': 'test-device' } }))
    expect(screen.getByRole('button', { name: 'Call of Duty' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Previous esports titles' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Next esports titles' })).toBeTruthy()
  })

  it('renders a three-way soccer card and persists through the generic ledger', async () => {
    mockRouter.query = { sport: 'mls' }
    ;(global as any).fetch = jest.fn((input: string, init?: RequestInit) => {
      if (input === '/api/sports/predict?league=mls') return ok({
        schema_version: 'sports-predict-v1', selected_title: { slug: 'mls', label: 'MLS' }, titles: [],
        matches: [{ matchKey: 'mls:1', teamA: 'Away FC', teamB: 'Home FC', title: 'MLS', league: 'mls', startTime: Date.now() + 60000, logoA: null, logoB: null, live: false, finished: false, allowDraw: true }],
        match_count: 1, has_more: false, building: false, error: null, source: 'scoreboard_snapshots',
      })
      if (input === '/api/sports/picks/me?league=mls') return ok({ picks: [], record: emptyRecord })
      if (input === '/api/sports/picks' && init?.method === 'POST') return ok({ matchKey: 'mls:1' })
      throw new Error(`unexpected fetch ${input}`)
    })
    render(<PredictPage />)
    const draw = await screen.findByRole('button', { name: 'Pick Draw' })
    await act(async () => { fireEvent.click(draw) })
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/api/sports/picks', expect.objectContaining({
      method: 'POST', body: JSON.stringify({ league: 'mls', matchKey: 'mls:1', side: 'D' }),
    })))
    expect(screen.getByText('Away FC')).toBeTruthy()
    expect(screen.getByText('Home FC')).toBeTruthy()
    expect(screen.queryByText(/MLS · MLS/)).toBeNull()
    expect(screen.queryByText(/^MLS ·/)).toBeNull()
  })

  it('adapts the existing UFC fight ledger instead of creating another one', async () => {
    mockRouter.query = { sport: 'ufc' }
    ;(global as any).fetch = jest.fn((input: string, init?: RequestInit) => {
      if (input === '/api/ufc/upcoming') return ok({ fights: [{ fightKey: 'fight-1', event: 'UFC 999', state: 'pre', lockAt: Date.now() + 60000, away: { name: 'Away Fighter' }, home: { name: 'Home Fighter' } }] })
      if (input === '/api/ufc/picks/me') return ok({ picks: [], record: emptyRecord })
      if (input === '/api/ufc/picks' && init?.method === 'POST') return ok({ fightKey: 'fight-1' })
      throw new Error(`unexpected fetch ${input}`)
    })
    render(<PredictPage />)
    const fighter = await screen.findByRole('button', { name: 'Pick Away Fighter' })
    await act(async () => { fireEvent.click(fighter) })
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/api/ufc/picks', expect.objectContaining({
      body: JSON.stringify({ fightKey: 'fight-1', side: 'away', method: null }),
    })))
  })

  it('shows the published tournament seed on a tennis prediction card', async () => {
    mockRouter.query = { sport: 'atp' }
    ;(global as any).fetch = jest.fn((input: string) => {
      if (input === '/api/sports/predict?league=atp') return ok({
        schema_version: 'sports-predict-v1', selected_title: { slug: 'atp', label: 'ATP' }, titles: [],
        matches: [{ matchKey: 'atp:1', teamA: 'Jannik Sinner', teamB: 'Unseeded Player', title: 'ATP', league: 'atp', startTime: Date.now() + 60000, logoA: null, logoB: null, seedA: 1, seedB: null, live: false, finished: false }],
        match_count: 1, has_more: false, building: false, error: null, source: 'scoreboard_snapshots',
      })
      if (input === '/api/sports/picks/me?league=atp') return ok({ picks: [], record: emptyRecord })
      throw new Error(`unexpected fetch ${input}`)
    })
    render(<PredictPage />)
    expect(await screen.findByText('(1) Jannik Sinner')).toBeTruthy()
    expect(screen.getAllByText('Unseeded Player').length).toBeGreaterThan(0)
    expect(screen.queryByText(/undefined.*Unseeded Player/)).toBeNull()
  })

  it('groups soccer under one sport selector and opens its league menu only when selected', async () => {
    mockRouter.query = { sport: 'soccer' }
    ;(global as any).fetch = jest.fn((input: string) => {
      if (input === '/api/sports/predict?leagues=mls%2Clcup%2Cwc') return ok({
        schema_version: 'sports-predict-v1', selected_title: { slug: 'mls,lcup,wc', label: 'Soccer' }, titles: [],
        matches: [], match_count: 0, has_more: false, building: false, error: null, source: null,
      })
      if (input === '/api/sports/picks/me?leagues=mls%2Clcup%2Cwc') return ok({ picks: [], record: emptyRecord })
      throw new Error(`unexpected fetch ${input}`)
    })
    render(<PredictPage />)
    expect(await screen.findByText('No open Soccer games in the stored slate right now.')).toBeTruthy()
    const soccer = await screen.findByRole('button', { name: 'Soccer' })
    expect(soccer.textContent).toContain('▼')
    fireEvent.click(soccer)
    expect(await screen.findByRole('menu', { name: 'Soccer filters' })).toBeTruthy()
    expect(screen.getByRole('menuitemradio', { name: /All Soccer/ })).toBeTruthy()
    expect(screen.getByRole('menuitemradio', { name: /MLS/ })).toBeTruthy()
    expect(screen.getByRole('menuitemradio', { name: /Leagues Cup/ })).toBeTruthy()
    expect(screen.getByRole('menuitemradio', { name: /World Cup/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Tennis' }).textContent).not.toContain('▼')
    expect(screen.queryByRole('button', { name: 'WNBA' })).toBeNull()
  })

  it('groups matches under an Eastern day, shows upcoming time, and closes live picks', async () => {
    mockRouter.query = { sport: 'mlb' }
    ;(global as any).fetch = jest.fn((input: string) => {
      if (input === '/api/sports/predict?league=mlb') return ok({
        schema_version: 'sports-predict-v1', selected_title: { slug: 'mlb', label: 'MLB' }, titles: [],
        matches: [
          { matchKey: 'mlb:live', teamA: 'Live Away', teamB: 'Live Home', title: 'MLB', league: 'mlb', startTime: Date.parse('2030-08-26T18:00:00Z'), logoA: null, logoB: null, live: true, finished: false },
          { matchKey: 'mlb:next', teamA: 'Next Away', teamB: 'Next Home', title: 'MLB', league: 'mlb', startTime: Date.parse('2030-08-26T20:00:00Z'), logoA: null, logoB: null, live: false, finished: false },
        ],
        match_count: 2, has_more: false, building: false, error: null, source: 'scoreboard_snapshots',
      })
      if (input === '/api/sports/picks/me?league=mlb') return ok({ picks: [], record: emptyRecord })
      throw new Error(`unexpected fetch ${input}`)
    })
    render(<PredictPage />)
    expect(await screen.findByRole('heading', { name: 'Monday, August 26' })).toBeTruthy()
    expect(screen.getByText(/4:00 PM E[DS]T/)).toBeTruthy()
    expect(screen.getByText(/LIVE/)).toBeTruthy()
    expect(screen.getByText('Picks closed — game in progress.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Pick Live Away' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Pick Next Away' })).toBeTruthy()
  })
})
