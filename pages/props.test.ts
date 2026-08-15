import { LEAGUES } from './props'

describe('Props league selector', () => {
  it('offers MLS as a first-class filter', () => {
    expect(LEAGUES).toContain('mls')
  })
})
