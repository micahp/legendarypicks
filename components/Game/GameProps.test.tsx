import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import GameProps from './GameProps'

const payload = {
  league: 'mlb',
  game_id: '999',
  settled_lines: 2,
  players: [{
    player_id: 10, name: 'Aaron Judge', team: 'NYY',
    props: [
      { market: 'total_bases', line: 1.5, side: 'over', result: { actual: 3, hit: true, settled_at: 'x', cashed: 'over' } },
      { market: 'total_bases', line: 1.5, side: 'under', result: { actual: 3, hit: false, settled_at: 'x', cashed: 'over' } },
      { market: 'hits', line: 0.5, side: 'over', result: { actual: 0, hit: false, settled_at: 'x', cashed: 'under' } },
      { market: 'strikeouts', line: 1.5, side: 'under', result: null },
    ],
  }],
}

// GameProps is presentational now — the page owns the single fetch (useGameProps), so
// these render it directly with the data the hook would have handed it.
function renderProps(body: any = payload) {
  return render(
    <GameProps
      league="mlb" players={body.players} settledLines={body.settled_lines}
      edgeLabel={false} loading={false} inTab
    />,
  )
}

describe('GameProps after the game settles', () => {
  it('reports lines settled and never a hit rate', async () => {
    // We hold both sides of most lines, so a win-loss record here would describe our
    // storage layout rather than our judgement.
    renderProps()
    await waitFor(() => expect(screen.getByText('How the props landed')).toBeTruthy())
    expect(screen.getByText('2 lines settled')).toBeTruthy()
    expect(screen.queryByText(/hit$/)).toBeNull()
  })

  it('shows a settled line once, not once per side', async () => {
    // "total bases over 1.5 -> 0" beside "total bases under 1.5 -> 0" is one result
    // printed twice, with a guaranteed 50% success rate attached.
    const { container } = renderProps()
    await waitFor(() => expect(screen.getByText('How the props landed')).toBeTruthy())
    const chips = Array.from(container.querySelectorAll('button'))
      .filter(b => b.textContent?.includes('total bases'))
    expect(chips).toHaveLength(1)
    expect(chips[0].textContent).toContain('over')
  })

  it('shows the number each settled prop landed on', async () => {
    renderProps()
    await waitFor(() => expect(screen.getByText('→ 3')).toBeTruthy())
    expect(screen.getByText('→ 0')).toBeTruthy()
  })

  it('leaves an unsettled prop unmarked rather than showing it as a miss', async () => {
    // The distinction the feature rests on: no verdict is not a loss.
    const { container } = renderProps()
    await waitFor(() => expect(screen.getByText('How the props landed')).toBeTruthy())
    const chip = Array.from(container.querySelectorAll('button'))
      .find(b => b.textContent?.includes('strikeouts'))!
    expect(chip.textContent).not.toContain('→')
    expect(chip.getAttribute('title')).toBeNull()
  })

  it('keeps the plain heading while nothing has settled', async () => {
    renderProps({ ...payload, settled_lines: 0,
      players: [{ ...payload.players[0], props: [{ market: 'hits', line: 0.5, side: 'over', result: null }] }] })
    await waitFor(() => expect(screen.getByText('Player Props')).toBeTruthy())
    expect(screen.queryByText(/hit$/)).toBeNull()
  })
})
