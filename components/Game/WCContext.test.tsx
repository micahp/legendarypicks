import React from 'react'
import { act, render, screen } from '@testing-library/react'
import BoothFeed from './BoothFeed'
import WCContext from './WCContext'

jest.mock('../ListenLive', () => function MockListenLive() {
  return <div>Listen live</div>
})

const response = (body: unknown) => Promise.resolve({
  ok: true,
  json: () => Promise.resolve(body),
})

const baseContext = {
  headline: 'Argentina at Spain',
  status: "12'",
  teams: {
    away: { abbr: 'ARG', name: 'Argentina', form: 'WWWWW' },
    home: { abbr: 'ESP', name: 'Spain', form: 'WWWWW' },
  },
  top_scorers: [],
  insights: [],
  match_stats: [
    { key: 'possessionPct', label: 'Possession', unit: '%', away: '42', home: '58' },
  ],
  history: {
    teams: {
      ARG: {
        rest_days: 4,
        extra_time_matches: 2,
        extra_time_minutes: 60,
        matches: [{
          game_id: '760515', round: 'Semifinals', opponent: { abbr: 'ENG', name: 'England' },
          score_for: 2, score_against: 1, result: 'W',
        }],
      },
      ESP: {
        rest_days: 5,
        extra_time_matches: 0,
        extra_time_minutes: 0,
        matches: [{
          game_id: '760514', round: 'Semifinals', opponent: { abbr: 'FRA', name: 'France' },
          score_for: 2, score_against: 0, result: 'W',
        }],
      },
    },
  },
  social_sentiment: { status: 'unavailable' },
}

async function flushRequests() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()
  })
}

describe('WC live context polling', () => {
  const originalFetch = global.fetch

  beforeEach(() => {
    jest.useFakeTimers()
  })

  afterEach(() => {
    global.fetch = originalFetch
    jest.restoreAllMocks()
    jest.useRealTimers()
  })

  test('Game Context replaces the mounted snapshot after 30 seconds without loading flicker', async () => {
    const fetchMock = jest.fn()
      .mockImplementationOnce(() => response({
        ...baseContext,
        read: [{ headline: 'Opening read', evidence: 'ESPN/market: 0-0', source: 'fact' }],
      }))
      .mockImplementationOnce(() => response({
        ...baseContext,
        read: [{ headline: 'Live tactical update', evidence: 'Booth: Spain are stretching Argentina', source: 'booth' }],
      }))
    global.fetch = fetchMock as unknown as typeof fetch

    const { container, unmount } = render(<WCContext gameId="760517" />)
    await flushRequests()
    expect(screen.getByText('Opening read')).toBeTruthy()
    expect(screen.getByText('Route to this match')).toBeTruthy()
    expect(screen.getByText(/4d rest · 60 ET min/)).toBeTruthy()
    expect(screen.getByText(/Social sentiment omitted/)).toBeTruthy()

    await act(async () => {
      jest.advanceTimersByTime(30_000)
      await Promise.resolve()
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(screen.getByText('Live tactical update')).toBeTruthy()
    expect(container.querySelector('.animate-pulse')).toBeNull()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    unmount()
  })

  test('Game Context keeps the last good response on a failed background refresh and cleans up', async () => {
    const abortSpy = jest.spyOn(AbortController.prototype, 'abort')
    const clearSpy = jest.spyOn(global, 'clearInterval')
    const fetchMock = jest.fn()
      .mockImplementationOnce(() => response({
        ...baseContext,
        read: [{ headline: 'Keep this read', evidence: 'ESPN/market: 0-0', source: 'fact' }],
      }))
      .mockRejectedValueOnce(new Error('temporary network failure'))
    global.fetch = fetchMock as unknown as typeof fetch

    const { unmount } = render(<WCContext gameId="760517" />)
    await flushRequests()
    await act(async () => {
      jest.advanceTimersByTime(30_000)
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(screen.getByText('Keep this read')).toBeTruthy()
    unmount()
    expect(clearSpy).toHaveBeenCalled()
    expect(abortSpy).toHaveBeenCalled()
  })

  test('From the Booth swaps in the newest polled receipts and cleans up its request', async () => {
    const abortSpy = jest.spyOn(AbortController.prototype, 'abort')
    const fetchMock = jest.fn()
      .mockImplementationOnce(() => response({
        insights: [{
          id: 'old', tag: 'Tactical', subject: 'Spain', quote: 'Old quote long enough to render safely',
          strength: 2, ts: '2026-07-19T19:10:00Z', headline: 'Earlier booth read',
        }],
      }))
      .mockImplementationOnce(() => response({
        insights: [{
          id: 'new', tag: 'Tactical', subject: 'Spain', quote: 'New quote long enough to render safely',
          strength: 3, ts: '2026-07-19T19:18:00Z', headline: 'Newest booth read',
        }],
      }))
    global.fetch = fetchMock as unknown as typeof fetch

    const { unmount } = render(<BoothFeed gameId="760517" />)
    await flushRequests()
    expect(screen.getByText('Earlier booth read')).toBeTruthy()

    await act(async () => {
      jest.advanceTimersByTime(30_000)
      await Promise.resolve()
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(screen.getByText('Newest booth read')).toBeTruthy()
    expect(screen.queryByText('Earlier booth read')).toBeNull()
    unmount()
    expect(abortSpy).toHaveBeenCalled()
  })
})
