import React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import TennisModelTab from './TennisModelTab'

const today = new Date()
const localDate = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`
const startToday = `${localDate}T12:00:00.000Z`
const startUpcoming = new Date(Date.now() + 36 * 60 * 60 * 1000).toISOString()

const projection = {
  probability: 0.7, projectedWinner: 'Home Player', homeAces: 5, awayAces: 3,
  homeDoubleFaults: 2, awayDoubleFaults: 4, totalGames: 23.5,
  totalGamesInterval: [19, 29] as [number, number], modelVersion: 'page-v1',
}

const odds = {
  matchWinner: { home: -150, away: 130 },
  totalGames: { line: 22.5, over: -110, under: -110 },
  capturedAt: '2026-10-17T11:45:00Z',
}

function match(overrides: Record<string, unknown> = {}) {
  return {
    gameId: 'match-1', tour: 'atp' as const, event: 'Test Open', round: 'Final',
    startTime: startUpcoming, status: 'scheduled' as const, home: 'Home Player', away: 'Away Player',
    projection, odds, result: null,
    grades: { winner: null, homeAcesError: null, awayAcesError: null, totalGamesError: null },
    preview: true, lockStatus: 'preview' as const,
    ...overrides,
  }
}

function apiPayload(matches: ReturnType<typeof match>[], overrides: Record<string, unknown> = {}) {
  return { available: true, reason: null, winnerModel: 'page', winnerModelReason: null,
    accuracy: { winnerBrier: null, brierN: 0 },
    source: 'test', matches, ...overrides }
}

function respond(payload: unknown) {
  ;(global as any).fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(payload) }))
}

describe('Tennis model tab parity', () => {
  it('shows a loading state while the model request is pending', () => {
    ;(global as any).fetch = jest.fn(() => new Promise(() => {}))
    const { container } = render(<TennisModelTab tour="atp" />)
    expect(container.querySelector('.animate-pulse')).toBeTruthy()
  })

  it('shows request errors and an unavailable payload honestly', async () => {
    ;(global as any).fetch = jest.fn(() => Promise.resolve({ ok: false, status: 503 }))
    const errorView = render(<TennisModelTab tour="atp" />)
    expect((await screen.findByRole('alert')).textContent).toContain('HTTP 503')
    errorView.unmount()

    respond({ available: false, reason: 'No verified matches.', matches: [] })
    render(<TennisModelTab tour="wta" />)
    expect(await screen.findByText('No verified matches.')).toBeTruthy()
  })

  it('keeps a future preview separate and reports settled winner Brier with its sample count', async () => {
    respond(apiPayload([
      match(),
      match({
        gameId: 'settled-1', status: 'final', preview: false, lockStatus: 'locked',
        startTime: startToday, lockedAt: '2026-10-17T11:00:00Z', frozenOdds: odds,
        grades: { winner: 'correct', winnerBrier: 0.09, homeAcesError: null, awayAcesError: null, totalGamesError: 1 },
        result: { winner: 'Home Player', homeAces: null, awayAces: null, totalGames: 24, sets: { home: [6, 6], away: [4, 4] } },
      }),
    ], { accuracy: { winnerBrier: 0.09, brierN: 1 } }))
    render(<TennisModelTab tour="atp" />)

    expect(await screen.findByRole('heading', { name: 'Away Player at Home Player' })).toBeTruthy()
    expect(screen.getByText('Preview · not locked')).toBeTruthy()
    expect(document.body.textContent).toContain('Current line · Bovada -150')
    expect(document.body.textContent).toContain('Bovada captured 2026-10-17T11:45:00Z')

    fireEvent.click(screen.getByRole('button', { name: 'Model accuracy' }))
    expect(screen.getByText('0.0900')).toBeTruthy()
    expect(screen.getByText('Brier n')).toBeTruthy()
    expect(screen.getByText('1', { selector: 'dd' })).toBeTruthy()
    expect(screen.getByText(/0.2500 is a constant 50% forecast/)).toBeTruthy()
  })

  it('shows frozen quote provenance and explicitly marks historical locks without a quote', async () => {
    const finalMatch = (gameId: string, frozenOdds: unknown) => match({
      gameId, status: 'final', preview: false, lockStatus: 'locked', lockedAt: '2026-10-17T11:00:00Z',
      frozenOdds,
      grades: { winner: 'incorrect', winnerBrier: 0.49, homeAcesError: null, awayAcesError: null, totalGamesError: null },
      result: { winner: 'Away Player', homeAces: null, awayAces: null, totalGames: 20, sets: { home: [4, 5], away: [6, 7] } },
    })
    respond(apiPayload([finalMatch('with-quote', odds), finalMatch('legacy-lock', null)], {
      accuracy: { winnerBrier: 0.49, brierN: 2 },
    }))
    render(<TennisModelTab tour="atp" />)
    fireEvent.click(await screen.findByRole('button', { name: 'Record' }))

    await waitFor(() => expect(document.body.textContent).toContain('No frozen sportsbook line was recorded for this forecast.'))
    expect(document.body.textContent).toContain('Frozen line · Bovada -150')
    expect(document.body.textContent).toContain('Bovada captured 2026-10-17T11:45:00Z')
    expect(document.body.textContent).toContain('No frozen sportsbook line was recorded for this forecast.')
    fireEvent.click(screen.getByRole('button', { name: 'Model accuracy' }))
    expect(screen.getByText('0.4900')).toBeTruthy()
    expect(screen.getByText('2', { selector: 'dd' })).toBeTruthy()
  })

  it('keeps completed, live, and overdue matches off Projections even when no grade exists', async () => {
    const finalWithoutGrade = match({
      gameId: 'shanghai-final', home: 'Alejandro Davidovich Fokina', away: 'Rafael Jodar',
      startTime: new Date().toISOString(), status: 'final', preview: false,
      lockedAt: '2026-10-17T11:00:00Z', lockStatus: 'locked', grades: null,
      result: { winner: 'Rafael Jodar', homeAces: null, awayAces: null,
        totalGames: 20, sets: { home: [1, 7], away: [6, 6] } },
    })
    const liveWithoutGrade = match({
      gameId: 'live-1', home: 'Live Player', status: 'live', grades: null,
    })
    const overdueScheduled = match({
      gameId: 'overdue-1', home: 'Overdue Player',
      startTime: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
      status: 'scheduled', lockStatus: 'missed', grades: null,
    })
    respond(apiPayload([finalWithoutGrade, liveWithoutGrade, overdueScheduled, match()]))
    render(<TennisModelTab tour="atp" />)

    expect(await screen.findByRole('heading', { name: 'Away Player at Home Player' })).toBeTruthy()
    expect(screen.queryByText('Rafael Jodar at Alejandro Davidovich Fokina')).toBeNull()
    expect(screen.queryByText('Away Player at Live Player')).toBeNull()
    expect(screen.queryByText('Away Player at Overdue Player')).toBeNull()
    expect(screen.queryByText('Final')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Record' }))
    expect(await screen.findByText('Rafael Jodar at Alejandro Davidovich Fokina')).toBeTruthy()
    expect(screen.getByText('Final')).toBeTruthy()
  })

  it('shows finalized missed-lock matches in Record rather than Projections', async () => {
    const missed = match({
      gameId: 'missed-1', startTime: new Date().toISOString(), status: 'final',
      projection: null, odds: null, preview: false, lockStatus: 'missed',
      grades: null,
      result: { winner: 'Away Player', homeAces: null, awayAces: null, totalGames: 20, sets: null },
    })
    respond(apiPayload([missed]))
    render(<TennisModelTab tour="atp" />)
    await waitFor(() => expect(screen.getByText('No ungraded projections are available.')).toBeTruthy())
    expect(screen.queryByText('Missed lock window')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Record' }))
    expect(await screen.findByText('Missed lock window')).toBeTruthy()
    expect(screen.getByText('No projection is available.')).toBeTruthy()
  })

  it('shows an explicit empty state when the selected slate has no matches', async () => {
    respond(apiPayload([]))
    render(<TennisModelTab tour="atp" />)
    await waitFor(() => expect(screen.getByText('No ungraded projections are available.')).toBeTruthy())
  })
})
