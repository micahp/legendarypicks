import { fireEvent, render, screen } from '@testing-library/react'
import LeagueLocker from './LeagueLocker'

describe('LeagueLocker', () => {
  it('starts with equally visible NFL HQ and research routes', () => {
    render(<LeagueLocker />)

    expect(screen.getByRole('link', { name: /Enter NFL HQ/ }).getAttribute('href')).toBe('/leagues/nfl?tab=camp')
    expect(screen.getByRole('link', { name: /Research NFL/ }).getAttribute('href')).toBe('/props?league=nfl')
    expect(screen.getByRole('img', { name: /without a helmet/ })).toBeTruthy()
  })

  it('equips the same character for NFL and clears the equipment for other leagues', () => {
    render(<LeagueLocker />)

    fireEvent.click(screen.getByRole('button', { name: 'Select NFL' }))
    expect(screen.getByRole('img', { name: /wearing a fictional football helmet/ })).toBeTruthy()
    expect(screen.getByText(/fictional helmet equipped/)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Select NBA' }))
    expect(screen.getByRole('img', { name: /without a helmet/ })).toBeTruthy()
    expect(screen.getByRole('link', { name: /Research NBA/ }).getAttribute('href')).toBe('/props?league=nba')
  })
})
