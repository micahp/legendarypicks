import React from 'react'
import { render } from '@testing-library/react'
import GameCard from './GameCard'

jest.mock('next/router', () => ({
  useRouter: () => ({ push: jest.fn() }),
}))

const base = {
  gameId: '401', league: 'NFL',
  homeTeam: { teamId: 'WIS', name: 'Wisconsin' }, awayTeam: { teamId: 'MSU', name: 'Michigan St.' },
  startTime: '2026-10-03T16:30:00Z',
}

// The header's right slot says when the game is: the start time before kickoff,
// the status badge once it is live or final. The left side holds only quiet labels.
describe('GameCard header time slot', () => {
  it('puts a scheduled game\'s start time on the right', () => {
    const { container } = render(<GameCard {...base} status="SCHEDULED" isPreseason />)
    const header = container.firstElementChild!.firstElementChild!
    const left = header.children[0], right = header.children[1]
    const time = new Date(base.startTime).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    expect(right.textContent).toBe(time)
    expect(left.textContent).toBe('Preseason')
  })

  it('keeps the badge on the right for a final, with no time', () => {
    const { container } = render(<GameCard {...base} status="FINAL" statusDetail="Final"
      homeTeam={{ ...base.homeTeam, score: 34 }} awayTeam={{ ...base.awayTeam, score: 13 }} />)
    const right = container.firstElementChild!.firstElementChild!.children[1]
    expect(right.textContent).toBe('FINAL')
  })
})
