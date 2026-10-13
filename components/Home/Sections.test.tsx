import React from 'react'
import { render, screen } from '@testing-library/react'
import QuestionsSection from './QuestionsSection'
import ChainSection from './ChainSection'
import TrustSection from './TrustSection'
import PlansSection from './PlansSection'
import { featured } from './fixtures'

describe('QuestionsSection', () => {
  it('renders the six questions', () => {
    render(<QuestionsSection />)
    expect(screen.getAllByRole('heading', { level: 3 })).toHaveLength(6)
    expect(screen.getByText('Where do we differ from the line?')).toBeTruthy()
  })
})

describe('ChainSection', () => {
  it('shows the four cards with real numbers', () => {
    render(<ChainSection featured={{ status: 'ready', data: featured }} />)
    expect(screen.getAllByRole('article')).toHaveLength(4)
    expect(screen.getByText('Baltimore 24.6, Atlanta 24.1')).toBeTruthy()
    expect(screen.getByText('The game ended 30 to 23.', { exact: false })).toBeTruthy()
    expect(screen.getByText('San Francisco 49ers 99.5%')).toBeTruthy()
    expect(screen.getByText('61%')).toBeTruthy()
  })
  it('hides a card whose piece is null', () => {
    render(<ChainSection featured={{ status: 'ready', data: { ...featured, chain: { ...featured.chain, market: null, player: null } } }} />)
    expect(screen.getAllByRole('article')).toHaveLength(2)
    expect(screen.queryByText('A fair price for every line')).toBeNull()
  })
  it('renders nothing when every piece is absent or the read failed', () => {
    const none = { player: null, game: null, market: null, season: null }
    const a = render(<ChainSection featured={{ status: 'ready', data: { ...featured, chain: none } }} />)
    expect(a.container.firstChild).toBeNull()
    const b = render(<ChainSection featured={{ status: 'error' }} />)
    expect(b.container.firstChild).toBeNull()
  })
  it('holds four skeleton cards while loading', () => {
    const { container } = render(<ChainSection featured={{ status: 'loading' }} />)
    expect(container.querySelectorAll('[data-state="loading"]')).toHaveLength(4)
  })
})

describe('TrustSection', () => {
  it('reads this season\'s record from the data', () => {
    render(<TrustSection featured={{ status: 'ready', data: featured }} />)
    expect(screen.getByText(/5-6-1 against the line after 12 graded games/)).toBeTruthy()
  })
  it('omits the season sentence when there is no record', () => {
    render(<TrustSection featured={{ status: 'ready', data: { ...featured, record: null } }} />)
    expect(screen.queryByText(/This season/)).toBeNull()
    expect(screen.getByText(/15 of 16 seasons/)).toBeTruthy()
  })
  it('omits it on error and while loading', () => {
    render(<TrustSection featured={{ status: 'error' }} />)
    expect(screen.queryByText(/This season/)).toBeNull()
  })
})

describe('PlansSection', () => {
  it('shows a disabled waitlist control with no link or form, and the one amber price token', () => {
    const { container } = render(<PlansSection />)
    const btn = screen.getByRole('button', { name: 'Join the waitlist' })
    expect(btn.getAttribute('aria-disabled')).toBe('true')
    expect(btn.closest('a')).toBeNull()
    expect(container.querySelector('form')).toBeNull()
    expect(screen.getByText('Price to be set').className).toContain('amber')
  })
})
