import React from 'react'
import { render, screen } from '@testing-library/react'
import GameCard from './GameCard'

jest.mock('next/router', () => ({
  useRouter: () => ({ push: jest.fn() }),
}))

const base = {
  gameId: '401', league: 'NFL',
  homeTeam: { teamId: 'WIS', name: 'Wisconsin' }, awayTeam: { teamId: 'MSU', name: 'Michigan St.' },
  startTime: '2026-10-03T16:30:00Z',
}
const time = new Date(base.startTime).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })

// A scheduled game's start time sits on the team rows, where the score will be; there is
// no header row above it. Preseason is a quiet line under the teams (ESPN's context line).
describe('GameCard layout', () => {
  it('puts a scheduled game\'s time beside the team names, in the score column', () => {
    const { container } = render(<GameCard {...base} status="SCHEDULED" />)
    const card = container.firstElementChild!
    const rows = card.firstElementChild!                       // the team block is the first child
    expect(rows.textContent).toContain('WIS')
    expect(rows.lastElementChild!.textContent).toBe(time)       // right column of the same block
  })

  it('moves Preseason below the teams', () => {
    const { container } = render(<GameCard {...base} status="SCHEDULED" isPreseason />)
    const card = container.firstElementChild!
    expect(card.lastElementChild!.textContent).toBe('Preseason')
    expect(screen.getAllByText('Preseason')).toHaveLength(1)
  })

  it('keeps the badge heading a final, with no time', () => {
    const { container } = render(<GameCard {...base} status="FINAL" statusDetail="Final"
      homeTeam={{ ...base.homeTeam, score: 34 }} awayTeam={{ ...base.awayTeam, score: 13 }} />)
    expect(container.firstElementChild!.firstElementChild!.textContent).toBe('FINAL')
    expect(container.textContent).not.toContain(time)
  })
})
