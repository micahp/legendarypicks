import React from 'react'
import { render, screen } from '@testing-library/react'
import GameCard from './GameCard'

jest.mock('next/router', () => ({
  useRouter: () => ({ push: jest.fn() }),
}))

const baseGame = {
  gameId: '401816542',
  league: 'MLB',
  homeTeam: { teamId: 'CHC', name: 'Chicago Cubs', score: 3 },
  awayTeam: { teamId: 'STL', name: 'St. Louis Cardinals', score: 7 },
  startTime: '2026-08-15T18:20:00Z',
  status: 'LIVE' as const,
}

// See lib/liveGameStatus.test.ts — the word LIVE is now reserved for the case
// where we know a game is live but cannot name its phase (Micah, 2026-08-17).
describe('GameCard live status', () => {
  it('shows the explicit live state and the publisher inning phase', () => {
    render(<GameCard {...baseGame} livePeriod={{ type: 'inning', number: 6, display: 'Top 6th', clock: '0:00' }} />)
    expect(screen.getByText('Top 6th')).toBeTruthy()
    expect(screen.queryByText('0:00')).toBeNull()
  })

  it('shows a quarter and clock for live football', () => {
    render(<GameCard {...baseGame} league="NFL" livePeriod={{ type: 'quarter', number: 4, clock: '1:51' }} />)
    expect(screen.getByText('Q4 · 1:51')).toBeTruthy()
  })
})
