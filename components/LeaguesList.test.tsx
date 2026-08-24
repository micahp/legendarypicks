import React from 'react'
import { render, screen } from '@testing-library/react'
import LeaguesPage from '../pages/leagues'

describe('leagues list', () => {
  beforeEach(() => {
    global.fetch = jest.fn(() => Promise.resolve({
      ok: true,
      json: () => Promise.resolve({
        leagues: [
          { league: 'mls', sport: 'soccer' },
          { league: 'nfl', sport: 'football' },
          { league: 'ncaaf', sport: 'football' },
          { league: 'esports', sport: 'esports' },
        ],
      }),
    })) as any
  })

  it.each([
    ['MLS', '/leagues/mls'],
    ['NCAAF', '/leagues/ncaaf'],
    ['Esports', '/leagues/esports'],
  ])('lists %s with a card linking to its league destination', async (name, href) => {
    render(<LeaguesPage />)
    const league = await screen.findByRole('heading', { level: 3, name })
    expect(league).toBeTruthy()
    const card = league.closest('a')
    expect(card?.getAttribute('href')).toBe(href)
  })

  it('groups competition cards under sport headings', async () => {
    render(<LeaguesPage />)
    const football = await screen.findByRole('heading', { name: 'Football' })
    const section = football.closest('section')
    expect(section?.textContent).toContain('NFL')
    expect(section?.textContent).toContain('NCAAF')
    expect(screen.getByRole('heading', { name: 'Soccer' })).toBeTruthy()
  })
})
