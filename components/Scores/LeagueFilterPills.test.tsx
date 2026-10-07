import { fireEvent, render, screen } from '@testing-library/react'
import LeagueFilterPills, {
  LEAGUE_TO_SPORT,
  SPORT_FETCH_KEYS,
  sportForQuery,
} from './LeagueFilterPills'

// The scoreboard's league <select> became these pills. The contract that has
// to hold: every sport renders as a labelled pill with its Material icon,
// the active sport carries aria-pressed, a click reports the sport, and every
// legacy ?league= value still resolves to the sport it used to filter.
describe('LeagueFilterPills', () => {
  it('renders one pill per sport, each with a visible label and an aria-hidden icon', () => {
    render(<LeagueFilterPills value="All" onChange={() => {}} />)
    const pills = screen.getAllByRole('button')
    expect(pills).toHaveLength(9)
    expect(pills.map((p) => p.textContent)).toEqual(
      ['All', 'Basketball', 'Baseball', 'Hockey', 'Football', 'Soccer', 'Tennis', 'MMA', 'Esports'],
    )
    for (const pill of pills) {
      const icon = pill.querySelector('svg')
      expect(icon).toBeTruthy()
      expect(icon!.getAttribute('aria-hidden')).toBe('true')
      // The label is visible text, not only an aria-label.
      expect((pill.textContent || '').length).toBeGreaterThan(0)
    }
  })

  it('marks exactly the active sport with aria-pressed', () => {
    const { rerender } = render(<LeagueFilterPills value="All" onChange={() => {}} />)
    const pressed = () => screen.getAllByRole('button').filter((b) => b.getAttribute('aria-pressed') === 'true')
    expect(pressed().map((b) => b.textContent)).toEqual(['All'])

    rerender(<LeagueFilterPills value="Soccer" onChange={() => {}} />)
    expect(pressed().map((b) => b.textContent)).toEqual(['Soccer'])
  })

  it('reports the clicked sport through onChange', () => {
    const onChange = jest.fn()
    render(<LeagueFilterPills value="All" onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: 'Tennis' }))
    expect(onChange).toHaveBeenCalledWith('Tennis')
    fireEvent.click(screen.getByRole('button', { name: 'All' }))
    expect(onChange).toHaveBeenCalledWith('All')
  })

  it('resolves every legacy ?league= value to its sport', () => {
    expect(sportForQuery('NBA')).toBe('Basketball')
    expect(sportForQuery('MLB')).toBe('Baseball')
    expect(sportForQuery('NHL')).toBe('Hockey')
    expect(sportForQuery('NFL')).toBe('Football')
    expect(sportForQuery('NCAAF')).toBe('Football')
    expect(sportForQuery('UEFA Nations League')).toBe('Soccer')
    expect(sportForQuery('International Friendlies')).toBe('Soccer')
    expect(sportForQuery('Leagues Cup')).toBe('Soccer')
    expect(sportForQuery('MLS')).toBe('Soccer')
    expect(sportForQuery('Liga MX')).toBe('Soccer')
    expect(sportForQuery('FIFA World Cup')).toBe('Soccer')
    expect(sportForQuery('ATP')).toBe('Tennis')
    expect(sportForQuery('WTA')).toBe('Tennis')
    expect(sportForQuery('UFC')).toBe('MMA')
    expect(sportForQuery('Call of Duty')).toBe('Esports')
    expect(sportForQuery('All')).toBe('All')
    // The sport names the control itself writes round-trip.
    expect(sportForQuery('Soccer')).toBe('Soccer')
    expect(sportForQuery('Esports')).toBe('Esports')
    // Unknown values stay unknown — no silent default to All.
    expect(sportForQuery('nfl')).toBeNull()
    expect(sportForQuery('not-a-league')).toBeNull()
  })

  it('the mapping covers every legacy league and fetch key exactly once', () => {
    // No legacy value lost, none doubled.
    expect(Object.keys(LEAGUE_TO_SPORT)).toHaveLength(16)
    // The union of the sports' fetch keys is the board's full league fan-out,
    // with no league unreachable from any sport pill.
    const keys = new Set(Object.values(SPORT_FETCH_KEYS).flat())
    expect(Array.from(keys).sort()).toEqual(
      ['atp', 'cod', 'friendlies', 'lcup', 'ligamx', 'mlb', 'mls', 'nba', 'ncaaf', 'nfl', 'nhl', 'ufc', 'unl', 'wc', 'wta'],
    )
  })
})
