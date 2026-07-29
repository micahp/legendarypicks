import { positionLabel, positionRankLabel } from '../positionLabel'

describe('positionLabel', () => {
  it('shows a kicker as K, never the stored PK', () => {
    expect(positionLabel('PK')).toBe('K')
  })

  it('leaves every other position exactly as stored', () => {
    for (const pos of ['QB', 'RB', 'WR', 'TE', 'FB', 'FLEX', 'DEF']) {
      expect(positionLabel(pos)).toBe(pos)
    }
  })

  it('renders nothing for a missing position rather than "undefined"', () => {
    expect(positionLabel(null)).toBe('')
    expect(positionLabel(undefined)).toBe('')
    expect(positionLabel('')).toBe('')
  })
})

describe('positionRankLabel', () => {
  it('translates the position inside a positional rank', () => {
    expect(positionRankLabel('PK', 3)).toBe('K3')
    expect(positionRankLabel('WR', 12)).toBe('WR12')
  })

  it('drops the rank when there is none', () => {
    expect(positionRankLabel('PK', null)).toBe('K')
  })

  it('renders nothing without a position', () => {
    expect(positionRankLabel(null, 4)).toBe('')
  })
})
