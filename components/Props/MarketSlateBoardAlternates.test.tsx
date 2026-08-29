import React from 'react'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import MarketSlateBoard from './MarketSlateBoard'

function json(body: any) {
  return { ok: true, status: 200, json: () => Promise.resolve(body) } as any
}

function prop(id: number, line: number, side: string, source: string, odds: number) {
  return {
    id, market: 'shots', line, side, source,
    captured_at: '2026-08-28T00:00:00Z', odds, player_id: 7,
    player_name: 'Alternate Player', player_team: 'SEA', league: 'nfl',
    game_home: 'SEA', game_away: 'NE', game_date: '2026-09-09',
  }
}

const OFFERS = [
  prop(1, 0.5, 'over', 'rotowire:underdog', -137),
  prop(2, 0.5, 'under', 'rotowire:underdog', -137),
  prop(3, 1.5, 'over', 'rotowire:underdog', -137),
  prop(4, 1.5, 'under', 'rotowire:underdog', -137),
  prop(5, 0.5, 'over', 'rotowire:prizepicks', -137),
  prop(6, 0.5, 'under', 'rotowire:prizepicks', -137),
  prop(7, 2.5, 'over', 'bovada', -110),
  prop(8, 2.5, 'under', 'bovada', 100),
]

beforeEach(() => {
  ;(global as any).fetch = jest.fn((url: string) => {
    if (url.includes('/api/props/slate')) {
      return Promise.resolve(json([{ markets: [{ market: 'shots', count: 4 }] }]))
    }
    if (url.includes('/api/props/history')) {
      const params = new URLSearchParams(url.split('?')[1])
      const line = Number(params.get('line'))
      return Promise.resolve(json({
        player_id: 7, player: 'Alternate Player', team: 'SEA', league: 'nfl',
        market: 'shots', line, side: 'over', projection: 2,
        hit_rate: { l5: 0.6, l10: 0.6, l20: 0.6, season: 0.6 },
        hit_rate_n: { l5: 5, l10: 10, l20: 20, season: 20 },
        games: [{ date: '2026-08-20', value: 2, opponent: 'DEN', home: true, hit: true }],
      }))
    }
    return Promise.resolve(json(OFFERS))
  })
})

describe('alternate provider lines', () => {
  it('keeps one player prop card and lists each provider plus line once', async () => {
    render(<MarketSlateBoard league="nfl" date="2026-09-09" />)

    await waitFor(() => expect(document.querySelectorAll('[data-market-row]')).toHaveLength(1))
    const selector = screen.getByLabelText(
      'Line and provider for Alternate Player Shots',
    )
    fireEvent.click(selector)
    const listbox = screen.getByRole('listbox', {
      name: 'Alternate lines for Alternate Player Shots',
    })
    const options = within(listbox).getAllByRole('option').map(option => option.textContent)
    const visibleLine = document.querySelector('[data-selected-line]') as HTMLElement
    const row = document.querySelector('[data-market-row]') as HTMLElement

    expect(row.className).toContain('overflow-visible')
    expect(row.className).not.toContain('overflow-hidden')
    expect(selector.className).toContain('text-2xl')
    // Default-line rule (docs/PROPS-ODDS-TAXONOMY.md §5): the lowest line among
    // REAL-odds offers is the default — bovada 2.5 beats the prizepicks/underdog
    // placeholders at 0.5/1.5, even though those are numerically lower.
    expect(visibleLine.textContent).toBe('2.5')
    expect(visibleLine.nextElementSibling?.textContent).toBe('▾')
    expect(selector.className).toContain('font-bold')
    expect(selector.className).toContain('text-white')
    expect(selector.textContent).toBe('2.5▾')
    expect(document.querySelector('[data-provider-label]')?.textContent).toBe('bovada')
    expect(listbox.className).toContain('bg-zinc-950')
    expect(options).toEqual([
      '0.5 · prizepicks',
      '0.5 · underdog',
      '1.5 · underdog',
      '2.5 · bovada',
    ])
    expect(options.join(' ')).not.toContain('rotowire:')

    const menu = selector.closest('details') as HTMLDetailsElement
    expect(menu.open).toBe(true)
    fireEvent.pointerDown(document.body)
    expect(menu.open).toBe(false)
  })

  it('updates the offer odds and chart line when another option is selected', async () => {
    render(<MarketSlateBoard league="nfl" date="2026-09-09" />)

    const selector = await screen.findByLabelText(
      'Line and provider for Alternate Player Shots',
    )
    fireEvent.click(selector)
    fireEvent.click(screen.getByRole('option', { name: '2.5 · bovada' }))

    const row = document.querySelector('[data-market-row]') as HTMLElement
    await waitFor(() => {
      expect(document.querySelector('[data-selected-line]')?.textContent).toBe('2.5')
      expect(document.querySelector('[data-provider-label]')?.textContent).toBe('bovada')
      expect(row.textContent).toContain('-110')
      expect(row.textContent).toContain('+100')
      expect(row.textContent).not.toContain('no line price')
      expect((global.fetch as jest.Mock).mock.calls.some(([url]) =>
        String(url).includes('/api/props/history?') && String(url).includes('line=2.5'))).toBe(true)
    })
  })

  it('falls back to the lowest placeholder line when no real-odds offer exists', async () => {
    // MLS-style card: every offer is a pick'em placeholder (the depth markets
    // no real book prices — docs/PROPS-ODDS-TAXONOMY.md §3).
    ;(global as any).fetch = jest.fn((url: string) => {
      if (url.includes('/api/props/slate')) {
        return Promise.resolve(json([{ markets: [{ market: 'shots', count: 4 }] }]))
      }
      if (url.includes('/api/props/history')) {
        const params = new URLSearchParams(url.split('?')[1])
        const line = Number(params.get('line'))
        return Promise.resolve(json({
          player_id: 7, player: 'Alternate Player', team: 'SEA', league: 'mls',
          market: 'shots', line, side: 'over', projection: 2,
          hit_rate: { l5: 0.6, l10: 0.6, l20: 0.6, season: 0.6 },
          hit_rate_n: { l5: 5, l10: 10, l20: 20, season: 20 },
          games: [{ date: '2026-08-20', value: 2, opponent: 'DEN', home: true, hit: true }],
        }))
      }
      return Promise.resolve(json([
        prop(11, 27.5, 'over', 'rotowire:prizepicks', -137),
        prop(12, 27.5, 'under', 'rotowire:prizepicks', -137),
        prop(13, 28.5, 'over', 'rotowire:underdog', -137),
        prop(14, 28.5, 'under', 'rotowire:underdog', -137),
      ]))
    })

    render(<MarketSlateBoard league="mls" date="2026-09-09" />)
    const visibleLine = await screen.findByText('27.5')
    expect(visibleLine).toBeDefined()
    // Placeholder card: pick'em display instead of prices, lowest line default.
    expect(document.querySelector('[data-provider-label]')?.textContent).toBe('prizepicks')
    expect(document.querySelector('[data-market-row]')?.textContent).toContain('no line price')
  })
})
