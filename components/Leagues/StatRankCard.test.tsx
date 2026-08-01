import { render, screen } from '@testing-library/react'
import StatRankCard from './StatRankCard'

describe('StatRankCard', () => {
  it('renders the reference hierarchy as one orange-headed four-stat card', () => {
    const { container } = render(
      <StatRankCard
        title="2025 Regular Season Stats"
        statRanks={{
          rush_yds_g: { value: 85.6, rank: 4, label: 'Rush Yds/G' },
          carries_g: { value: 17.9, rank: 6, label: 'Carries/G' },
          rec_yds_g: { value: 25.4, rank: 154, label: 'Rec Yds/G' },
          fantasy_ppr_g: { value: 20.1, rank: null, label: 'PPR/G' },
        }}
      />,
    )

    expect(screen.getByText('2025 Regular Season Stats').className).toContain('bg-orange-600')
    expect(container.querySelectorAll('.grid > div')).toHaveLength(4)
    expect(screen.getByText('4th')).toBeTruthy()
    expect(screen.getByText('154th')).toBeTruthy()
  })

  it('uses the recovered completion label', () => {
    render(
      <StatRankCard
        statRanks={{
          cmp_g: { value: 19.2, rank: 25, label: 'Cmp/G' },
        }}
      />,
    )

    expect(screen.getByText('Comp/G')).toBeTruthy()
    expect(screen.queryByText('Cmp/G')).toBeNull()
  })
})
