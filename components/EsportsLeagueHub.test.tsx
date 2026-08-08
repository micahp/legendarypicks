import React from 'react'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import EsportsLeaguePage from '../pages/leagues/esports'

/* The complete Esports league destination at /leagues/esports: EWC tournament center, Club
 * Championship rail (honest states), title discovery, non-EWC context, responsive limits. */

const now = Date.now()

const ewcLive = {
  startTime: now,
  endTime: null,
  live: true,
  finished: false,
  title: 'Call of Duty',
  league: 'Esports World Cup',
  teamA: 'Team Falcons',
  teamB: 'Gentle Mates',
  favorite: null,
  watch: {
    platform: 'youtube',
    url: 'https://www.youtube.com/watch?v=abc123',
    channel: null,
    embedUrl: 'https://www.youtube.com/embed/abc123',
    online: true,
    alternates: [],
  },
  streamKey: 'yt:abc123',
  eventId: 10834,
  prominence: 100,
  ewcEventId: 'ewc-2026',
}

const ewcUpcoming = {
  startTime: now + 60 * 60 * 1000, // today, so the module titles the block "Today across titles"
  endTime: null,
  live: false,
  finished: false,
  title: 'CS2',
  league: 'Esports World Cup',
  teamA: 'Natus Vincere',
  teamB: 'Virtus.pro',
  favorite: null,
  watch: null,
  ewcEventId: 'ewc-2026',
}

const ewcCompleted = {
  startTime: now - 2 * 60 * 60 * 1000,
  endTime: now - 60 * 60 * 1000,
  live: false,
  finished: true,
  winner: 'a' as const,
  score: { a: 3, b: 1 },
  title: 'Call of Duty',
  league: 'Esports World Cup',
  teamA: 'G2 Esports',
  teamB: 'Team Heretics',
  favorite: null,
  watch: null,
  ewcEventId: 'ewc-2026',
}

const projection = {
  eventId: 'ewc-2026',
  eventName: 'Esports World Cup 2026',
  active: true,
  asOf: new Date().toISOString(),
  matches: { live: [ewcLive], upcoming: [ewcUpcoming], completed: [ewcCompleted] },
}

const standingsRows = [
  { rank: 1, clubId: 'team-falcons', clubName: 'Team Falcons', logo: null, points: 2600, eligibleTopEightCount: null, titleWins: null, eligibleToWin: null, movement: null },
  { rank: 2, clubId: 'twisted-minds', clubName: 'Twisted Minds', logo: null, points: 1400, eligibleTopEightCount: null, titleWins: null, eligibleToWin: null, movement: null },
  { rank: 3, clubId: 'team-spirit', clubName: 'Team Spirit', logo: null, points: 1200, eligibleTopEightCount: null, titleWins: null, eligibleToWin: null, movement: null },
]

const standings = (status: 'current' | 'stale' | 'unavailable' = 'current') => ({
  event: 'ewc-2026',
  status,
  asOf: status === 'unavailable' ? null : '2026-08-08T12:00:00+00:00',
  source: status === 'unavailable' ? null : { label: 'EWC Official', url: 'https://example.invalid' },
  standings: status === 'unavailable' ? [] : standingsRows,
})

const titles = {
  titles: [
    { slug: 'call-of-duty', label: 'Call of Duty', match_count: 3, live_count: 1, result_count: 5, next_start: 1786215600000 },
    { slug: 'league-of-legends', label: 'LoL', match_count: 2, live_count: 0, result_count: 7, next_start: 1786220000000 },
    { slug: 'counter-strike-2', label: 'CS2', match_count: 0, live_count: 0, result_count: 4, next_start: null },
  ],
}

function mockMatchMedia(matches: boolean) {
  const mq = {
    matches,
    media: '(min-width: 1024px)',
    onchange: null,
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
    addListener: jest.fn(),
    removeListener: jest.fn(),
    dispatchEvent: jest.fn(),
  }
  ;(window as any).matchMedia = jest.fn().mockReturnValue(mq)
  return mq
}

type FetchBehavior = Record<string, () => Promise<{ json: () => Promise<unknown> }>>

// Drain pending fetch resolutions so a late setState never fires after the test body
// (React's "update not wrapped in act" warning).
async function flush() {
  await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}

function mockFetch(respond: (url: string) => unknown) {
  const fn = jest.fn((url: string) => {
    const value = respond(String(url))
    if (value instanceof Error) return Promise.reject(value)
    return Promise.resolve({ json: () => Promise.resolve(value) })
  })
  ;(global as any).fetch = fn
  return fn
}

function renderHub(desktop = true, respond?: (url: string) => unknown) {
  mockMatchMedia(desktop)
  const fetchMock = mockFetch(respond ?? ((url: string) => {
    if (url.includes('/club-standings')) return standings()
    if (url === '/api/esports/titles') return titles
    return projection
  }))
  render(<EsportsLeaguePage />)
  return fetchMock
}

