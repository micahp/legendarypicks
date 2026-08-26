import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
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
