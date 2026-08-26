import { fireEvent, render, screen } from '@testing-library/react'
import PropChart, { PropHistory } from './PropChart'

function chartData(games: PropHistory['games']): PropHistory {
  return {
    player_id: 1,
    player: 'Alex Ready',
    team: 'AAA',
    league: 'nba',
    market: 'points',
    line: 20.5,
    side: 'over',
    projection: null,
    hit_rate: { l5: 0, l10: 0, l20: 0, season: 0 },
    games,
  }
}

const threeGames: PropHistory['games'] = [
  { date: '2026-07-20', value: 24, opponent: 'HOM', home: true, hit: true },
  { date: '2026-07-21', value: 18, opponent: 'AWY', home: false, hit: false },
  { date: '2026-07-22', value: 21, opponent: 'UNK', home: null, hit: true },
]

describe('PropChart venue handling', () => {
  // The per-game labels moved out of the SVG and onto DOM columns under each
  // bar, matching the PrizePicks reference: value, opponent, date. Home games
  // carry no prefix there -- only away gets `@` -- so the old "vs HOM" and the
  // separate away arrow are gone by design, not by accident.
  // Scoped to the label row. Reading the whole container also picks up the
  // "vs <OPP>" FILTER chip, which is a different thing that happens to share
  // the text -- the first version of this test failed on exactly that.
  function columns(container: HTMLElement): string {
    return (container.querySelector('[data-game-labels]')?.textContent || '')
  }

  it('marks a known away game with @', () => {
    const { container } = render(<PropChart data={chartData([
      { date: '2026-07-22', value: 18, opponent: 'AWY', home: false, hit: false },
    ])} />)
    expect(columns(container)).toContain('@AWY')
  })

  it('leaves a home game unprefixed', () => {
    const { container } = render(<PropChart data={chartData([
      { date: '2026-07-22', value: 24, opponent: 'HOM', home: true, hit: true },
    ])} />)
    const text = columns(container)
    expect(text).toContain('HOM')
    expect(text).not.toContain('@HOM')
    expect(text).not.toContain('vs HOM')
  })

  it('leaves unknown venue unmarked', () => {
    const { container } = render(<PropChart data={chartData([
      { date: '2026-07-22', value: 21, opponent: 'UNK', home: null, hit: true },
    ])} />)
    const text = columns(container)
    expect(text).toContain('UNK')
    expect(text).not.toContain('@UNK')
  })

  it('prints the date under each bar as M/D', () => {
    const { container } = render(<PropChart data={chartData([
      { date: '2026-07-22', value: 21, opponent: 'UNK', home: null, hit: true },
    ])} />)
    expect(columns(container)).toContain('7/22')
  })

  it('colours a miss red and a hit green, not two shades of one hue', () => {
    const { container } = render(<PropChart data={chartData([
      { date: '2026-07-21', value: 24, opponent: 'HOM', home: true, hit: true },
      { date: '2026-07-22', value: 18, opponent: 'AWY', home: false, hit: false },
    ])} />)
    const fills = Array.from(container.querySelectorAll('rect')).map(r => r.getAttribute('fill'))
    expect(fills).toContain('#4ade80')
    expect(fills).toContain('#f87171')
  })

  it('prints the average of the games actually drawn', () => {
    const { container } = render(<PropChart data={chartData([
      { date: '2026-07-21', value: 24, opponent: 'HOM', home: true, hit: true },
      { date: '2026-07-22', value: 18, opponent: 'AWY', home: false, hit: false },
    ])} />)
    // (24 + 18) / 2 = 21.0 over 2 games. The footer sits outside the label
    // row, so this one reads the whole chart deliberately.
    const all = container.textContent || ''
    expect(all).toContain('21.0')
    expect(all).toContain('avg last 2')
  })
})

describe('a window short of its own sample reports a dash', () => {
  // 2026-08-26, reported from the props tab: a Liga MX player with three
  // matches printed 100% on L5, L10 AND L20, because `slice(0, 20)` of three
  // games is three games. The label claimed a twenty-game record; the data was
  // three. MLS looked correct only because those players have 25-42 games.
  function headline(container: HTMLElement): string {
    return container.textContent || ''
  }

  it('shows a dash for L5 when only three games exist', () => {
    const { container } = render(
      <PropChart data={chartData(threeGames)} window="l5" />
    )
    expect(headline(container)).toContain('—')
    expect(headline(container)).not.toContain('67%')
  })

  it('shows a dash for L10 and L20 on the same three games', () => {
    for (const w of ['l10', 'l20'] as const) {
      const { container } = render(
        <PropChart data={chartData(threeGames)} window={w} />
      )
      expect(headline(container)).toContain('—')
    }
  })

  it('still reports season, which claims only what exists', () => {
    const { container } = render(
      <PropChart data={chartData(threeGames)} window="season" />
    )
    expect(headline(container)).toContain('67%')
  })

  it('reports a real percentage once the window is full', () => {
    const five = [
      ...threeGames,
      { date: '2026-07-23', value: 30, opponent: 'HOM', home: true, hit: true },
      { date: '2026-07-24', value: 10, opponent: 'AWY', home: false, hit: false },
    ]
    const { container } = render(
      <PropChart data={chartData(five)} window="l5" />
    )
    expect(headline(container)).toContain('60%')
  })
})
