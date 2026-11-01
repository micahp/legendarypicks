import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import NflPixelHQ, { getRoomTimeOfDay } from './NflPixelHQ'
import { diagrammaticFieldX } from './PixelRedZonePlayer'

const originalFetch = global.fetch

const jsonResponse = (body: unknown, headers: Record<string, string> = {}) => ({
  ok: true,
  json: async () => body,
  headers: { get: (name: string) => headers[name.toLowerCase()] ?? null },
}) as Response

describe('getRoomTimeOfDay', () => {
  it.each([
    [4, 'night'], [5, 'dawn'], [7, 'dawn'], [8, 'day'],
    [16, 'day'], [17, 'dusk'], [19, 'dusk'], [20, 'night'],
  ] as const)('maps local hour %i to %s', (hour, expected) => {
    expect(getRoomTimeOfDay(new Date(2026, 0, 1, hour))).toBe(expected)
  })
})

describe('diagrammaticFieldX', () => {
  it('redzone_offense_orientation', () => {
    const samePublisherSpotAcrossEnds = [
      { period: 1, offense: 'home', spot: 65 },
      { period: 2, offense: 'away', spot: 65 },
      { period: 3, offense: 'home', spot: 65 },
      { period: 4, offense: 'away', spot: 65 },
    ]
    expect(samePublisherSpotAcrossEnds.map(row => diagrammaticFieldX(row.spot))).toEqual([38, 38, 38, 38])
    expect(diagrammaticFieldX(0)).toBe(90)
    expect(diagrammaticFieldX(100)).toBe(10)
    expect(diagrammaticFieldX(null)).toBeNull()
  })
})

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
      if (url.startsWith('/api/nfl/pixel-red-zone/replay/')) return Promise.resolve(jsonResponse({
        mode: 'replay',
        game: {
          game_id: '401772829', date: '2025-09-07T17:00Z', status: 'replay',
          teams: {
            away: { team_id: '4', abbreviation: 'CIN', name: 'Cincinnati Bengals' },
            home: { team_id: '5', abbreviation: 'CLE', name: 'Cleveland Browns' },
          },
          score: { away: 17, home: 16 },
        },
        archive: { label: 'REPLAY', captured_at_utc: '2026-11-01T06:57:16Z', raw_fixture_sha256: 'fixture' },
        events: [{
          schema_version: 'lp-observed-nfl-event-v1', mode: 'replay', game_id: '401772829',
          source: { publisher: 'ESPN', event_id: '401772829:ESPN:play-1', play_id: 'play-1', revision: 'hash', occurred_at_utc: null, observed_at_utc: null },
          sequence: 1, period: 1, clock: '14:00', status: 'replay', offense_team_id: '5',
          before: { down: 1, yards_to_go: 10, yardline_100: 70, score: { away: 0, home: 0 } },
          after: { score: { away: 0, home: 0 } }, event_type: 'rush', source_event_type: 'Rush',
          scoring_play: false, is_turnover: false, review_state: 'none', display_text: 'Rush for 4 yards',
          confidence: { field: 'verified', score: 'verified' },
        }],
      }))
      if (url === '/api/nfl/game/nfl-1/playbyplay') return Promise.resolve(jsonResponse({
        available: true, publisher: 'ESPN', eventId: 'nfl-1', publisherUpdatedAt: '2026-11-01T07:00:00Z',
        periods: [{ label: 'Q2', plays: [{ playId: 'espn-play-42', sequenceNumber: 42, period: 2,
          clock: '08:21', type: 'Rush', text: 'Run up the middle for 6 yards.', wallclock: '2026-11-01T07:00:00Z' }] }],
      }))
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
    expect(result.container.querySelectorAll('.lp-hq-stage .lp-hq-object-label')).toHaveLength(6)
    const propCard = await screen.findByRole('button', { name: /player props from the desk computer/i })
    expect(propCard.textContent).toContain('Test Receiver')
    expect(propCard.textContent).toContain('OVER')
    expect(propCard.textContent).toMatch(/Oct 31,/)
    await screen.findByText(/No player projections published/i)
    await screen.findByText(/No upcoming matchup found/i)
    expect(await screen.findByText('LAC')).toBeTruthy()
    expect(screen.getByText('KC')).toBeTruthy()

    const tvCard = screen.getByRole('button', { name: /watch pixel red zone from the television/i })
    expect(tvCard.textContent).toContain('LAC')
    expect(tvCard.textContent).toContain('KC')
    fireEvent.click(tvCard)
    expect(await screen.findByRole('dialog', { name: 'Pixel Red Zone' })).toBeTruthy()
    expect(screen.getByText('NFL games in progress')).toBeTruthy()
    expect(screen.getByText(/LIVE · Q2/)).toBeTruthy()
    expect(await screen.findByText(/Run up the middle for 6 yards/)).toBeTruthy()
    expect(screen.getByText(/Source play espn-play-42/)).toBeTruthy()
    expect((global.fetch as jest.Mock).mock.calls.filter(([url]) => String(url).includes('/pixel-red-zone/replay/'))).toHaveLength(0)
    fireEvent.click(screen.getByRole('button', { name: 'Watch archived ESPN replay' }))
    expect(await screen.findByText(/Cincinnati Bengals at Cleveland Browns/)).toBeTruthy()
    expect(screen.getByText('REPLAY')).toBeTruthy()
    const redZoneDialog = screen.getByRole('dialog', { name: 'Historical game replay' })
    expect(redZoneDialog.getAttribute('aria-modal')).toBe('true')
    expect(document.body.style.overflow).toBe('hidden')
    expect(screen.getByRole('link', { name: 'Game details' }).getAttribute('href')).toBe('/game/nfl/401772829')
    expect(screen.getByRole('link', { name: 'NFL scores' }).getAttribute('href')).toBe('/scores?league=nfl')
    fireEvent.click(screen.getByRole('button', { name: 'Back to room' }))
    await waitFor(() => expect(screen.getByRole('button', { name: /watch pixel red zone from the television/i }).getAttribute('aria-expanded')).toBe('false'))
    expect(document.body.style.overflow).toBe('')
  })

  it('opens the desk computer prop preview with source time and actual player history', async () => {
    await renderRoom()

    const propCard = await screen.findByRole('button', { name: /player props from the desk computer/i })
    expect(propCard.textContent).toContain('Test Receiver')
    expect(propCard.textContent).toContain('OVER')
    expect(propCard.textContent).toMatch(/Oct 31,/)
    await screen.findByText(/No player projections published/i)
    await screen.findByText(/No upcoming matchup found/i)
    fireEvent.click(propCard)

    const propPreview = await screen.findByRole('region', { name: 'Player prop board' })
    expect(within(propPreview).getByText('Test Receiver')).toBeTruthy()
    expect(within(propPreview).getByText(/source time/)).toBeTruthy()
    expect(await within(propPreview).findByText('64')).toBeTruthy()
    expect(screen.getByRole('link', { name: /open full nfl prop board/i }).getAttribute('href')).toBe('/props?league=nfl')
  })

  it('labels career and arcade as future features without implying they work', async () => {
    await renderRoom()

    fireEvent.click(screen.getByRole('button', { name: /trophy shelf career status/i }))
    const careerPreview = screen.getByRole('region', { name: 'Career receipts' })
    expect(within(careerPreview).getByText(/career tracking is not available yet/i)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /arcade console future feature status/i }))
    const arcadePreview = screen.getByRole('region', { name: 'Arcade console' })
    expect(within(arcadePreview).getByText(/future destination.*no mini-game or rewards/i)).toBeTruthy()
  })
})
