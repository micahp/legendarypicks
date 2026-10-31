import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import NflPixelHQ from './NflPixelHQ'

const originalFetch = global.fetch

const jsonResponse = (body: unknown, headers: Record<string, string> = {}) => ({
  ok: true,
  json: async () => body,
  headers: { get: (name: string) => headers[name.toLowerCase()] ?? null },
}) as Response

async function renderRoom() {
  let result!: ReturnType<typeof render>
  await act(async () => {
    result = render(<NflPixelHQ data={null} loading={false} error={null} />)
    await new Promise(resolve => setTimeout(resolve, 0))
  })
  return result
}

describe('NflPixelHQ', () => {
  beforeEach(() => {
    global.fetch = jest.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith('/api/nfl/games')) return Promise.resolve(jsonResponse([{
        game_id: 'nfl-1', state: 'in', date: '2026-10-31T18:00:00Z', quarter: 2,
        home: { abbrev: 'KC', name: 'Kansas City Chiefs', score: 21 },
        away: { abbrev: 'LAC', name: 'LA Chargers', score: 17 },
      }], { 'x-lp-data-source': 'scoreboard_snapshots', 'x-lp-data-age': '60' }))
      if (url === '/api/nfl/model/locks') return Promise.resolve(jsonResponse({ week: null, models: [], games: [] }))
      if (url === '/api/nfl/projections') return Promise.resolve(jsonResponse({ week: null, players: [] }))
      if (url.includes('/api/props/slate?league=nfl')) return Promise.resolve(jsonResponse([{
        game_id: 52, home: 'KC', away: 'LAC', date: '2026-11-01', prop_count: 1, players: [],
      }]))
      if (url.includes('/api/props/slate?game_id=52')) return Promise.resolve(jsonResponse([{
        game_id: 52, home: 'KC', away: 'LAC', date: '2026-11-01', prop_count: 1,
        players: [{ id: 44, name: 'Test Receiver', team: 'KC', props: [{
          market: 'rec_yds', line: 50.5, side: 'over', source: 'Bovada', captured_at: '2026-10-31T16:20:00Z',
        }] }],
      }]))
      if (url.startsWith('/api/props/history')) return Promise.resolve(jsonResponse({ games: [
        { date: '2026-10-25', value: 64, opponent: 'BUF' },
        { date: '2026-10-18', value: 42, opponent: 'DEN' },
      ] }))
      return Promise.resolve(jsonResponse([]))
    })
  })

  afterEach(() => { global.fetch = originalFetch })

  it('keeps the research menu routes and shows real scoreboard data in the room', async () => {
    let result!: ReturnType<typeof render>
    await act(async () => {
      result = render(<NflPixelHQ data={null} loading={false} error="unavailable" />)
      await new Promise(resolve => setTimeout(resolve, 0))
    })

    fireEvent.click(screen.getByText('Research menu'))
    expect(screen.getByRole('link', { name: 'Scores' }).getAttribute('href')).toBe('/scores?league=nfl')
    expect(screen.getByRole('link', { name: 'Forecasts' }).getAttribute('href')).toBe('/leagues/nfl?tab=model')
    expect(screen.getByRole('link', { name: 'Player props' }).getAttribute('href')).toBe('/props?league=nfl')
    expect(screen.getByRole('link', { name: 'Player projections' }).getAttribute('href')).toBe('/nfl/projections')
    expect(screen.getByText('NFL season context is unavailable right now.')).toBeTruthy()
    await screen.findByText(/Test Receiver · rec yds/i)
    await screen.findByText(/No player projections published/i)
    await screen.findByText(/No upcoming matchup found/i)
    expect(await screen.findByText('LAC')).toBeTruthy()
    expect(screen.getByText('KC')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /scores from the television/i }))
    expect(await screen.findByText('LA Chargers at Kansas City Chiefs')).toBeTruthy()
    expect(screen.getByText(/captured 1 min ago/)).toBeTruthy()
    expect(screen.getByRole('link', { name: /open full nfl scores/i }).getAttribute('href')).toBe('/scores?league=nfl')
    fireEvent.click(screen.getByRole('button', { name: 'Return to HQ' }))
    await waitFor(() => expect(screen.getByRole('button', { name: /scores from the television/i }).getAttribute('aria-expanded')).toBe('false'))
  })

  it('opens an in-room prop preview with source time and actual player history', async () => {
    await renderRoom()

    await screen.findByText(/Test Receiver · rec yds/i)
    await screen.findByText(/No player projections published/i)
    await screen.findByText(/No upcoming matchup found/i)
    fireEvent.click(screen.getByRole('button', { name: /player props from the desk computer/i }))

    expect(await screen.findByText('Test Receiver')).toBeTruthy()
    expect(screen.getByText(/source time/)).toBeTruthy()
    expect(await screen.findByText('64')).toBeTruthy()
    expect(screen.getByRole('link', { name: /open full nfl prop board/i }).getAttribute('href')).toBe('/props?league=nfl')
  })

  it('labels career and arcade as future features without implying they work', async () => {
    await renderRoom()

    fireEvent.click(screen.getByRole('button', { name: /trophy shelf career status/i }))
    expect(screen.getByText(/career tracking is not available yet/i)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /arcade console future feature status/i }))
    expect(screen.getByText(/future destination.*no mini-game or rewards/i)).toBeTruthy()
  })
})
