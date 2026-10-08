import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import GameCard from './GameCard'
import listen from '../../data/radio-listen.json'
import { audioForGame, teamAudio } from '../../lib/gameAudio'

const push = jest.fn()
jest.mock('next/router', () => ({
  useRouter: () => ({ push }),
}))

const nhl = {
  gameId: '401892456',
  league: 'NHL',
  homeTeam: { teamId: 'ANA', name: 'Anaheim Ducks' },
  awayTeam: { teamId: 'EDM', name: 'Edmonton Oilers' },
  startTime: '2026-10-08T02:00:00Z',
}
const table = listen as unknown as Record<string, Record<string, { href: string; label: string }>>

describe('team radio data', () => {
  it('every link opens a publisher player page', () => {
    for (const lg of ['nhl', 'mlb', 'nba']) {
      for (const [team, e] of Object.entries(table[lg])) {
        expect([team, e.href]).toEqual([team, expect.stringMatching(/^https:\/\/(tunein\.com\/radio|www\.iheart\.com\/live)\//)])
        expect(e.label).toBeTruthy()
      }
    }
  })

  it('covers every NHL club and resolves both Utah spellings', () => {
    expect(Object.keys(table.nhl)).toHaveLength(32)
    expect(teamAudio('NHL', 'UTA')?.href).toBe(table.nhl.UTA.href)
    expect(teamAudio('NHL', 'UTAH')?.href).toBe(table.nhl.UTA.href)
  })

  it('uses the scoreboard codes for MLB clubs whose league code differs', () => {
    expect(teamAudio('MLB', 'ARI')).not.toBeNull()
    expect(teamAudio('MLB', 'CHW')).not.toBeNull()
    expect(teamAudio('MLB', 'AZ')).toBeNull()
  })

  it('a team without a verified player gets no link, the other team still does', () => {
    expect(teamAudio('MLB', 'BAL')).toBeNull()
    const both = audioForGame('MLB', 'NYY', 'BAL')
    expect(both.map((a) => a.team)).toEqual(['NYY'])
  })

  it('leagues without team radio return nothing', () => {
    expect(audioForGame('UFC', 'A', 'B')).toEqual([])
    expect(audioForGame(undefined, 'NYY', 'TB')).toEqual([])
  })
})

describe('GameCard audio', () => {
  beforeEach(() => push.mockClear())

  it('shows home then away station and opens the player without navigating', () => {
    render(<GameCard {...nhl} status="SCHEDULED" />)
    const links = screen.getAllByRole('link', { name: /listen live/i })
    expect(links.map((l) => l.getAttribute('href'))).toEqual([table.nhl.ANA.href, table.nhl.EDM.href])
    expect(links[0].getAttribute('target')).toBe('_blank')
    fireEvent.click(links[0])
    expect(push).not.toHaveBeenCalled()
  })

  it('keeps the links during the game and removes them after final', () => {
    const { rerender } = render(<GameCard {...nhl} status="LIVE" />)
    expect(screen.getAllByRole('link', { name: /listen live/i })).toHaveLength(2)
    rerender(<GameCard {...nhl} status="FINAL" />)
    expect(screen.queryByRole('link', { name: /listen live/i })).toBeNull()
  })
})
