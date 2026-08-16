import React from 'react'
import { render, waitFor } from '@testing-library/react'
import PropsPage, { LEAGUES } from './props'

describe('Props league selector', () => {
  it('omits World Cup and puts UFC first with MLB after NHL', () => {
    expect(LEAGUES).toEqual(['All', 'ufc', 'mls', 'nba', 'nfl', 'nhl', 'mlb'])
  })
})

describe('Props slate grouping', () => {
  const slate = [
    { game_id: 1, home: 'DAL', away: 'PHI', date: '2026-08-17', start_time: '2026-08-17T00:30:00+00:00', league: 'nfl', prop_count: 12, players: [] },
    { game_id: 2, home: 'NYY', away: 'BOS', date: '2026-08-16', start_time: '2026-08-16T00:30:00+00:00', league: 'mlb', prop_count: 8, players: [] },
    { game_id: 3, home: 'GB', away: 'CHI', date: '2026-08-17', start_time: '2026-08-17T02:30:00+00:00', league: 'nfl', prop_count: 10, players: [] },
    { game_id: 4, home: 'LAL', away: 'BOS', date: '2026-08-16', start_time: '2026-08-16T22:00:00+00:00', league: 'nba', prop_count: 6, players: [] },
    { game_id: 5, home: 'A', away: 'B', date: '2026-08-16', start_time: '2026-08-16T01:30:00+00:00', league: 'ufc', prop_count: 2, players: [] },
    { game_id: 6, home: 'C', away: 'D', date: '2026-08-16', start_time: '2026-08-16T02:30:00+00:00', league: 'nhl', prop_count: 4, players: [] },
  ]
  const originalFetch = global.fetch

  beforeEach(() => {
    global.fetch = jest.fn(() => Promise.resolve({
      ok: true,
      json: () => Promise.resolve(slate),
    })) as any
  })

  afterEach(() => {
    global.fetch = originalFetch
  })

  it('uses each game’s local start date and keeps totals per league', async () => {
    render(React.createElement(PropsPage))

    await waitFor(() => {
      expect(document.querySelectorAll('[data-slate-game]')).toHaveLength(slate.length)
    })

    const dates = Array.from(document.querySelectorAll<HTMLElement>('[data-slate-date]'))
    expect(dates.map(section => section.dataset.slateDate)).toEqual(['2026-08-15', '2026-08-16'])
    expect(Array.from(dates[0].querySelectorAll(':scope > [data-slate-league]'))
      .map(section => (section as HTMLElement).dataset.slateLeague)).toEqual(['ufc', 'nhl', 'mlb'])
    expect(Array.from(dates[1].querySelectorAll(':scope > [data-slate-league]'))
      .map(section => (section as HTMLElement).dataset.slateLeague)).toEqual(['nba', 'nfl'])
    expect(dates[0].textContent).toContain('MLB1 game · 8 props')
    expect(dates[0].textContent).toContain('UFC1 game · 2 props')
    expect(dates[0].textContent).toContain('NHL1 game · 4 props')
    expect(dates[1].textContent).toContain('NBA1 game · 6 props')
    expect(dates[1].textContent).toContain('NFL2 games · 22 props')
    expect(document.querySelectorAll('[data-slate-date] .h-px')).toHaveLength(0)
  })
})
