import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import HeroCarousel from './HeroCarousel'
import ModelsSlide, { MODELS } from './ModelsSlide'

const slides = [
  { label: 'First', node: <p>First slide text</p> },
  { label: 'Second', node: <p>Second slide text</p> },
]

function groups() {
  return screen.getAllByRole('group', { hidden: true }) as HTMLElement[]
}

describe('HeroCarousel', () => {
  it('keeps every slide in the page and shows only the first', () => {
    render(<HeroCarousel slides={slides} />)
    expect(groups().map((g) => g.hidden)).toEqual([false, true])
    expect(screen.getByText('Second slide text')).toBeTruthy()
  })

  it('shows a slide when its dot is pressed', () => {
    render(<HeroCarousel slides={slides} />)
    fireEvent.click(screen.getByRole('button', { name: 'Show Second' }))
    expect(groups().map((g) => g.hidden)).toEqual([true, false])
    expect(screen.getByRole('button', { name: 'Show Second' }).getAttribute('aria-current')).toBe('true')
  })
})

describe('ModelsSlide', () => {
  it('lists each model with its status and shows no statistics', () => {
    const { container } = render(<ModelsSlide />)
    for (const m of MODELS) expect(screen.getByText(m.name)).toBeTruthy()
    expect(screen.getAllByText('Live')).toHaveLength(5)
    expect(screen.getAllByText('Coming soon')).toHaveLength(2)
    expect(container.textContent).not.toMatch(/%|10K|5\+ years|92/)
    expect(screen.queryByText('Model insights')).toBeNull()
  })

  it('uses the homepage copy word for word', () => {
    render(<ModelsSlide />)
    expect(screen.getByText('Prediction models across multiple sports.')).toBeTruthy()
    expect(screen.getByText('Track the models powering Legendary Picks. NFL, NCAAF, NHL, ATP/WTA, and NBA are live now. MLS and UFC are coming soon.')).toBeTruthy()
    expect(screen.getByText('Explore the models →').closest('a')?.getAttribute('href')).toBe('/leagues')
    expect(screen.getByText('Built for transparent forecasting and research.')).toBeTruthy()
    expect(screen.getByText('Sport-specific prediction models with transparent metrics.')).toBeTruthy()
  })

  it('gives each model row one sport icon, hidden from screen readers', () => {
    const { container } = render(<ModelsSlide />)
    const icons = Array.from(container.querySelectorAll('.material-symbols-outlined'))
    expect(icons.map((el) => el.textContent)).toEqual(MODELS.map((m) => m.icon))
    icons.forEach((el) => expect(el.getAttribute('aria-hidden')).toBe('true'))
  })

  it('highlights the border of live models and leaves the others plain', () => {
    render(<ModelsSlide />)
    for (const m of MODELS) {
      const row = screen.getByText(m.name).closest('li') as HTMLElement
      expect(row.className.includes('border-emerald-500/60')).toBe(m.status === 'Live')
      expect(row.className.includes('border-zinc-800')).toBe(m.status !== 'Live')
    }
  })
})
