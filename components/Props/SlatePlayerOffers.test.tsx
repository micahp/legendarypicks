import React from 'react'
import { fireEvent, render, screen, within } from '@testing-library/react'
import SlatePlayerOffers, { groupSlateOffers, SlateOfferProp } from './SlatePlayerOffers'

const props: SlateOfferProp[] = [
  ...[36.5, 37.5, 38.5, 39.5, 41.5, 42.5, 43.5].flatMap((line, index) => [
    { market: 'rushing_yards', line, side: 'over', source: 'rotowire:underdog', id: index },
    { market: 'rushing_yards', line, side: 'under', source: 'rotowire:underdog', id: index + 20 },
  ]),
  { market: 'rushing_yards', line: 36.5, side: 'over', source: 'rotowire:prizepicks' },
  { market: 'rushing_yards', line: 36.5, side: 'under', source: 'rotowire:prizepicks' },
  { market: 'total_touchdowns', line: 0.5, side: 'over', source: 'rotowire:underdog' },
  { market: 'total_touchdowns', line: 0.5, side: 'under', source: 'rotowire:underdog' },
] as SlateOfferProp[]

describe('slate player offer consolidation', () => {
  it('groups over, under and alternate lines into one row per market', () => {
    const grouped = groupSlateOffers(props)
    expect(grouped).toHaveLength(2)
    expect(grouped.find(row => row.market === 'rushing_yards')?.offers).toHaveLength(8)
    expect(grouped.find(row => row.market === 'rushing_yards')?.offers[0].over).toBeTruthy()
    expect(grouped.find(row => row.market === 'rushing_yards')?.offers[0].under).toBeTruthy()
  })

  it('uses an alternate-line dropdown and opens the selected side at that line', () => {
    const onOpen = jest.fn()
    render(<SlatePlayerOffers playerId={7} playerName="Ashton Gray" props={props} onOpen={onOpen} />)

    expect(document.querySelectorAll('[data-slate-market-row]')).toHaveLength(2)
    const selector = screen.getByLabelText('Line for Ashton Gray rushing yards')
    expect(selector.textContent).toBe('36.5▾')
    fireEvent.click(selector)
    const listbox = screen.getByRole('listbox', { name: 'Alternate lines for Ashton Gray rushing yards' })
    const options = within(listbox).getAllByRole('option')
    expect(options).toHaveLength(7)
    expect(options.map(option => option.textContent)).toEqual([
      '36.5', '37.5', '38.5', '39.5', '41.5', '42.5', '43.5',
    ])
    fireEvent.click(within(listbox).getByRole('option', { name: '43.5' }))

    const rushingRow = document.querySelector('[data-slate-market-row="rushing_yards"]') as HTMLElement
    fireEvent.click(within(rushingRow).getByRole('button', { name: 'UNDER' }))
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({
      market: 'rushing_yards', line: 43.5, side: 'under',
    }))
  })
})

describe('prices on the offer row', () => {
  it('shows a real book price beside the book', () => {
    render(
      <SlatePlayerOffers
        playerId={1}
        playerName="Test Player"
        props={[
          { market: 'saves', line: 2.5, side: 'over', source: 'rotowire:fanduel-sb', odds: -110 },
          { market: 'saves', line: 2.5, side: 'under', source: 'rotowire:fanduel-sb', odds: -110 },
        ]}
        onOpen={() => {}}
      />,
    )
    expect(document.querySelector('[data-slate-odds]')?.textContent).toBe('-110')
  })

  it('shows a positive price with its sign, because the sign is the meaning', () => {
    render(
      <SlatePlayerOffers
        playerId={1}
        playerName="Test Player"
        props={[
          { market: 'saves', line: 2.5, side: 'over', source: 'rotowire:caesars-sb', odds: 145 },
          { market: 'saves', line: 2.5, side: 'under', source: 'rotowire:caesars-sb', odds: 145 },
        ]}
        onOpen={() => {}}
      />,
    )
    expect(document.querySelector('[data-slate-odds]')?.textContent).toBe('+145')
  })

  it('shows NO price for a pickem source, even though the payload carries -137', () => {
    render(
      <SlatePlayerOffers
        playerId={1}
        playerName="Test Player"
        props={[
          { market: 'saves', line: 2.5, side: 'over', source: 'rotowire:prizepicks', odds: -137 },
          { market: 'saves', line: 2.5, side: 'under', source: 'rotowire:prizepicks', odds: -137 },
        ]}
        onOpen={() => {}}
      />,
    )
    expect(document.querySelector('[data-slate-odds]')).toBeNull()
    expect(document.body.textContent).not.toContain('137')
  })

  it('shows nothing when there is no price at all', () => {
    render(
      <SlatePlayerOffers
        playerId={1}
        playerName="Test Player"
        props={[
          { market: 'saves', line: 2.5, side: 'over', source: 'rotowire:betr' },
          { market: 'saves', line: 2.5, side: 'under', source: 'rotowire:betr' },
        ]}
        onOpen={() => {}}
      />,
    )
    expect(document.querySelector('[data-slate-odds]')).toBeNull()
  })

  it('prices each chip when the two sides differ', () => {
    render(
      <SlatePlayerOffers
        playerId={1}
        playerName="Test Player"
        props={[
          { market: 'saves', line: 2.5, side: 'over', source: 'rotowire:draftkings-sb', odds: -120 },
          { market: 'saves', line: 2.5, side: 'under', source: 'rotowire:draftkings-sb', odds: 100 },
        ]}
        onOpen={() => {}}
      />,
    )
    expect(document.querySelector('[data-slate-odds]')).toBeNull()
    const row = document.querySelector('[data-slate-market-row]') as HTMLElement
    expect(row.textContent).toContain('-120')
    expect(row.textContent).toContain('+100')
  })

  it('keeps OVER and UNDER together in one group, so they wrap as a pair', () => {
    render(
      <SlatePlayerOffers
        playerId={1}
        playerName="Test Player"
        props={[
          { market: 'saves', line: 2.5, side: 'over', source: 'rotowire:prizepicks' },
          { market: 'saves', line: 2.5, side: 'under', source: 'rotowire:prizepicks' },
        ]}
        onOpen={() => {}}
      />,
    )
    const row = document.querySelector('[data-slate-market-row]') as HTMLElement
    // The ROW may still wrap on a phone; that is fine and deliberate. What must not happen
    // is the pair splitting, so nothing here asserts flex-nowrap and nothing truncates.
    expect(row.className).toContain('flex-wrap')
    const chips = Array.from(row.querySelectorAll('button, span'))
      .filter(el => ['OVER', 'UNDER'].includes((el.textContent || '').trim()))
    expect(chips).toHaveLength(2)
    expect(chips[0].parentElement).toBe(chips[1].parentElement)
    expect(chips[0].parentElement?.className).toContain('shrink-0')
  })
})
