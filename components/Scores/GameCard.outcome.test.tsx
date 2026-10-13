import React from 'react'
import { render, screen } from '@testing-library/react'
import GameCard from './GameCard'

jest.mock('next/router', () => ({
  useRouter: () => ({ push: jest.fn() }),
}))

// Every final says HOW it ended (TASK-scoreboard-outcomes-and-homepage.md):
// a final with no score shows the method of victory in the score slot, and
// the badge says the non-score endings (retirement, shootout) instead of a
// plain FINAL.
describe('GameCard method of victory', () => {
  it('shows the UFC finish in the score slot on the winner line', () => {
    render(<GameCard
      gameId="600059185"
      league="UFC"
      homeTeam={{ teamId: 'J. Wells', name: 'Jeremiah Wells', winner: true }}
      awayTeam={{ teamId: 'M. Orolbai', name: 'Myktybek Orolbai', winner: false }}
      startTime="2026-08-16T01:00:00Z"
      status="FINAL"
      statusDetail="Final"
      outcomeMethod="Submission"
      outcomeRound={3}
      outcomeClock="1:24"
    />)
    expect(screen.getByText('SUB · R3 1:24')).toBeTruthy()
  })

  it('shows KO/TKO and Decision labels too', () => {
    const { unmount } = render(<GameCard
      gameId="600060733"
      league="UFC"
      homeTeam={{ teamId: 'R. Puga', name: 'Roman Puga', winner: true }}
      awayTeam={{ teamId: 'T. Trembley', name: 'Taner Trembley', winner: false }}
      startTime="2026-08-19T00:00:00Z"
      status="FINAL"
      outcomeMethod="KO/TKO"
      outcomeRound={1}
      outcomeClock="0:39"
    />)
    expect(screen.getByText('KO/TKO · R1 0:39')).toBeTruthy()
    unmount()
    render(<GameCard
      gameId="x"
      league="UFC"
      homeTeam={{ teamId: 'I. Makhachev', name: 'Islam Makhachev', winner: true }}
      awayTeam={{ teamId: 'I. M. Garry', name: 'Ian Machado Garry', winner: false }}
      startTime="2026-08-16T01:00:00Z"
      status="FINAL"
      outcomeMethod="Decision"
      outcomeRound={5}
      outcomeClock="5:00"
    />)
    expect(screen.getByText('DEC · R5 5:00')).toBeTruthy()
  })

  it('renders no method when the publisher does not say', () => {
    render(<GameCard
      gameId="x"
      league="UFC"
      homeTeam={{ teamId: 'A', name: 'Fighter A', winner: true }}
      awayTeam={{ teamId: 'B', name: 'Fighter B', winner: false }}
      startTime="2026-08-16T01:00:00Z"
      status="FINAL"
    />)
    expect(screen.queryByText(/· R\d/)).toBeNull()
    expect(screen.queryByText(/SUB|KO|DEC/)).toBeNull()
  })

  it('labels a tennis retirement RETIRED instead of FINAL', () => {
    render(<GameCard
      gameId="x"
      league="ATP"
      homeTeam={{ teamId: 'A', name: 'Player A', score: 2 }}
      awayTeam={{ teamId: 'B', name: 'Player B', score: 0 }}
      startTime="2026-08-13T12:00:00Z"
      status="FINAL"
      statusDetail="Retired"
    />)
    expect(screen.getByText('RETIRED')).toBeTruthy()
    expect(screen.queryByText('FINAL')).toBeNull()
  })

  it('shows tournament seeds on tennis match cards and no number for unseeded players', () => {
    render(<GameCard
      gameId="x"
      league="ATP"
      homeTeam={{ teamId: 'Sinner', name: 'Jannik Sinner', seed: 1 }}
      awayTeam={{ teamId: 'Player', name: 'Unseeded Player' }}
      startTime="2026-08-26T15:00:00Z"
      status="SCHEDULED"
    />)
    expect(screen.getByText('(1) Jannik Sinner')).toBeTruthy()
    expect(screen.getByText('Unseeded Player')).toBeTruthy()
    expect(screen.queryByText(/undefined.*Unseeded Player/)).toBeNull()
  })

  it('labels a shootout-decided soccer final with the pens result', () => {
    render(<GameCard
      gameId="401863611"
      league="LCUP"
      homeTeam={{ teamId: 'CLB', name: 'Columbus Crew', score: 1, winner: true }}
      awayTeam={{ teamId: 'UNAM', name: 'UNAM', score: 1, winner: false }}
      startTime="2026-08-12T00:00:00Z"
      status="FINAL"
      statusDetail="FT (Pens)"
    />)
    expect(screen.getByText('FT (Pens)')).toBeTruthy()
  })

  it('keeps showing Final/OT and Final/10', () => {
    render(<GameCard
      gameId="x"
      league="NHL"
      homeTeam={{ teamId: 'TOR', name: 'Toronto Maple Leafs', score: 3 }}
      awayTeam={{ teamId: 'MTL', name: 'Montreal Canadiens', score: 2 }}
      startTime="2025-10-12T00:00:00Z"
      status="FINAL"
      statusDetail="Final/OT"
    />)
    expect(screen.getByText('Final/OT')).toBeTruthy()
  })
})

describe('GameCard postponed match', () => {
  it('says POSTPONED and shows no 0-0 score for a match that was never played', () => {
    // The real 09-26 row: state post, status FT, 0-0, detail Postponed.
    render(<GameCard
      gameId="761833"
      league="MLS"
      homeTeam={{ teamId: 'RBNY', name: 'Red Bull New York', score: 0, winner: false }}
      awayTeam={{ teamId: 'STL', name: 'St. Louis CITY SC', score: 0, winner: false }}
      startTime="2026-09-26T23:30:00Z"
      status="FINAL"
      statusDetail="Postponed"
    />)
    expect(screen.getByText('POSTPONED')).toBeTruthy()
    expect(screen.queryByText('FINAL')).toBeNull()
    expect(screen.queryAllByText('0')).toHaveLength(0)
  })
})

describe('GameCard preseason label', () => {
  it('labels a publisher-filed preseason game', () => {
    render(<GameCard gameId="401902644" league="NBA" isPreseason
      homeTeam={{ teamId: 'TOR', name: 'Toronto Raptors' }} awayTeam={{ teamId: 'MIA', name: 'Miami Heat' }}
      startTime="2026-10-03T23:00:00Z" status="SCHEDULED" />)
    expect(screen.getByText('Preseason')).toBeTruthy()
  })

  it('shows no label on a regular-season game', () => {
    render(<GameCard gameId="401900001" league="NBA"
      homeTeam={{ teamId: 'OKC', name: 'Thunder' }} awayTeam={{ teamId: 'HOU', name: 'Rockets' }}
      startTime="2026-10-20T23:30:00Z" status="SCHEDULED" />)
    expect(screen.queryByText('Preseason')).toBeNull()
  })
})
