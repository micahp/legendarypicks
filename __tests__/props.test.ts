import React from 'react'
import { render, waitFor } from '@testing-library/react'
import PropsPage, { LEAGUES } from '../pages/props'

describe('Props league selector', () => {
  it('omits World Cup, puts UFC first with MLB after NHL, and carries tennis and Leagues Cup', () => {
    // atp/wta were missing while tennis was half the board (2026-08-17), which made them both
    // unfilterable and last in every day group -- LEAGUES is the pill row AND the ordering.
    // lcup appended 2026-08-25 for the same reason, before its first fixtures on 08-26: the
    // API had just been fixed to serve `?league=lcup`, and a league absent from this list is
    // unreachable by filter no matter what the API returns.
    expect(LEAGUES).toEqual(['All', 'ufc', 'mls', 'nba', 'nfl', 'nhl', 'mlb', 'atp', 'wta', 'lcup'])
  })

  it('labels Leagues Cup in words rather than uppercasing the key', () => {
    // Rendering the page fetches the slate; the pills do not depend on it, but the
    // component does, so stub it rather than assert against a crashed render.
    const originalFetch = global.fetch
    global.fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve([]) })) as any
    try {
    // Every other pill is its key uppercased, which is right for NBA and wrong for LCUP.
    // pages/scores.tsx already publishes this competition as "Leagues Cup"; one competition
    // should not have two names in one product.
    render(React.createElement(PropsPage))
      const labels = Array.from(document.querySelectorAll('button')).map(b => b.textContent)
      expect(labels).toContain('Leagues Cup')
      expect(labels).not.toContain('LCUP')
    } finally {
      global.fetch = originalFetch
    }
  })

  it('gives the slate heading the same name as the pill', () => {
    // Fixing the pill alone left the board rendering a "Leagues Cup" pill directly
    // above an "LCUP" heading over the same two games (verified in a browser against
    // the 08-26 fixtures). The heading read `leagueKey.toUpperCase()` rather than the
    // label map, so one competition wore two names on one screen.
    const originalFetch = global.fetch
    global.fetch = jest.fn(() => Promise.resolve({
      ok: true,
      json: () => Promise.resolve([{
        game_id: 1494, home: 'Toluca', away: 'Austin FC', date: '2026-08-26',
        start_time: '2026-08-27T00:30:00Z', league: 'lcup', prop_count: 8, players: [],
      }]),
    })) as any
    try {
      render(React.createElement(PropsPage))
      return waitFor(() => {
        const section = document.querySelector('[data-slate-league="lcup"]')
        expect(section).not.toBeNull()
        const heading = section!.querySelector('h3')!.textContent
        expect(heading).toBe('Leagues Cup')
        expect(heading).not.toBe('LCUP')
      })
    } finally {
      global.fetch = originalFetch
    }
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
