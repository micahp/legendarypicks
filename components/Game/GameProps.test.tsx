import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import GameProps from './GameProps'

const payload = {
  league: 'mlb',
  game_id: '999',
  settled_count: 2,
  hit_count: 1,
  players: [{
    player_id: 10, name: 'Aaron Judge', team: 'NYY',
    props: [
      { market: 'total_bases', line: 1.5, side: 'over', result: { actual: 3, hit: true, settled_at: 'x' } },
      { market: 'hits', line: 0.5, side: 'over', result: { actual: 0, hit: false, settled_at: 'x' } },
      { market: 'strikeouts', line: 1.5, side: 'under', result: null },
    ],
  }],
}

function mockFetch(body: any) {
  ;(global as any).fetch = jest.fn(() => Promise.resolve({ json: () => Promise.resolve(body) }))
}

describe('GameProps after the game settles', () => {
  it('leads with how the board did', async () => {
    mockFetch(payload)
    render(<GameProps league="mlb" gameId="999" inTab />)
    await waitFor(() => expect(screen.getByText('How the props landed')).toBeTruthy())
    expect(screen.getByText('1')).toBeTruthy()
    expect(screen.getByText(/of 2 hit/)).toBeTruthy()
  })

  it('shows the number each settled prop landed on', async () => {
    mockFetch(payload)
    render(<GameProps league="mlb" gameId="999" inTab />)
    await waitFor(() => expect(screen.getByText('→ 3')).toBeTruthy())
    expect(screen.getByText('→ 0')).toBeTruthy()
  })

  it('leaves an unsettled prop unmarked rather than showing it as a miss', async () => {
    // The distinction the feature rests on: no verdict is not a loss.
    mockFetch(payload)
    const { container } = render(<GameProps league="mlb" gameId="999" inTab />)
    await waitFor(() => expect(screen.getByText('How the props landed')).toBeTruthy())
    const chip = Array.from(container.querySelectorAll('button'))
      .find(b => b.textContent?.includes('strikeouts'))!
    expect(chip.textContent).not.toContain('→')
    expect(chip.getAttribute('title')).toBeNull()
  })

  it('keeps the plain heading while nothing has settled', async () => {
    mockFetch({ ...payload, settled_count: 0, hit_count: 0,
      players: [{ ...payload.players[0], props: [{ market: 'hits', line: 0.5, side: 'over', result: null }] }] })
    render(<GameProps league="mlb" gameId="999" inTab />)
    await waitFor(() => expect(screen.getByText('Player Props')).toBeTruthy())
    expect(screen.queryByText(/hit$/)).toBeNull()
  })
})
