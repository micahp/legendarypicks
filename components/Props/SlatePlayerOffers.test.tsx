import React from 'react'
import { fireEvent, render, screen, within } from '@testing-library/react'
import SlatePlayerOffers, { groupSlateOffers, SlateOfferProp } from './SlatePlayerOffers'

const props: SlateOfferProp[] = [
  ...[36.5, 37.5, 38.5, 39.5, 41.5, 42.5, 43.5].flatMap((line, index) => [
    { market: 'rushing_yards', line, side: 'over', source: 'rotowire:underdog', id: index },
    { market: 'rushing_yards', line, side: 'under', source: 'rotowire:underdog', id: index + 20 },
  ]),
  { market: 'total_touchdowns', line: 0.5, side: 'over', source: 'rotowire:underdog' },
  { market: 'total_touchdowns', line: 0.5, side: 'under', source: 'rotowire:underdog' },
] as SlateOfferProp[]

describe('slate player offer consolidation', () => {
  it('groups over, under and alternate lines into one row per market', () => {
    const grouped = groupSlateOffers(props)
    expect(grouped).toHaveLength(2)
    expect(grouped.find(row => row.market === 'rushing_yards')?.offers).toHaveLength(7)
    expect(grouped.find(row => row.market === 'rushing_yards')?.offers[0].over).toBeTruthy()
    expect(grouped.find(row => row.market === 'rushing_yards')?.offers[0].under).toBeTruthy()
  })

  it('uses an alternate-line dropdown and opens the selected side at that line', () => {
    const onOpen = jest.fn()
    render(<SlatePlayerOffers playerId={7} playerName="Ashton Gray" props={props} onOpen={onOpen} />)

    expect(document.querySelectorAll('[data-slate-market-row]')).toHaveLength(2)
    const selector = screen.getByLabelText('Line and provider for Ashton Gray rushing yards')
    expect(selector.textContent).toBe('36.5▾')
    fireEvent.click(selector)
    const listbox = screen.getByRole('listbox', { name: 'Alternate lines for Ashton Gray rushing yards' })
    expect(within(listbox).getAllByRole('option')).toHaveLength(7)
    fireEvent.click(within(listbox).getByRole('option', { name: '43.5 · underdog' }))

    const rushingRow = document.querySelector('[data-slate-market-row="rushing_yards"]') as HTMLElement
    fireEvent.click(within(rushingRow).getByRole('button', { name: 'UNDER' }))
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({
      market: 'rushing_yards', line: 43.5, side: 'under',
    }))
  })
})
