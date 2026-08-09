import React from 'react'
import { render, screen } from '@testing-library/react'
import LeaguesPage from '../pages/leagues'

describe('leagues list', () => {
  it('lists Esports with a card linking to the Esports league destination', () => {
    render(<LeaguesPage />)
    const esports = screen.getByText('Esports')
    expect(esports).toBeTruthy()
    const card = esports.closest('a')
    expect(card?.getAttribute('href')).toBe('/leagues/esports')
  })
})
