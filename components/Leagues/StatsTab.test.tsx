import { fireEvent, render, screen } from '@testing-library/react'
import StatsTab from './StatsTab'
import type { LeadersData } from './types'

/**
 * The filter bar's contract is that every option it offers came from the API.
 * The endpoint already drops metrics with no values for the selected season
 * (measured 2026-08-17: NBA's `ts_pct` is 100% NULL on both picks.db and
 * picks.dev.db, so True Shooting % is never published) — these tests pin that
 * the UI adds nothing back and renders only what it was handed.
 */
const leaders = (over: Partial<LeadersData> = {}): LeadersData =>
  ({
    league: 'nba',
    season: 2026,
    available_seasons: [2026, 2025],
    stat: 'pts',
    stat_type: null,
    category: 'scoring',
    categories: [
      { key: 'scoring', label: 'Scoring', stats: [{ key: 'pts', label: 'Points', format: 'decimal_1' }] },
      { key: 'defense', label: 'Defense', stats: [{ key: 'stl', label: 'Steals', format: 'decimal_1' }] },
    ],
    columns: [{ key: 'pts', label: 'Points', format: 'decimal_1' }],
    leaders: [
      { player_id: 1, name: 'Luka Doncic', team: 'DAL', games: 40, pts: 33.5 },
    ],
    change_metric: null,
    comparison: null,
    changes: [],
    ...over,
  }) as unknown as LeadersData

const renderTab = (data: LeadersData, extra: Record<string, unknown> = {}) =>
  render(
    <StatsTab
      league="nba"
      leagueName="NBA"
      supportsTeamStats={false}
      subView="players"
      mlbType="batting"
      leaders={data}
      playerLoading={false}
      playerError={null}
      playerFilterError={false}
      teamAggregates={null}
      teamLoading={false}
      teamError={null}
      teamCategory={null}
      onSelectSubView={jest.fn()}
      onSelectMlbType={jest.fn()}
      onSelectSeason={jest.fn()}
      onSelectStatCategory={jest.fn()}
      onSelectSortMetric={jest.fn()}
      onResetFilters={jest.fn()}
      onSelectTeamCategory={jest.fn()}
      {...extra}
    />,
  )

describe('stats filter pills', () => {
  it('offers exactly the seasons and categories the API published', () => {
    renderTab(leaders())

    const season = screen.getByLabelText('Season') as HTMLSelectElement
    expect(Array.from(season.options).map(o => o.value)).toEqual(['2026', '2025'])

    const category = screen.getByLabelText('Stat category') as HTMLSelectElement
    expect(Array.from(category.options).map(o => o.value)).toEqual(['scoring', 'defense'])
  })

  it('reports a season pick to the caller', () => {
    const onSelectSeason = jest.fn()
    renderTab(leaders(), { onSelectSeason })
    fireEvent.change(screen.getByLabelText('Season'), { target: { value: '2025' } })
    expect(onSelectSeason).toHaveBeenCalledWith('2025')
  })

  it('reports a category pick to the caller', () => {
    const onSelectStatCategory = jest.fn()
    renderTab(leaders(), { onSelectStatCategory })
    fireEvent.change(screen.getByLabelText('Stat category'), { target: { value: 'defense' } })
    expect(onSelectStatCategory).toHaveBeenCalledWith('defense')
  })

  it('states a single season without offering it as a control', () => {
    // NFL publishes one season. The year must still be on screen — it is the
    // only thing saying which season the table is — but a select with one
    // option invites a click that cannot do anything.
    renderTab(leaders({ season: 2025, available_seasons: [2025] } as Partial<LeadersData>))
    const season = screen.getByLabelText('Season')
    expect(season.tagName).toBe('SPAN')
    // NBA spans two calendar years, so the pill shows the league's own label.
    expect(season.textContent).toBe('2024-25')
  })

  it('never offers a category the API withheld', () => {
    // NBA "Efficiency" is dropped whenever its metrics have no values.
    renderTab(leaders())
    expect(screen.queryByText('Efficiency')).toBeNull()
  })

  it('drops the season caption above the table — the pill carries it', () => {
    renderTab(leaders())
    expect(screen.queryByText(/^Season 2026$/)).toBeNull()
    expect(screen.getByText(/Sorted by Points/)).not.toBeNull()
  })
})
