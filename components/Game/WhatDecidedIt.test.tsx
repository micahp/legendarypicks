import React from 'react'
import { render, screen } from '@testing-library/react'
import WhatDecidedIt from './WhatDecidedIt'

const leaders = [
  { player_id: 1, name: 'Brady Singer', team: 'CIN', market: 'total_outs', line: 17.5, actual: 18, cashed: 'over', margin: 0.5 },
  { player_id: 2, name: 'Keibert Ruiz', team: 'WSH', market: 'total_hits,_runs_and_rbis', line: 1.5, actual: 5, cashed: 'over', margin: 3.5 },
  { player_id: 3, name: 'Elly De La Cruz', team: 'CIN', market: 'total_bases', line: 1.5, actual: 0, cashed: 'under', margin: 1.5 },
]

describe('WhatDecidedIt', () => {
  it('says nothing at all until a line has settled', () => {
    // A game with no settled lines has no story to tell here, and an empty panel
    // with a heading would imply we had looked and found nothing worth showing.
    const { container } = render(<WhatDecidedIt leaders={[]} settledLines={0} />)
    expect(container.firstChild).toBeNull()
  })

  it('shows the sample it is drawn from, never a record', () => {
    // We hold both sides of most lines, so any win-loss figure would describe our
    // storage layout rather than our judgement.
    render(<WhatDecidedIt leaders={leaders} settledLines={48} />)
    expect(screen.getByText('3 of 48 settled lines')).toBeTruthy()
    expect(screen.queryByText(/\d+ of \d+ hit/)).toBeNull()
  })

  it('states the direction in words rather than by color alone', () => {
    // Self-evident beats a legend, and it survives greyscale and colorblindness.
    render(<WhatDecidedIt leaders={leaders} settledLines={48} />)
    expect(screen.getAllByText('over the line').length).toBe(2)
    expect(screen.getByText('under the line')).toBeTruthy()
  })

  it('renders which side cashed, the value the endpoint computes for this panel', () => {
    render(<WhatDecidedIt leaders={leaders} settledLines={48} />)
    expect(screen.getAllByText('over cashed').length).toBe(2)
    expect(screen.getByText('under cashed')).toBeTruthy()
  })

  it('spends no accent color on clearing a line', () => {
    // honest-data-ui §5: the accent marks absence, not achievement. Nothing on this
    // panel is an achievement of ours — painting clears green and shorts red makes it
    // read as the win-loss record the endpoint deliberately refuses to publish.
    const { container } = render(<WhatDecidedIt leaders={leaders} settledLines={48} />)
    const bars = container.querySelectorAll('[class*="bg-emerald"], [class*="bg-red"]')
    expect(bars.length).toBe(0)
  })

  it('does not invent a denominator for a line of zero', () => {
    // Substituting 1 for 0 silently misplaces the fill instead of showing nothing.
    const zero = [{ ...leaders[0], line: 0, actual: 2, margin: 2 }]
    const { container } = render(<WhatDecidedIt leaders={zero} settledLines={1} />)
    expect(screen.getByText('line 0')).toBeTruthy()
    const fill = container.querySelector('[class*="bg-zinc-500"]') as HTMLElement
    expect(fill.style.width).toBe('0%')
  })

  it('keeps a result far past its line inside the track', () => {
    const huge = [{ ...leaders[1], line: 0.5, actual: 9, margin: 8.5 }]
    const { container } = render(<WhatDecidedIt leaders={huge} settledLines={1} />)
    const fill = container.querySelector('[class*="bg-zinc-500"]') as HTMLElement
    expect(parseFloat(fill.style.width)).toBeLessThanOrEqual(100)
  })
})
