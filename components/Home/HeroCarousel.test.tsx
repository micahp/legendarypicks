import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import HeroCarousel from './HeroCarousel'
import { featured } from './fixtures'
import type { Featured, Load } from './types'

const ready = (d: Featured): Load<Featured> => ({ status: 'ready', data: d })
let scrollTo: jest.Mock

function setReducedMotion(reduce: boolean) {
  window.matchMedia = ((q: string) => ({ matches: reduce && q.includes('reduce'), media: q, addEventListener() {}, removeEventListener() {} })) as any
}

beforeEach(() => {
  scrollTo = jest.fn()
  HTMLElement.prototype.scrollTo = scrollTo as any
  setReducedMotion(false)
})

describe('HeroCarousel', () => {
  it('shows three slides with the links and copy from the design', () => {
    render(<HeroCarousel featured={ready(featured)} />)
    expect(screen.getAllByRole('tab')).toHaveLength(3)
    expect(screen.getByText('Live prop lines and hit rate history across 11 leagues.')).toBeTruthy()
    expect(screen.getByText('Open the prop board').closest('a')!.getAttribute('href')).toBe('/props?tab=props')
    expect(screen.getByText('Open the NFL board').closest('a')!.getAttribute('href')).toBe('/leagues/nfl?tab=model')
    expect(screen.getByText('See the playoff odds').closest('a')!.getAttribute('href')).toBe('/nfl/playoff-odds')
    expect(screen.getByText('Free for all 32 teams.')).toBeTruthy()
  })

  it('moves to a slide when its dot is clicked', () => {
    render(<HeroCarousel featured={ready(featured)} />)
    fireEvent.click(screen.getByLabelText('Show slide 3, playoff odds'))
    expect(scrollTo).toHaveBeenCalledWith(expect.objectContaining({ behavior: 'smooth' }))
    expect(screen.getByLabelText('Show slide 3, playoff odds').getAttribute('aria-selected')).toBe('true')
    expect(screen.getByLabelText('Show slide 1, prop lines').getAttribute('aria-selected')).toBe('false')
  })

  it('moves with the arrow keys and stops at both ends', () => {
    render(<HeroCarousel featured={ready(featured)} />)
    const rail = screen.getByTestId('slides')
    fireEvent.keyDown(rail, { key: 'ArrowLeft' })
    expect(scrollTo).not.toHaveBeenCalled()
    fireEvent.keyDown(rail, { key: 'ArrowRight' })
    expect(screen.getByLabelText('Show slide 2, NFL projections').getAttribute('aria-selected')).toBe('true')
    fireEvent.keyDown(rail, { key: 'ArrowRight' })
    fireEvent.keyDown(rail, { key: 'ArrowRight' })
    expect(scrollTo).toHaveBeenCalledTimes(2)
    fireEvent.keyDown(rail, { key: 'ArrowLeft' })
    expect(screen.getByLabelText('Show slide 2, NFL projections').getAttribute('aria-selected')).toBe('true')
  })

  it('does not animate when the reader prefers reduced motion', () => {
    setReducedMotion(true)
    render(<HeroCarousel featured={ready(featured)} />)
    fireEvent.click(screen.getByLabelText('Show slide 2, NFL projections'))
    expect(scrollTo).toHaveBeenCalledWith(expect.objectContaining({ behavior: 'auto' }))
  })

  it('keeps slide 1 text and drops slides with no data when the read fails', () => {
    render(<HeroCarousel featured={{ status: 'error' }} />)
    expect(screen.getByText('Live prop lines and hit rate history across 11 leagues.')).toBeTruthy()
    expect(screen.getByText(/not available right now/)).toBeTruthy()
    expect(screen.getAllByRole('tab')).toHaveLength(1)
  })

  it('drops only the slide whose piece is null', () => {
    render(<HeroCarousel featured={ready({ ...featured, game: null })} />)
    expect(screen.getAllByRole('tab')).toHaveLength(2)
    expect(screen.queryByText('Open the NFL board')).toBeNull()
    expect(screen.getByLabelText('Slide 2 of 2')).toBeTruthy()
  })

  it('holds all three slides with skeleton cards while loading', () => {
    const { container } = render(<HeroCarousel featured={{ status: 'loading' }} />)
    expect(screen.getAllByRole('tab')).toHaveLength(3)
    expect(container.querySelectorAll('[data-state="loading"]')).toHaveLength(3)
  })
})
