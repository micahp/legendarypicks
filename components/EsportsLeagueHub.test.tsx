import React from 'react'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import EsportsLeaguePage from '../pages/leagues/esports'

/* The complete Esports league destination at /leagues/esports: EWC-first tournament center,
 * inline all-esports board from /api/esports/upcoming, tabs, interactive title filtering,
 * Club Championship honest states, and the responsive standings limit. */

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
  startTime: now + 60 * 60 * 1000,
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

// The broader all-esports board (shared /api/esports/upcoming contract): a non-EWC live LoL
// broadcast, an upcoming LoL match, an upcoming Call of Duty match, and a finished LoL match.
const boardLive = {
  startTime: now,
  endTime: null,
  live: true,
  finished: false,
  title: 'LoL',
  league: 'LEC — Summer 2026 (Regular Season)',
  teamA: 'G2 Esports',
  teamB: 'Karmine Corp',
  favorite: null,
  watch: {
    platform: 'youtube',
    url: 'https://www.youtube.com/watch?v=D4jmAm688f8',
    channel: null,
    embedUrl: 'https://www.youtube.com/embed/D4jmAm688f8',
    online: true,
    alternates: [],
  },
  streamKey: 'yt:D4jmAm688f8',
  eventId: 10756,
  prominence: 100,
}

const boardUpcomingLol = {
  startTime: now + 2 * 60 * 60 * 1000,
  endTime: null,
  live: false,
  finished: false,
  title: 'LoL',
  league: 'LEC — Summer 2026 (Regular Season)',
  teamA: 'Fnatic',
  teamB: 'Team Vitality',
  favorite: null,
  watch: null,
}

const boardUpcomingCod = {
  startTime: now + 3 * 60 * 60 * 1000,
  endTime: null,
  live: false,
  finished: false,
  title: 'Call of Duty',
  league: 'CDL Championship',
  teamA: 'FaZe Clan',
  teamB: 'OpTic Gaming',
  favorite: null,
  watch: null,
}

const boardResult = {
  startTime: now - 3 * 60 * 60 * 1000,
  endTime: now - 2 * 60 * 60 * 1000,
  live: false,
  finished: true,
  winner: 'a' as const,
  score: { a: 2, b: 1 },
  title: 'LoL',
  league: 'LEC — Summer 2026 (Regular Season)',
  teamA: 'T1',
  teamB: 'Gen.G',
  favorite: null,
  watch: null,
}

const upcoming = {
  source: 'fixture',
  matches: [boardLive, boardUpcomingLol, boardUpcomingCod, boardResult],
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
    { slug: 'league-of-legends', label: 'LoL', match_count: 2, live_count: 1, result_count: 7, next_start: 1786220000000 },
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

function mockFetch(respond: (url: string) => unknown) {
  const fn = jest.fn((url: string) => {
    const value = respond(String(url))
    if (value instanceof Error) return Promise.reject(value)
    return Promise.resolve({ json: () => Promise.resolve(value) })
  })
  ;(global as any).fetch = fn
  return fn
}

function defaultRespond(url: string): unknown {
  if (url === '/api/esports/upcoming') return upcoming
  if (url.includes('/club-standings')) return standings()
  if (url === '/api/esports/titles') return titles
  return projection
}

function renderHub(desktop = true, respond?: (url: string) => unknown) {
  mockMatchMedia(desktop)
  const fetchMock = mockFetch(respond ?? defaultRespond)
  render(<EsportsLeaguePage />)
  return fetchMock
}

async function flush() {
  await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}

describe('esports league hub — header and EWC-first center', () => {
  it('renders the league header, EWC tournament center, and Club Championship rail by default', async () => {
    const fetchMock = renderHub(true)

    expect(screen.getByText('Leagues').closest('a')?.getAttribute('href')).toBe('/leagues')
    expect(screen.getByRole('heading', { name: 'Esports' })).toBeTruthy()
    expect(screen.getByText('Live esports →').closest('a')?.getAttribute('href')).toBe('/esports')

    // EWC tournament center (default tab) — event focus, live, today, results.
    await waitFor(() => expect(screen.getByText('EWC 2026')).toBeTruthy())
    expect(screen.getByText('Esports World Cup 2026')).toBeTruthy()
    expect(screen.getAllByText('Team Falcons').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('Gentle Mates')).toBeTruthy()
    expect(screen.getByText('Today across titles')).toBeTruthy()
    expect(screen.getByText('EWC results')).toBeTruthy()
    expect(screen.getByText('G2 Esports')).toBeTruthy()

    // Club Championship rail — rows, tabular points, source; desktop requests ten rows.
    expect(screen.getByText('Club Championship')).toBeTruthy()
    expect(screen.getByText('Twisted Minds')).toBeTruthy()
    expect(screen.getByText('2600')).toBeTruthy()
    expect(screen.getByText('EWC Official')).toBeTruthy()
    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes('club-standings?limit=10'))).toBe(true)
    expect(screen.queryByText('Show full top ten →')).toBeNull()
    await flush()
  })
})

