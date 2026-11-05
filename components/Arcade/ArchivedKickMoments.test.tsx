import { act, render, screen } from '@testing-library/react'
import ArchivedKickMoments from './ArchivedKickMoments'

const originalFetch = global.fetch
const originalGtag = window.gtag

describe('ArchivedKickMoments', () => {
  afterEach(() => {
    global.fetch = originalFetch
    if (originalGtag) window.gtag = originalGtag
    else Reflect.deleteProperty(window, 'gtag')
  })

  it('labels historical source-backed kicks as archived and opens the exact challenge', async () => {
    const gtag = jest.fn()
    window.gtag = gtag
    global.fetch = jest.fn(async () => ({
      ok: true,
      json: async () => ({ moments: [{
        challenge_id: 'espn-fg-fixture',
        origin: 'observed_nfl_play',
        state: 'archived_verified',
        source_ref: {
          publisher: 'ESPN', game_id: '401772829', play_id: '4017728291916',
          event_id: '401772829:ESPN:4017728291916', source_revision: 'revision-1',
        },
        source_verified_at_utc: '2026-11-01T06:57:16Z',
        last_observed_at_utc: '2026-11-01T06:57:16Z',
        publisher_updated_at: '2026-11-01T06:56:00Z',
        observed_context: {
          away_team: 'Cincinnati Bengals', home_team: 'Cleveland Browns', period: 1,
          clock: '10:12', game_date: '2025-09-07T17:00Z', attempt_distance_yards: 45,
        },
      }] }),
    }) as Response)

    await act(async () => {
      render(<ArchivedKickMoments />)
      await new Promise(resolve => setTimeout(resolve, 0))
    })

    expect(screen.getByRole('heading', { name: 'Archived ESPN kicks' })).toBeTruthy()
    expect(screen.getByText(/45 yd · Cincinnati Bengals at Cleveland Browns/)).toBeTruthy()
    expect(screen.getByText(/Archived ESPN play/)).toBeTruthy()
    expect(screen.getByText(/LP observed Nov 1, 6:57 AM UTC/)).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Play kick' }).getAttribute('href'))
      .toBe('/arcade/nfl/field-goal/espn-fg-fixture')
    expect(gtag).toHaveBeenCalledWith('event', 'arcade_source_moments_snapshot', expect.objectContaining({
      surface: 'arcade_lobby', request_available: true, archive_available: true,
      live_moment_count: 0, archive_moment_count: 1,
    }))
    expect(JSON.stringify(gtag.mock.calls)).not.toContain('espn-fg-fixture')
    expect(JSON.stringify(gtag.mock.calls)).not.toContain('4017728291916')
  })

  it('reports live source freshness as aggregate age buckets only', async () => {
    const gtag = jest.fn()
    window.gtag = gtag
    const now = new Date().toISOString()
    global.fetch = jest.fn(async () => ({
      ok: true,
      json: async () => ({
        live_available: true,
        moments: [],
        live_moments: [{
          challenge_id: 'private-live-challenge',
          origin: 'observed_nfl_play',
          state: 'live_observed',
          source_ref: {
            publisher: 'ESPN', game_id: 'private-game', play_id: 'private-play',
            event_id: 'private-event', source_revision: 'private-revision',
          },
          source_verified_at_utc: now,
          last_observed_at_utc: now,
          publisher_updated_at: now,
          observed_context: {
            away_team: 'Away', home_team: 'Home', period: 1, clock: '10:00',
            game_date: now, attempt_distance_yards: 40,
          },
        }],
      }),
    }) as Response)

    await act(async () => {
      render(<ArchivedKickMoments compact />)
      await new Promise(resolve => setTimeout(resolve, 0))
    })

    expect(gtag).toHaveBeenCalledWith('event', 'arcade_source_moments_snapshot', expect.objectContaining({
      surface: 'nfl_hq', live_moment_count: 1, live_source_age_under_1m: 1,
      live_publisher_timestamp_known: 1,
    }))
    const analyticsPayloads = JSON.stringify(gtag.mock.calls)
    expect(analyticsPayloads).not.toContain('private-live-challenge')
    expect(analyticsPayloads).not.toContain('private-game')
    expect(analyticsPayloads).not.toContain('private-play')
  })

  it('shows fresh live kicks separately with their observed time', async () => {
    global.fetch = jest.fn(async () => ({
      ok: true,
      json: async () => ({
        live_available: true,
        live_moments: [{
          challenge_id: 'espn-fg-live',
          origin: 'observed_nfl_play',
          state: 'live_observed',
          source_ref: {
            publisher: 'ESPN', game_id: '401999001', play_id: 'live-play-1',
            event_id: '401999001:ESPN:live-play-1', source_revision: 'revision-live',
          },
          source_verified_at_utc: '2026-11-01T20:00:00Z',
          last_observed_at_utc: '2026-11-01T20:01:00Z',
          publisher_updated_at: '2026-11-01T20:00:30Z',
          observed_context: {
            away_team: 'Seattle Seahawks', home_team: 'Chicago Bears', period: 2,
            clock: '08:10', game_date: '2026-11-01T18:00Z', attempt_distance_yards: 45,
          },
        }],
        moments: [],
      }),
    }) as Response)

    await act(async () => {
      render(<ArchivedKickMoments />)
      await new Promise(resolve => setTimeout(resolve, 0))
    })

    expect(screen.getByRole('heading', { name: 'Live ESPN kicks' })).toBeTruthy()
    expect(screen.getByText(/LP observed Nov 1, 8:01 PM UTC/)).toBeTruthy()
    expect(screen.getByText(/ESPN summary updated Nov 1, 8:00 PM UTC/)).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Play kick' }).getAttribute('href'))
      .toBe('/arcade/nfl/field-goal/espn-fg-live')
    expect(screen.getByRole('heading', { name: 'Archived ESPN kicks' })).toBeTruthy()
  })

  it('refreshes visible live moments and stops polling while the tab is hidden', async () => {
    const originalVisibility = Object.getOwnPropertyDescriptor(document, 'visibilityState')
    let calls = 0
    jest.useFakeTimers()
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    global.fetch = jest.fn(async () => {
      calls += 1
      return {
        ok: true,
        json: async () => calls === 1 ? {
          live_available: true,
          live_moments: [{
            challenge_id: 'espn-fg-live', origin: 'observed_nfl_play', state: 'live_observed',
            source_ref: { publisher: 'ESPN', game_id: '401999001', play_id: 'p1',
              event_id: '401999001:ESPN:p1', source_revision: 'r1' },
            source_verified_at_utc: '2026-11-01T20:00:00Z',
            last_observed_at_utc: '2026-11-01T20:01:00Z', publisher_updated_at: null,
            observed_context: { away_team: 'Seattle Seahawks', home_team: 'Chicago Bears',
              period: 2, clock: '08:10', game_date: '2026-11-01T18:00Z', attempt_distance_yards: 45 },
          }],
          moments: [],
        } : { live_available: true, live_moments: [], moments: [] },
      } as Response
    })

    let view!: ReturnType<typeof render>
    try {
      await act(async () => {
        view = render(<ArchivedKickMoments />)
        await Promise.resolve()
      })
      expect(screen.getByRole('link', { name: 'Play kick' })).toBeTruthy()

      await act(async () => { await jest.advanceTimersByTimeAsync(60_000) })
      expect(calls).toBe(2)
      expect(screen.queryByRole('link', { name: 'Play kick' })).toBeNull()

      Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
      await act(async () => {
        document.dispatchEvent(new Event('visibilitychange'))
        await jest.advanceTimersByTimeAsync(120_000)
      })
      expect(calls).toBe(2)

      Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
      await act(async () => {
        document.dispatchEvent(new Event('visibilitychange'))
        await Promise.resolve()
      })
      expect(calls).toBe(3)
    } finally {
      view?.unmount()
      jest.useRealTimers()
      if (originalVisibility) Object.defineProperty(document, 'visibilityState', originalVisibility)
      else delete (document as Document & { visibilityState?: DocumentVisibilityState }).visibilityState
    }
  })
})
