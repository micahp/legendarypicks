import { render, screen } from '@testing-library/react'
import NewsTab from './NewsTab'
import type { LeagueNews } from './types'

const feed = (over: Partial<LeagueNews> = {}): LeagueNews => ({
  conversations: [],
  narratives: [],
  granular: [],
  ...over,
})

describe('league news tab', () => {
  it('says a source count on a synthesised conversation', () => {
    // The conversation text is ours, not a publisher's. How many sources it was
    // built from is part of how much weight it carries, so it is stated rather
    // than left to be inferred from the list length.
    render(
      <NewsTab
        leagueName="MLS"
        loading={false}
        error={null}
        news={feed({
          conversations: [{
            conv_id: 'c1', league: 'mls', title: 'Cross-border spending',
            narrative: 'Galaxy sell Cerrillo.',
            sources: [
              { headline: 'A', url: 'https://a.example' },
              { headline: 'B', url: 'https://b.example' },
            ],
          }],
        })}
      />,
    )
    expect(screen.getByText('Built from 2 sources')).not.toBeNull()
  })

  it('marks a social handle as a post, not as an outlet', () => {
    render(
      <NewsTab
        leagueName="MLS"
        loading={false}
        error={null}
        news={feed({
          granular: [
            { id: 1, league: 'mls', headline: 'Deal close', url: 'https://x.example',
              source: '@TomBogert', published: new Date().toISOString(), layer: 'trade' },
            { id: 2, league: 'mls', headline: 'CAS to hear appeal', url: 'https://y.example',
              source: 'espn-ligamx', published: new Date().toISOString(), layer: 'narrative' },
          ],
        })}
      />,
    )
    expect(screen.getByText('Post by @TomBogert')).not.toBeNull()
    // An outlet is named plainly — it is not relabelled as a post.
    expect(screen.getByText('espn-ligamx')).not.toBeNull()
    expect(screen.queryByText('Post by espn-ligamx')).toBeNull()
  })

  it('reads an unparseable timestamp as unknown rather than as now', () => {
    render(
      <NewsTab
        leagueName="MLS"
        loading={false}
        error={null}
        news={feed({
          granular: [{ id: 3, league: 'mls', headline: 'H', url: 'https://z.example',
            source: 'espn', published: 'not-a-date', layer: 'trade' }],
        })}
      />,
    )
    expect(screen.getByText('time unknown')).not.toBeNull()
  })

  it('says nothing is published rather than rendering an empty shell', () => {
    render(<NewsTab leagueName="NBA" loading={false} error={null} news={feed()} />)
    expect(screen.getByText(/No news published for NBA yet/)).not.toBeNull()
  })

  it('surfaces the endpoint reason on failure', () => {
    render(<NewsTab leagueName="NBA" loading={false} error="News is unavailable." news={null} />)
    expect(screen.getByText('News is unavailable.')).not.toBeNull()
  })
})
