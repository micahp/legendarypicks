import { render, screen } from '@testing-library/react'
import NewsTab from './NewsTab'
import { LeagueSection } from '../News/LeagueSection'
import type { LeagueNews } from '../News/LeagueSection'

const feed: LeagueNews = {
  conversations: [{
    conv_id: 'c1', league: 'mls', title: 'Cross-border spending',
    narrative: 'Galaxy sell Cerrillo.', fan_voice: '', paragraph: 'A paragraph.',
    sources: [{ headline: 'A', url: 'https://a.example', source: 'The Athletic' }],
    generated_at: '2026-08-17T14:37:58Z', story_time: '2026-08-17T14:37:58Z', source_count: 3,
  }],
  narratives: [{
    id: 1, league: 'mls', headline: 'CAS to hear appeal', url: 'https://y.example',
    source: 'espn-ligamx', published: '2026-08-17T12:00:00Z', layer: 'narrative', key_player: null,
  }],
  granular: [{
    id: 2, league: 'mls', headline: 'Hibs finalizing deal', url: 'https://x.example',
    source: '@TomBogert', published: '2026-08-17T14:00:00Z', layer: 'trade', key_player: null,
  }],
  other: 0,
}

describe('league hub News tab', () => {
  it('renders exactly what the News page renders for that league', () => {
    // The tab must not be a second design of the same thing: it delegates to the
    // News page's own LeagueSection, so the markup is identical by construction.
    const tab = render(<NewsTab league="mls" news={feed} loading={false} error={null} />)
    const tabHtml = tab.container.innerHTML
    tab.unmount()

    const page = render(<LeagueSection league="mls" data={feed} />)
    expect(tabHtml).toBe(page.container.innerHTML)
  })

  it('shows the section even with nothing in the feed', () => {
    render(<NewsTab league="nba" news={null} loading={false} error={null} />)
    expect(screen.getByText(/No classified news yet for NBA/)).not.toBeNull()
  })

  it('surfaces the endpoint reason on failure', () => {
    render(<NewsTab league="nba" news={null} loading={false} error="News is unavailable." />)
    expect(screen.getByText('News is unavailable.')).not.toBeNull()
  })
})
