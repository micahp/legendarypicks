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
const table = listen as unknown as Record<string, Record<string, { href: string; label: string; stream: string }>>

describe('team radio data', () => {
  it('every link opens a publisher player page', () => {
    for (const lg of ['nhl', 'mlb', 'nba']) {
      for (const [team, e] of Object.entries(table[lg])) {
        expect([team, e.href]).toEqual([team, expect.stringMatching(/^https:\/\/(tunein\.com\/radio|www\.iheart\.com\/live)\//)])
        expect(e.label).toBeTruthy()
        // Played in an https page, so the stream must be https too
        expect([team, e.stream]).toEqual([team, expect.stringMatching(/^https:\/\//)])
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

describe('GameCard radio button', () => {
  let play: jest.SpyInstance
  beforeEach(() => {
    push.mockClear()
    play = jest.spyOn(window.HTMLMediaElement.prototype, 'play').mockImplementation(() => Promise.resolve())
    jest.spyOn(window.HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
    jest.spyOn(window.HTMLMediaElement.prototype, 'load').mockImplementation(() => {})
  })
  afterEach(() => jest.restoreAllMocks())

  it('one play button, no station names, plays the home team stream without opening the game', () => {
    const { container } = render(<GameCard {...nhl} status="SCHEDULED" />)
    const buttons = screen.getAllByRole('button', { name: /play live radio/i })
    expect(buttons).toHaveLength(1)
    expect(container.textContent).not.toContain(table.nhl.ANA.label)
    expect(screen.queryByRole('link', { name: /listen/i })).toBeNull()
    fireEvent.click(buttons[0])
    expect(play).toHaveBeenCalledTimes(1)
    expect(container.querySelector('audio')?.getAttribute('src')).toBe(table.nhl.ANA.stream)
    expect(push).not.toHaveBeenCalled()
  })

  it('falls back to the away team when the home club has no stream', () => {
    const { container } = render(
      <GameCard gameId="1" league="MLB" status="LIVE" startTime="2026-10-08T00:00:00Z"
        homeTeam={{ teamId: 'BAL', name: 'Baltimore Orioles' }} awayTeam={{ teamId: 'NYY', name: 'New York Yankees' }} />,
    )
    fireEvent.click(screen.getByRole('button', { name: /play live radio/i }))
    expect(container.querySelector('audio')?.getAttribute('src')).toBe(table.mlb.NYY.stream)
  })

  it('labels a live MLB card Blackout when the check says so', async () => {
    const fetchMock = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ stale: false, games: { '9': { team: 'NYY', blackout: true } } }) })
    ;(global as unknown as { fetch: unknown }).fetch = fetchMock
    render(
      <GameCard gameId="9" league="MLB" status="LIVE" startTime="2026-10-08T00:00:00Z"
        homeTeam={{ teamId: 'NYY', name: 'New York Yankees' }} awayTeam={{ teamId: 'TB', name: 'Tampa Bay Rays' }} />,
    )
    expect(await screen.findByText('Blackout')).toBeTruthy()
    expect(fetchMock).toHaveBeenCalledWith('/api/radio/blackouts')
    // still playable: inside the home market the game is on
    expect(screen.getByRole('button', { name: /play live radio/i })).toBeTruthy()
  })

  it('no button after final, and none when neither club has a stream', () => {
    const { rerender } = render(<GameCard {...nhl} status="FINAL" />)
    expect(screen.queryByRole('button', { name: /play live radio/i })).toBeNull()
    rerender(
      <GameCard gameId="2" league="MLB" status="LIVE" startTime="2026-10-08T00:00:00Z"
        homeTeam={{ teamId: 'BAL', name: 'Baltimore Orioles' }} awayTeam={{ teamId: 'KC', name: 'Kansas City Royals' }} />,
    )
    expect(screen.queryByRole('button', { name: /play live radio/i })).toBeNull()
  })
})
