import React from 'react'
import { render, screen } from '@testing-library/react'
import LeaguesPage from '../pages/leagues'

describe('leagues list', () => {
  it.each([
    ['MLS', '/leagues/mls'],
    ['NCAAF', '/leagues/ncaaf'],
    ['Esports', '/leagues/esports'],
  ])('lists %s with a card linking to its league destination', (name, href) => {
    render(<LeaguesPage />)
    const league = screen.getByText(name)
    expect(league).toBeTruthy()
    const card = league.closest('a')
    expect(card?.getAttribute('href')).toBe(href)
  })
})
