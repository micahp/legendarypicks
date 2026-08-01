import React from 'react'
import { render, screen } from '@testing-library/react'

import PlayerNews, { formatNewsDate, PlayerNewsResponse } from './PlayerNews'


const READY_RESPONSE: PlayerNewsResponse = {
  player_id: 7979,
  name: 'Jahmyr Gibbs',
  source: 'RotoWire',
  data_status: 'ready',
  message: null,
  source_updated_at: '2026-07-31T12:01:00-05:00',
  articles: [
    {
      id: 632221,
      source_player_id: '16808',
      headline: 'Newest update',
      notes: 'A verified player update.',
      analysis: 'Fantasy-specific analysis.',
      injury_status: 'QUESTIONABLE',
      injury_type: 'Back',
      injury_location: null,
      return_date: '2026-08-13',
      published: '2026-07-31T12:00:00-05:00',
      link: 'https://www.rotowire.com/football/player/jahmyr-gibbs-16808',
    },
  ],
}


function mockResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: async () => body,
  } as Response
}


describe('PlayerNews', () => {
  beforeEach(() => {
    ;(global as typeof globalThis & { fetch: jest.Mock }).fetch = jest.fn()
  })

  afterEach(() => {
    jest.restoreAllMocks()
    delete (global as Partial<typeof globalThis>).fetch
  })

  it('keeps a source date-only return date on the same calendar day', () => {
    expect(formatNewsDate('2026-08-13', false, 'en-US')).toBe('Aug 13')
  })

  it('renders attributed fantasy news and qualifies the estimated return date', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValue(mockResponse(READY_RESPONSE))

    render(<PlayerNews playerId={7979} />)

    expect(await screen.findByText('Newest update')).toBeTruthy()
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/player/7979/fantasy-news?limit=10',
      expect.objectContaining({ signal: expect.anything() }),
    )
    expect(screen.getByText('Fantasy Spin')).toBeTruthy()
    expect(screen.getByText('Estimated return: Aug 13')).toBeTruthy()
    expect(screen.getByText('Source: RotoWire')).toBeTruthy()
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('distinguishes a source outage from a player with no news', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValue(
      mockResponse({
        ...READY_RESPONSE,
        data_status: 'unavailable',
        message: 'Fantasy news is temporarily unavailable.',
        articles: [],
      }),
    )

    render(<PlayerNews playerId={7979} />)

    expect(await screen.findByText('Fantasy news unavailable')).toBeTruthy()
    expect(screen.queryByText('No recent fantasy news')).toBeNull()
  })

  it('renders an explicit request error instead of a blank panel', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValue(mockResponse({}, false, 503))

    render(<PlayerNews playerId={7979} compact />)

    expect(await screen.findByText('Fantasy news unavailable')).toBeTruthy()
  })

  it('labels stale articles without discarding the last validated feed', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValue(
      mockResponse({
        ...READY_RESPONSE,
        data_status: 'stale',
        message: 'Latest fantasy news refresh is delayed.',
      }),
    )

    render(<PlayerNews playerId={7979} />)

    expect(await screen.findByText('Latest fantasy news refresh is delayed.')).toBeTruthy()
    expect(screen.getByText('Newest update')).toBeTruthy()
  })
})
