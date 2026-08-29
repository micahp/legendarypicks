import React from 'react'
import { render, screen } from '@testing-library/react'
import LeaguesPage from '../pages/leagues'

describe('leagues list', () => {
  beforeEach(() => {
    global.fetch = jest.fn(() => Promise.resolve({
      ok: true,
      json: () => Promise.resolve({
        leagues: [
          { league: 'soccer', sport: 'soccer' },
          { league: 'nfl', sport: 'football' },
          { league: 'ncaaf', sport: 'football' },
          { league: 'esports', sport: 'esports' },
        ],
      }),
    })) as any
  })

  it.each([
    ['Soccer', '/leagues/soccer'],
    ['NCAAF', '/leagues/ncaaf'],
    ['Esports', '/leagues/esports'],
  ])('lists %s with a card linking to its league destination', async (name, href) => {
    render(<LeaguesPage />)
    const league = await screen.findByRole('heading', { level: 2, name })
    expect(league).toBeTruthy()
    const card = league.closest('a')
    expect(card?.getAttribute('href')).toBe(href)
  })

  it('renders one flat league grid without sport category headings', async () => {
    render(<LeaguesPage />)
    const directory = await screen.findByLabelText('League directory')
    expect(directory.textContent).toContain('NFL')
    expect(directory.textContent).toContain('NCAAF')
    expect(screen.queryByRole('heading', { name: 'Football' })).toBeNull()
  })
})
