import React from 'react'
import { render, screen } from '@testing-library/react'
import PropHistoryCard from './PropHistoryCard'
import GameCard from './GameCard'
import PlayoffOddsCard from './PlayoffOddsCard'
import { game, odds, prop } from './fixtures'

describe('PropHistoryCard', () => {
  it('shows the four windows with their sample sizes, 20 bars and the line', () => {
    const { container } = render(<PropHistoryCard prop={prop} />)
    expect(screen.getByText('Test Receiver')).toBeTruthy()
    expect(screen.getByText('SEA at DEN, receiving yards, over 89.5')).toBeTruthy()
    expect(screen.getByText('80%')).toBeTruthy()
    expect(screen.getByText('42 games')).toBeTruthy()
    expect(container.querySelectorAll('rect')).toHaveLength(20)
    expect(screen.getByText('Line 89.5')).toBeTruthy()
    expect(screen.getByRole('img').getAttribute('aria-label')).toContain('against the line of 89.5')
  })
  it('says n/a, not 0%, for a window with no games', () => {
    render(<PropHistoryCard prop={{ ...prop, hit_rate_n: { ...prop.hit_rate_n, l20: 0 }, hit_rate: { ...prop.hit_rate, l20: 0 } }} />)
    expect(screen.getByText('n/a')).toBeTruthy()
    expect(screen.queryByText('0%')).toBeNull()
  })
  it('renders a quiet absent state for null', () => {
    render(<PropHistoryCard prop={null} />)
    expect(screen.getByText(/not available right now/)).toBeTruthy()
  })
})

describe('GameCard', () => {
  it('shows projected, final, both lines, the pick, its gap and the result chip', () => {
    render(<GameCard game={game} />)
    expect(screen.getByText('24.6')).toBeTruthy()
    expect(screen.getByText('30')).toBeTruthy()
    expect(screen.getByText('ATL -3.0')).toBeTruthy()
    expect(screen.getByText('BAL -0.5')).toBeTruthy()
    expect(screen.getByText('BAL +3.0')).toBeTruthy()
    expect(screen.getByText('(3.5 points off the line)')).toBeTruthy()
    expect(screen.getByText('Pick won')).toBeTruthy()
  })
  it('has no final column and no chip before the game is played', () => {
    render(<GameCard game={{ ...game, final: null, pick_result: null }} />)
    expect(screen.queryByText('Final')).toBeNull()
    expect(screen.queryByText('Pick won')).toBeNull()
  })
  it('marks a missing projected score n/a, never zero', () => {
    render(<GameCard game={{ ...game, proj_home: null, proj_away: null }} />)
    expect(screen.getAllByText('n/a')).toHaveLength(2)
  })
  it('renders a quiet absent state for null', () => {
    render(<GameCard game={null} />)
    expect(screen.getByText(/not available right now/)).toBeTruthy()
  })
})

describe('PlayoffOddsCard', () => {
  it('shows five bars with one-decimal percentages and the simulation count', () => {
    render(<PlayoffOddsCard odds={odds} />)
    expect(screen.getAllByRole('listitem')).toHaveLength(5)
    expect(screen.getByText('99.5%')).toBeTruthy()
    expect(screen.getByText(/Top five of 32 teams\. 20,000 simulated seasons\./)).toBeTruthy()
  })
  it('omits the simulation count when the run did not record one', () => {
    render(<PlayoffOddsCard odds={{ ...odds, sims: null }} />)
    expect(screen.queryByText(/simulated seasons/)).toBeNull()
  })
  it('renders a quiet absent state for null', () => {
    render(<PlayoffOddsCard odds={null} />)
    expect(screen.getByText(/not available right now/)).toBeTruthy()
  })
})