describe('esports league hub — inline all-esports board from /api/esports/upcoming', () => {
  it('renders live, upcoming, and results content inline (not a link card)', async () => {
    renderHub(true)

    // Live & Upcoming tab: the shared LiveNow player + day-grouped schedule rows.
    fireEvent.click(screen.getByRole('button', { name: 'Live & Upcoming' }))
    await waitFor(() => expect(screen.getByText('G2 Esports')).toBeTruthy())
    expect(screen.getByText('Karmine Corp')).toBeTruthy()
    expect(screen.getByText('Fnatic')).toBeTruthy()
    expect(screen.getByText('Team Vitality')).toBeTruthy()
    expect(screen.getByText('FaZe Clan')).toBeTruthy()
    expect(screen.getByText('Upcoming matches')).toBeTruthy()

    // Results tab: finished matches render inline with scores.
    fireEvent.click(screen.getByRole('button', { name: 'Results' }))
    await waitFor(() => expect(screen.getByText('T1')).toBeTruthy())
    expect(screen.getByText('Gen.G')).toBeTruthy()
    expect(screen.getByText('Recent results')).toBeTruthy()
    await flush()
  })

  it('renders loading, error+retry, and empty states for the board', async () => {
    const fetchMock = mockFetch((url) => {
      if (url === '/api/esports/upcoming') return new Error('board down')
      return defaultRespond(url)
    })
    mockMatchMedia(true)
    render(<EsportsLeaguePage />)
    fireEvent.click(screen.getByRole('button', { name: 'Live & Upcoming' }))
    await waitFor(() => expect(screen.getByText(/Couldn't load the esports board/)).toBeTruthy())
    expect(screen.queryByText('G2 Esports')).toBeNull()
    await flush()
  })
})

describe('esports league hub — Games tab tracks the complete EWC population', () => {
  it('renders every EWC live, upcoming, and completed match without generic-board games', async () => {
    renderHub(true)
    fireEvent.click(screen.getByRole('button', { name: 'Games' }))
    await waitFor(() => expect(screen.getByText('3 games · 2 titles')).toBeTruthy())
    expect(screen.getByText('Gentle Mates')).toBeTruthy()
    expect(screen.getByText('Natus Vincere')).toBeTruthy()
    expect(screen.getByText('Virtus.pro')).toBeTruthy()
    expect(screen.getByText('G2 Esports')).toBeTruthy()
    expect(screen.getByText('Team Heretics')).toBeTruthy()
    expect(screen.getByText('Live now')).toBeTruthy()
    expect(screen.getByText('Upcoming')).toBeTruthy()
    expect(screen.getByText('Finals')).toBeTruthy()
    expect(screen.getAllByText('LIVE').length).toBeGreaterThan(0)
    expect(screen.getAllByText('FINAL').length).toBeGreaterThan(0)

    // Generic-board-only matches must not leak into the EWC tracker.
    expect(screen.queryByText('Karmine Corp')).toBeNull()
    expect(screen.queryByText('Fnatic')).toBeNull()
    expect(screen.queryByText('FaZe Clan')).toBeNull()
    await flush()
  })

  it('filters the complete EWC population by represented title and clears', async () => {
    renderHub(true)
    fireEvent.click(screen.getByRole('button', { name: 'Games' }))
    await waitFor(() => expect(screen.getByText('3 games · 2 titles')).toBeTruthy())

    fireEvent.click(screen.getByRole('button', { name: /Call of Duty 2/ }))
    await waitFor(() => expect(screen.getByText(/Showing only Call of Duty/)).toBeTruthy())
    expect(screen.getByText('2 of 3 games')).toBeTruthy()
    expect(screen.getByText('Gentle Mates')).toBeTruthy()
    expect(screen.getByText('G2 Esports')).toBeTruthy()
    expect(screen.queryByText('Natus Vincere')).toBeNull()
    expect(screen.queryByText('Virtus.pro')).toBeNull()

    fireEvent.click(screen.getByText('Clear filter ×'))
    await waitFor(() => expect(screen.getByText('Natus Vincere')).toBeTruthy())
    expect(screen.getByText('3 games · 2 titles')).toBeTruthy()
    expect(screen.queryByText(/Showing only Call of Duty/)).toBeNull()
    await flush()
  })
})

describe('esports league hub — picks tab', () => {
  it('links to the picks board and each title picks desk', async () => {
    renderHub(true)
    fireEvent.click(screen.getByRole('button', { name: 'Picks' }))
    await waitFor(() => expect(screen.getByText('Open the picks board')).toBeTruthy())
    expect(screen.getByText('Open the picks board').closest('a')?.getAttribute('href')).toBe('/predict')
    // Title pick pills are data-dependent — wait for them.
    await waitFor(() => expect(screen.getAllByText(/picks →/).length).toBeGreaterThan(0))
    const links = screen.getAllByText(/picks →/).map((el) => el.closest('a')?.getAttribute('href'))
    expect(links).toContain('/predict?title=call-of-duty')
    expect(links).toContain('/predict?title=league-of-legends')
    await flush()
  })
})

describe('esports league hub — responsive standings limit', () => {
  it('mobile requests five rows and expands to ten on demand', async () => {
    const fetchMock = renderHub(false)

    await waitFor(() => expect(screen.getByText('Club Championship')).toBeTruthy())
    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes('club-standings?limit=5'))).toBe(true)

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
      return defaultRespond(url)
    })
    await waitFor(() => expect(screen.getByText('Standings unavailable')).toBeTruthy())
    expect(screen.queryByText('Twisted Minds')).toBeNull()
    expect(screen.queryByText('2600')).toBeNull()
    await flush()
  })

  it('shows a visible stale badge without a tooltip', async () => {
    renderHub(true, (url) => {
      if (url.includes('/club-standings')) return standings('stale')
      return defaultRespond(url)
    })
    await waitFor(() => expect(screen.getByText('Stale')).toBeTruthy())
    await flush()
  })

  it('renders an error card with retry when the projection fails, then recovers', async () => {
    let failing = true
    const fetchMock = mockFetch((url) => {
      if (url === '/api/esports/events/ewc-2026' && failing) return new Error('boom')
      return defaultRespond(url)
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
      return defaultRespond(url)
    })
    await waitFor(() => expect(screen.getByText(/No active EWC 2026 matches right now/)).toBeTruthy())
    expect(screen.queryByText('EWC 2026')).toBeNull()
    await flush()
  })

  it('keeps the complete EWC Games tracker available when the title directory is unavailable', async () => {
    renderHub(true, (url) => {
      if (url === '/api/esports/titles') return new Error('titles down')
      return defaultRespond(url)
    })
    fireEvent.click(screen.getByRole('button', { name: 'Games' }))
    await waitFor(() => expect(screen.getByText('3 games · 2 titles')).toBeTruthy())
    expect(screen.getByRole('button', { name: /Call of Duty 2/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /CS2 1/ })).toBeTruthy()
    await flush()
  })
})
