import React from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import PropsPage from '../pages/props'
import { groupSportNavigation } from '../components/Navigation/sports'

describe('Props sport selector', () => {
  it('keeps football direct and groups tours or competitions under their sport', () => {
    const groups = groupSportNavigation([
      { league: 'nfl', sport: 'football' },
      { league: 'ncaaf', sport: 'football' },
      { league: 'mls', sport: 'soccer' },
      { league: 'lcup', sport: 'soccer' },
      { league: 'nba', sport: 'basketball' },
      { league: 'atp', sport: 'tennis' },
      { league: 'wta', sport: 'tennis' },
      { league: 'ufc', sport: 'mma' },
    ], 'props')
    expect(groups.map(group => group.label)).toEqual(['NFL', 'NCAAF', 'Soccer', 'Tennis', 'NBA', 'UFC'])
    expect(groups.find(group => group.label === 'Soccer')?.competitions.map(item => item.league))
      .toEqual(['mls', 'lcup'])
    expect(groups.find(group => group.label === 'Tennis')?.competitions.map(item => item.league))
      .toEqual(['atp', 'wta'])
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
  const clickAndFlush = async (button: HTMLElement) => {
    await act(async () => {
      fireEvent.click(button)
      await new Promise(resolve => setTimeout(resolve, 0))
    })
  }

  beforeEach(() => {
    global.fetch = jest.fn((input: RequestInfo | URL) => {
      const url = String(input)
      const payload = url.includes('/api/navigation/sports')
        ? { props: [
          { league: 'ufc', sport: 'mma' },
          { league: 'mlb', sport: 'baseball' },
          { league: 'nba', sport: 'basketball' },
          { league: 'nfl', sport: 'football' },
          { league: 'nhl', sport: 'hockey' },
          { league: 'atp', sport: 'tennis' },
          { league: 'wta', sport: 'tennis' },
        ] }
        : slate
      return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) })
    }) as any
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
      .map(section => (section as HTMLElement).dataset.slateLeague)).toEqual(['mlb', 'nhl', 'ufc'])
    expect(Array.from(dates[1].querySelectorAll(':scope > [data-slate-league]'))
      .map(section => (section as HTMLElement).dataset.slateLeague)).toEqual(['nfl', 'nba'])
    expect(dates[0].textContent).toContain('MLB1 game · 8 props')
    expect(dates[0].textContent).toContain('UFC1 game · 2 props')
    expect(dates[0].textContent).toContain('NHL1 game · 4 props')
    expect(dates[1].textContent).toContain('NBA1 game · 6 props')
    expect(dates[1].textContent).toContain('NFL2 games · 22 props')
    expect(document.querySelectorAll('[data-slate-date] .h-px')).toHaveLength(0)
  })

  it('queries both tours by default, then one tour when the competition is selected', async () => {
    render(React.createElement(PropsPage))
    fireEvent.click(await screen.findByRole('button', { name: 'Tennis' }))

    await waitFor(() => {
      expect((global.fetch as jest.Mock).mock.calls.some(([url]) =>
        String(url).includes('leagues=atp%2Cwta'))).toBe(true)
    })
    await waitFor(() => expect(document.querySelectorAll('[data-slate-game]')).toHaveLength(slate.length))
    expect(screen.getByRole('navigation', { name: 'Tennis competitions' })).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'WTA' }))
    await waitFor(() => {
      expect((global.fetch as jest.Mock).mock.calls.some(([url]) =>
        String(url).includes('league=wta'))).toBe(true)
    })
    await waitFor(() => expect(document.querySelectorAll('[data-slate-game]')).toHaveLength(slate.length))
  })

  it('keeps NBA and both soccer competitions selectable when their slate is empty', async () => {
    global.fetch = jest.fn((input: RequestInfo | URL) => {
      const url = String(input)
      const payload = url.includes('/api/navigation/sports')
        ? { props: [
          { league: 'mls', sport: 'soccer' },
          { league: 'lcup', sport: 'soccer' },
          { league: 'nba', sport: 'basketball' },
        ] }
        : []
      return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) })
    }) as any

    render(React.createElement(PropsPage))

    await clickAndFlush(await screen.findByRole('button', { name: 'Soccer' }))
    const soccerNav = screen.getByRole('navigation', { name: 'Soccer competitions' })
    expect(soccerNav.textContent).toContain('MLS')
    expect(soccerNav.textContent).toContain('Leagues Cup')
    await waitFor(() => expect((global.fetch as jest.Mock).mock.calls.some(([url]) =>
      String(url).includes('leagues=mls%2Clcup'))).toBe(true))

    await clickAndFlush(screen.getByRole('button', { name: 'Leagues Cup' }))
    await waitFor(() => expect((global.fetch as jest.Mock).mock.calls.some(([url]) =>
      String(url).includes('league=lcup'))).toBe(true))

    await clickAndFlush(screen.getByRole('button', { name: 'NBA' }))
    await waitFor(() => expect((global.fetch as jest.Mock).mock.calls.some(([url]) =>
      String(url).includes('league=nba'))).toBe(true))
    expect(screen.getByRole('button', { name: 'NBA' }).getAttribute('aria-pressed')).toBe('true')
  })

  it('uses the published Leagues Cup label for the slate heading', async () => {
    global.fetch = jest.fn((input: RequestInfo | URL) => {
      const payload = String(input).includes('/api/navigation/sports')
        ? { props: [{ league: 'lcup', sport: 'soccer' }] }
        : [{
          game_id: 1494,
          home: 'Toluca',
          away: 'Austin FC',
          date: '2026-08-26',
          start_time: '2026-08-27T00:30:00Z',
          league: 'lcup',
          prop_count: 8,
          players: [],
        }]
      return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) })
    }) as any

    render(React.createElement(PropsPage))

    await waitFor(() => {
      const heading = document.querySelector('[data-slate-league="lcup"] h3')
      expect(heading?.textContent).toBe('Leagues Cup')
    })
  })
})
