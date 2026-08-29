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
    const select = screen.getByRole('combobox', {
      name: 'Line and provider for Alternate Player Shots',
    })
    const options = within(select).getAllByRole('option').map(option => option.textContent)

    expect(options).toEqual([
      '0.5 · prizepicks',
      '0.5 · underdog',
      '1.5 · underdog',
      '2.5 · bovada',
    ])
    expect(options.join(' ')).not.toContain('rotowire:')
  })

  it('updates the offer odds and chart line when another option is selected', async () => {
    render(<MarketSlateBoard league="nfl" date="2026-09-09" />)

    const select = await screen.findByRole('combobox', {
      name: 'Line and provider for Alternate Player Shots',
    })
    fireEvent.change(select, { target: { value: '2.5|bovada' } })

    const row = document.querySelector('[data-market-row]') as HTMLElement
    await waitFor(() => {
      expect(row.textContent).toContain('-110')
      expect(row.textContent).toContain('+100')
      expect(row.textContent).not.toContain('no line price')
      expect((global.fetch as jest.Mock).mock.calls.some(([url]) =>
        String(url).includes('/api/props/history?') && String(url).includes('line=2.5'))).toBe(true)
    })
  })
})
