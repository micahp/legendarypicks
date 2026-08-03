import { render, screen } from '@testing-library/react'

import { PlayerNameCell } from './columns'

/* The subtitle rule is the overlay's, adopted verbatim: the rank label already
   carries the position, so a rank prints "RB3" and nothing else, and the two
   rankless positions print their bare label. "RB · RB1" is the same fact
   twice and the gate fails on it. */
describe('PlayerNameCell', () => {
  it('prints the rank label alone when a positional rank exists', () => {
    render(<PlayerNameCell name="Bijan Robinson" team="ATL" position="RB" posRank={3} />)
    expect(screen.getByTestId('pool-player-subtitle').textContent).toBe('ATL · RB3')
    expect(screen.getByTestId('pool-player-name').textContent).toBe('Bijan Robinson')
  })

  it('prints the bare position when no rank exists', () => {
    render(<PlayerNameCell name="Zay Flowers" team="BAL" position="WR" />)
    expect(screen.getByTestId('pool-player-subtitle').textContent).toBe('BAL · WR')
  })

  it('prints K for a kicker, rank or not', () => {
    render(<PlayerNameCell name="Justin Tucker" team="BAL" position="PK" posRank={1} />)
    expect(screen.getByTestId('pool-player-subtitle').textContent).toBe('BAL · K')
  })

  it('prints D/ST for a defense, rank or not', () => {
    render(<PlayerNameCell name="49ers D/ST" team="SF" position="DEF" posRank={1} />)
    expect(screen.getByTestId('pool-player-subtitle').textContent).toBe('SF · D/ST')
  })

  it('never wraps the name or the subtitle', () => {
    render(<PlayerNameCell name="Christian McCaffrey" team="SF" position="RB" posRank={1} />)
    expect(screen.getByTestId('pool-player-name').className).toContain('whitespace-nowrap')
    expect(screen.getByTestId('pool-player-subtitle').className).toContain('whitespace-nowrap')
  })
})
