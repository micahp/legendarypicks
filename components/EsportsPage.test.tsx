import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import EsportsPage from '../pages/esports'

/* The live broadcast + match board only. There is no EWC tournament-center payload anywhere in
 * this suite: the page must render live/non-EWC content and never fetch or render EWC elements. */

const liveWatch = {
  platform: 'youtube',
  url: 'https://www.youtube.com/watch?v=D4jmAm688f8',
  channel: null,
  embedUrl: 'https://www.youtube.com/embed/D4jmAm688f8',
  online: true,
  language: 'en',
  viewers: 18454,
  alternates: [],
}

const liveMatch = {
  startTime: Date.UTC(2026, 7, 8, 18, 0),
  endTime: null,
  live: true,
  finished: false,
  title: 'LoL',
  league: 'LEC — Summer 2026 (Regular Season)',
  teamA: 'G2 Esports',
  teamB: 'Karmine Corp',
  favorite: null,
  watch: liveWatch,
  streamKey: 'yt:D4jmAm688f8',
  eventId: 10756,
  prominence: 100,
}

const scheduledMatch = {
  ...liveMatch,
  startTime: Date.UTC(2026, 7, 8, 19, 0),
  live: false,
  teamA: 'Fnatic',
  teamB: 'Team Vitality',
  watch: null,
  streamKey: null,
}

function mockFetch(urls: Record<string, unknown>) {
  const fn = jest.fn((url: string) =>
    Promise.resolve({ json: () => Promise.resolve(urls[url]) }),
  )
  ;(global as any).fetch = fn
  return fn
}

describe('esports live board (post-correction)', () => {
  it('renders live non-EWC content and never fetches or renders the EWC tournament center', async () => {
    const fetchMock = mockFetch({
      '/api/esports/lol/msi/live': { live: false },
      '/api/esports/upcoming': { matches: [liveMatch, scheduledMatch] },
    })

    render(<EsportsPage />)

    // Non-EWC live content is not lost: the live broadcast and the scheduled slate render.
    await waitFor(() => expect(screen.getByText('G2 Esports')).toBeTruthy())
    expect(screen.getByText('Karmine Corp')).toBeTruthy()
    expect(screen.getByText('Fnatic')).toBeTruthy()
    expect(screen.getByText('Team Vitality')).toBeTruthy()

    // No tournament-center takeover: the board page never fetches the EWC endpoints…
    const calledUrls = fetchMock.mock.calls.map((c) => String(c[0]))
    expect(calledUrls).toContain('/api/esports/upcoming')
    expect(calledUrls).toContain('/api/esports/lol/msi/live')
    expect(calledUrls.some((u) => u.includes('/api/esports/events/ewc-2026'))).toBe(false)
    expect(calledUrls.some((u) => u.includes('/api/esports/titles'))).toBe(false)

    // …and never renders the EWC module header or the Club Championship rail.
    expect(screen.queryByText('EWC 2026')).toBeNull()
    expect(screen.queryByText('Club Championship')).toBeNull()
    expect(screen.queryByText('Standings unavailable')).toBeNull()
  })
})
