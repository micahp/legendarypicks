import { fireEvent, render, screen } from '@testing-library/react'
import LeagueLocker from './LeagueLocker'

describe('LeagueLocker', () => {
  it('starts with equally visible NFL HQ and research routes', () => {
    render(<LeagueLocker />)

    expect(screen.getByRole('link', { name: /Enter NFL HQ/ }).getAttribute('href')).toBe('/leagues/nfl?tab=camp')
    expect(screen.getByRole('link', { name: /Research NFL/ }).getAttribute('href')).toBe('/props?league=nfl')
    expect(screen.getByRole('img', { name: /general manager in street clothes/ })).toBeTruthy()
  })

  it('keeps the GM in street clothes and changes the league destination honestly', () => {
    render(<LeagueLocker />)

    fireEvent.click(screen.getByRole('button', { name: 'Select NFL' }))
    expect(screen.getByRole('img', { name: /general manager in street clothes/ })).toBeTruthy()
    expect(screen.getByText(/NFL selected · game focus set/)).toBeTruthy()
    expect(screen.getByRole('link', { name: /Enter NFL HQ/ }).getAttribute('href')).toBe('/leagues/nfl?tab=camp')

    fireEvent.click(screen.getByRole('button', { name: 'Select NBA' }))
    expect(screen.getByRole('img', { name: /general manager in street clothes/ })).toBeTruthy()
    expect(screen.getByRole('link', { name: /Explore NBA/ }).getAttribute('href')).toBe('/leagues/nba')
    expect(screen.getByRole('link', { name: /Research NBA/ }).getAttribute('href')).toBe('/props?league=nba')
  })
})
