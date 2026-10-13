import React from 'react'
import { render, screen } from '@testing-library/react'
import PropHistoryCard from './PropHistoryCard'
import { prop } from './fixtures'

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
