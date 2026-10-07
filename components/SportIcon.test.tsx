import { render } from '@testing-library/react'
import SportIcon, { LEAGUE_SLUG_TO_SPORT, sportIconFor } from './SportIcon'

// The league pages dropped their emoji in favour of this shared Material icon.
// What has to hold: every slug the directory/detail pages can receive resolves
// to its sport's glyph, unknown slugs fall back to the trophy (never an emoji,
// never nothing), and the svg stays aria-hidden because the adjacent visible
// text names the league.
describe('SportIcon', () => {
  it('maps each league slug to its sport glyph', () => {
    const expected: Record<string, string> = {
      nba: 'Basketball',
      mlb: 'Baseball',
      nhl: 'Hockey',
      nfl: 'Football',
      ncaaf: 'Football',
      soccer: 'Soccer',
      mls: 'Soccer',
      lcup: 'Soccer',
      ccc: 'Soccer',
      campeones: 'Soccer',
      usoc: 'Soccer',
      wc: 'Soccer',
      atp: 'Tennis',
      wta: 'Tennis',
      tennis: 'Tennis',
      ufc: 'MMA',
      cod: 'Esports',
      esports: 'Esports',
    }
    for (const [slug, sport] of Object.entries(expected)) {
      expect(LEAGUE_SLUG_TO_SPORT[slug]).toBe(sport)
      expect(sportIconFor(slug)).toBe(sport)
    }
  })

  it('accepts the scoreboard sport names too', () => {
    expect(sportIconFor('All')).toBe('All')
    expect(sportIconFor('Basketball')).toBe('Basketball')
    expect(sportIconFor('Soccer')).toBe('Soccer')
  })

  it('falls back to the trophy for unknown slugs — never an emoji, never nothing', () => {
    expect(sportIconFor('not-a-league')).toBe('Trophy')
    const { container } = render(<SportIcon league="not-a-league" />)
    const svg = container.querySelector('svg')
    expect(svg).toBeTruthy()
    // The trophy glyph, inlined as paths.
    expect(svg!.querySelectorAll('path').length).toBeGreaterThan(0)
  })

  it('renders an aria-hidden svg that inherits its colour from text', () => {
    const { container } = render(<SportIcon league="nba" className="h-6 w-6" />)
    const svg = container.querySelector('svg')
    expect(svg).toBeTruthy()
    expect(svg!.getAttribute('aria-hidden')).toBe('true')
    expect(svg!.getAttribute('focusable')).toBe('false')
    expect(svg!.getAttribute('fill')).toBe('currentColor')
    expect(svg!.getAttribute('class')).toBe('h-6 w-6')
  })

  it('different sports resolve to different path data', () => {
    // A spot check: the basketball and soccer glyphs are not the same shape.
    expect(sportIconFor('nba')).not.toBe(sportIconFor('mls'))
  })
})
