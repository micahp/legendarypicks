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
