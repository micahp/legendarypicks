import React from 'react'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import MarketSlateBoard from './MarketSlateBoard'

// RotoWire stamps a constant price on pick'em books. Verified in its raw payload
// 2026-08-26: `prizepicks` and `underdog` each carry exactly one (over, under)
// pair across every archived prop -- (-137, -137) -- while sleeper has 231
// distinct pairs and draftkings-sb 351. Rendering that constant as a price
// invites a comparison that cannot mean anything.
const LINE = 0.5

function json(body: any) {
  return { ok: true, status: 200, json: () => Promise.resolve(body) } as any
}

function prop(id: number, name: string, source: string, odds: number | null) {
  return {
    id, market: 'shots', line: LINE, side: 'over', source,
    captured_at: '2026-08-26T00:00:00Z', odds, player_id: id,
    player_name: name, player_team: 'LEO', league: 'ligamx',
    game_home: 'León', game_away: 'Salt Lake', game_date: '2026-08-26',
  }
}

const ROWS = [
  prop(1, 'Pickem Player', 'rotowire:prizepicks', -137),
  prop(2, 'Booked Player', 'bovada', -160),
]

beforeEach(() => {
  ;(global as any).fetch = jest.fn((url: string) => {
    if (url.includes('/api/props/slate')) {
      return Promise.resolve(json([{ markets: [{ market: 'shots', count: ROWS.length }] }]))
    }
    if (url.includes('/api/props/history')) {
      const id = Number(new URLSearchParams(url.split('?')[1]).get('player_id'))
      return Promise.resolve(json({
        player_id: id, player: 'x', team: 'LEO', league: 'ligamx', market: 'shots',
        line: LINE, side: 'over', projection: 1,
        hit_rate: { l5: 0.5, l10: 0.5, l20: 0.5, season: 0.5 },
        hit_rate_n: { l5: 5, l10: 10, l20: 20, season: 20 },
        games: Array.from({ length: 20 }, (_, i) => ({
          date: '2026-08-0' + ((i % 9) + 1), value: 1, opponent: 'AME', home: true, hit: i % 2 === 0,
        })),
      }))
    }
    return Promise.resolve(json(ROWS))
  })
})

async function rowFor(player: string): Promise<HTMLElement> {
  await waitFor(() => {
    expect(document.querySelectorAll('[data-market-row]').length).toBe(ROWS.length)
  })
  const row = Array.from(document.querySelectorAll('[data-market-row]'))
    .find(r => (r.textContent || '').includes(player))
  return row as HTMLElement
}

describe('a pick’em book shows no line price', () => {
  it('does not print the relay constant for a prizepicks row', async () => {
    render(<MarketSlateBoard league="ligamx" date="2026-08-26" />)
    const row = await rowFor('Pickem Player')
    expect(row.textContent).not.toContain('-137')
    expect(row.textContent).toContain('no line price')
  })

  it('still prints a real book’s price', async () => {
    render(<MarketSlateBoard league="ligamx" date="2026-08-26" />)
    const row = await rowFor('Booked Player')
    expect(row.textContent).toContain('-160')
    expect(row.textContent).not.toContain('no line price')
  })

  it('keeps the pick’em row on the board rather than hiding it', async () => {
    // 5,005 player/market/line/side combinations exist ONLY at a pick'em book.
    // Suppressing the price must not suppress the prop.
    render(<MarketSlateBoard league="ligamx" date="2026-08-26" />)
    expect((await rowFor('Pickem Player'))).toBeTruthy()
  })
})

describe('the odds sort ranks by price and parks pick’em last', () => {
  it('orders real prices shortest to longest and leaves pick’em at the bottom', async () => {
    // American odds are monotonic as integers: -160 is a shorter price than
    // +500. A pick'em row has no price at all, so it must not interleave.
    const rows = [
      prop(1, 'Pickem Player', 'rotowire:prizepicks', -137),
      prop(2, 'Longshot', 'bovada', 500),
      prop(3, 'Favourite', 'bovada', -160),
    ]
    ;(global as any).fetch = jest.fn((url: string) => {
      if (url.includes('/api/props/slate')) {
        return Promise.resolve(json([{ markets: [{ market: 'shots', count: rows.length }] }]))
      }
      if (url.includes('/api/props/history')) {
        const id = Number(new URLSearchParams(url.split('?')[1]).get('player_id'))
        return Promise.resolve(json({
          player_id: id, player: 'x', team: 'LEO', league: 'ligamx', market: 'shots',
          line: LINE, side: 'over', projection: 1,
          hit_rate: { l5: 0.5, l10: 0.5, l20: 0.5, season: 0.5 },
          hit_rate_n: { l5: 5, l10: 10, l20: 20, season: 20 },
          games: Array.from({ length: 20 }, (_, i) => ({
            date: '2026-08-0' + ((i % 9) + 1), value: 1, opponent: 'AME', home: true, hit: i % 2 === 0,
          })),
        }))
      }
      return Promise.resolve(json(rows))
    })

    render(<MarketSlateBoard league="ligamx" date="2026-08-26" />)
    await waitFor(() => {
      expect(document.querySelectorAll('[data-market-row]').length).toBe(rows.length)
    })
    fireEvent.click(screen.getByRole('button', { name: /^Odds/ }))
    await waitFor(() => {
      const names = Array.from(document.querySelectorAll('[data-market-row] h3'))
        .map(n => (n.textContent || '').trim())
      // ASCENDING by default: shortest price first -- the favourite, which is
      // the useful end. Descending would open the board on +10000 longshots.
      // Pick'em has no price and parks last in either direction.
      expect(names[names.length - 1]).toBe('Pickem Player')
      expect(names.slice(0, 2)).toEqual(['Favourite', 'Longshot'])
    })
  })
})