describe('esports league hub — complete product (desktop)', () => {
  it('renders header, EWC tournament center, Club Championship rail, title discovery, and non-EWC context', async () => {
    const fetchMock = renderHub(true)

    // League-style header + breadcrumb + live-board link
    expect(screen.getByText('Leagues').closest('a')?.getAttribute('href')).toBe('/leagues')
    expect(screen.getByRole('heading', { name: 'Esports' })).toBeTruthy()
    expect(screen.getByText('Live esports →').closest('a')?.getAttribute('href')).toBe('/esports')

    // EWC tournament center — event focus, live, today, results
    await waitFor(() => expect(screen.getByText('EWC 2026')).toBeTruthy())
    expect(screen.getByText('Esports World Cup 2026')).toBeTruthy()
    // Team Falcons appears in both the live match and the rail — both must render.
    expect(screen.getAllByText('Team Falcons').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('Gentle Mates')).toBeTruthy()
    expect(screen.getByText('Natus Vincere')).toBeTruthy()
    expect(screen.getByText('Today across titles')).toBeTruthy()
    expect(screen.getByText('EWC results')).toBeTruthy()
    expect(screen.getByText('G2 Esports')).toBeTruthy()

    // Club Championship rail — rows, tabular points, source
    expect(screen.getByText('Club Championship')).toBeTruthy()
    expect(screen.getByText('Twisted Minds')).toBeTruthy()
    expect(screen.getByText('2600')).toBeTruthy()
    expect(screen.getByText('EWC Official')).toBeTruthy()

    // Desktop requests ten rows; the rail is expanded so no expand action shows.
    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes('club-standings?limit=10'))).toBe(true)
    expect(screen.queryByText('Show full top ten →')).toBeNull()

    // Title discovery — pills to title desks and picks
    expect(screen.getByText('All esports titles')).toBeTruthy()
    expect(screen.getByText('Call of Duty').closest('a')?.getAttribute('href')).toBe('/esports/call-of-duty')
    expect(screen.getByText('LoL').closest('a')?.getAttribute('href')).toBe('/esports/league-of-legends')
    const picksLinks = screen.getAllByText('Picks').map((el) => el.closest('a')?.getAttribute('href'))
    expect(picksLinks).toContain('/predict?title=call-of-duty')
    expect(picksLinks).toContain('/predict?title=league-of-legends')

    // Broader non-EWC context — the live board stays reachable
    expect(screen.getByText('Live board →').closest('a')?.getAttribute('href')).toBe('/esports')
    expect(screen.getByText('Make Picks →').closest('a')?.getAttribute('href')).toBe('/predict')
    await flush()
  })
})

describe('esports league hub — responsive standings limit', () => {
  it('mobile requests five rows and expands to ten on demand', async () => {
    const fetchMock = renderHub(false)

    await waitFor(() => expect(screen.getByText('Club Championship')).toBeTruthy())
    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes('club-standings?limit=5'))).toBe(true)

    // Collapsed mobile rail offers the bounded follow-up to ten.
    const expand = screen.getByText('Show full top ten →')
    fireEvent.click(expand)

    await waitFor(() => expect(fetchMock.mock.calls.some((c) => String(c[0]).includes('club-standings?limit=10'))).toBe(true))
    expect(screen.queryByText('Show full top ten →')).toBeNull()
    await flush()
  })
})

describe('esports league hub — data states', () => {
  it('renders the honest unavailable Club Championship state', async () => {
    renderHub(true, (url) => {
      if (url.includes('/club-standings')) return standings('unavailable')
      if (url === '/api/esports/titles') return titles
      return projection
    })
    await waitFor(() => expect(screen.getByText('Standings unavailable')).toBeTruthy())
    // No rail rows — the rail must not render club names or points.
    expect(screen.queryByText('Twisted Minds')).toBeNull()
    expect(screen.queryByText('2600')).toBeNull()
    await flush()
  })

  it('shows a visible stale badge without a tooltip', async () => {
    renderHub(true, (url) => {
      if (url.includes('/club-standings')) return standings('stale')
      if (url === '/api/esports/titles') return titles
      return projection
    })
    await waitFor(() => expect(screen.getByText('Stale')).toBeTruthy())
    await flush()
  })

  it('renders an error card with retry when the projection fails, then recovers', async () => {
    let failing = true
    const fetchMock = mockFetch((url) => {
      if (url === '/api/esports/events/ewc-2026' && failing) return new Error('boom')
      if (url.includes('/club-standings')) return standings()
      if (url === '/api/esports/titles') return titles
      return projection
    })
    mockMatchMedia(true)
    render(<EsportsLeaguePage />)

    await waitFor(() => expect(screen.getByText(/Couldn't load the EWC tournament center/)).toBeTruthy())

    failing = false
    fireEvent.click(screen.getByText('Retry'))
    await waitFor(() => expect(screen.getByText('EWC 2026')).toBeTruthy())
    expect(fetchMock.mock.calls.filter((c) => String(c[0]) === '/api/esports/events/ewc-2026').length).toBeGreaterThanOrEqual(2)
    await flush()
  })

  it('shows an honest empty state when the EWC event has no matches', async () => {
    renderHub(true, (url) => {
      if (url === '/api/esports/events/ewc-2026') {
        return { eventId: 'ewc-2026', eventName: 'Esports World Cup 2026', active: false, asOf: null, matches: { live: [], upcoming: [], completed: [] } }
      }
      if (url.includes('/club-standings')) return standings()
      if (url === '/api/esports/titles') return titles
      return projection
    })
    await waitFor(() => expect(screen.getByText(/No active EWC 2026 matches right now/)).toBeTruthy())
    expect(screen.queryByText('EWC 2026')).toBeNull()
    await flush()
  })

  it('shows a quiet note when the title directory is unavailable', async () => {
    renderHub(true, (url) => {
      if (url === '/api/esports/titles') return new Error('titles down')
      if (url.includes('/club-standings')) return standings()
      return projection
    })
    await waitFor(() => expect(screen.getByText(/title directory is unavailable/)).toBeTruthy())
    await flush()
  })
})
