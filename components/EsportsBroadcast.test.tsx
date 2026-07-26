import React from 'react'
import { render, screen } from '@testing-library/react'

import { buildBroadcastViews, LiveCard } from '../pages/esports'


describe('between-match broadcast continuity', () => {
  it('keeps the gap state and displays the primary source viewer count', () => {
    const now = Date.UTC(2026, 6, 26, 17, 20)
    const watch = {
      platform: 'youtube',
      url: 'https://www.youtube.com/watch?v=D4jmAm688f8',
      channel: null,
      embedUrl: 'https://www.youtube.com/embed/D4jmAm688f8',
      online: null,
      language: 'en',
      viewers: 18454,
      alternates: [{
        platform: 'twitch',
        url: 'https://www.twitch.tv/lec',
        channel: 'lec',
        embedUrl: 'https://player.twitch.tv/?channel=lec',
        online: true,
        language: 'en',
      }],
    }
    const previous = {
      startTime: now - 60 * 60 * 1000,
      endTime: now - 5 * 60 * 1000,
      live: false,
      finished: true,
      winner: 'b',
      title: 'LoL',
      league: 'LEC — Summer 2026 (Regular Season)',
      teamA: 'Movistar KOI',
      teamB: 'Team Vitality',
      favorite: null,
      watch: null,
      streamKey: 'twitch:lec',
      eventId: 10756,
      prominence: 100,
    }
    const next = {
      startTime: now + 10 * 60 * 1000,
      endTime: null,
      live: false,
      finished: false,
      winner: null,
      title: 'LoL',
      league: 'LEC — Summer 2026 (Regular Season)',
      teamA: 'G2 Esports',
      teamB: 'Karmine Corp',
      favorite: null,
      watch,
      streamKey: 'twitch:lec',
      eventId: 10756,
      prominence: 100,
    }

    const views = buildBroadcastViews([previous, next] as any, [], now)

    expect(views).toHaveLength(1)
    expect(views[0].state).toBe('gap')
    expect(views[0].match).toBe(previous)
    expect(views[0].upNext).toBe(next)
    expect(views[0].watch?.viewers).toBe(18454)

    render(
      <LiveCard
        m={views[0].match}
        host="localhost"
        upNext={views[0].upNext}
        watchOverride={views[0].watch}
        broadcastKey={views[0].key}
        broadcastState={views[0].state}
      />,
    )

    expect(screen.getByText(/18.5K watching/)).toBeTruthy()
    expect(screen.getByText('Final')).toBeTruthy()
    expect(screen.getByText('Up Next')).toBeTruthy()
    expect(screen.getByText('G2 Esports')).toBeTruthy()
    expect(screen.getByText('Karmine Corp')).toBeTruthy()
  })
})
