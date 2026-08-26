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
  function svgLabel(container: HTMLElement): string {
    const svg = container.querySelector('svg')
    const textNodes = svg ? Array.from(svg.querySelectorAll('text')) : []
    return textNodes.map(t => t.textContent || '').join(' ')
  }

  it('labels a known away game with @', () => {
    const { container } = render(<PropChart data={chartData([
      { date: '2026-07-22', value: 18, opponent: 'AWY', home: false, hit: false },
    ])} />)
    expect(svgLabel(container)).toContain('@ AWY')
  })

  it('labels a known home game with vs', () => {
    const { container } = render(<PropChart data={chartData([
      { date: '2026-07-22', value: 24, opponent: 'HOM', home: true, hit: true },
    ])} />)
    expect(svgLabel(container)).toContain('vs HOM')
  })

  it('leaves unknown venue unmarked', () => {
    const { container } = render(<PropChart data={chartData([
      { date: '2026-07-22', value: 21, opponent: 'UNK', home: null, hit: true },
    ])} />)
    const label = svgLabel(container)
    expect(label).toContain('UNK')
    expect(label).not.toContain('@')
    expect(label).not.toContain('vs')
  })

  it('shows the away arrow only for a known away game', () => {
    const { container } = render(<PropChart data={chartData(threeGames)} />)
    const arrows = Array.from(container.querySelectorAll('span'))
      .filter(el => (el.className || '').includes('ml-0.5'))
    expect(arrows).toHaveLength(3)
    expect(arrows.map(arrow => arrow.textContent)).toEqual(['', '↑', ''])
  })

  it('keeps unknown venue out of both venue filters', () => {
    const { container } = render(<PropChart data={chartData(threeGames)} />)
    const barCount = () => container.querySelectorAll('rect').length

    expect(barCount()).toBe(3)
    fireEvent.click(screen.getByText('Home'))
    expect(barCount()).toBe(1)
    fireEvent.click(screen.getByText('Away'))
    expect(barCount()).toBe(1)
    fireEvent.click(screen.getByText('All'))
    expect(barCount()).toBe(3)
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
