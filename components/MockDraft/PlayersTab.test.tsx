import { render, screen, within } from '@testing-library/react'

import type { DraftPlayer } from '../../lib/mockDraft/engine'
import type { PoolPlayer } from '../Leagues/types'
import type { PoolRow } from './PlayersTab'
import PlayersTab from './PlayersTab'


const DRAFT_PLAYER: DraftPlayer = {
  player_id: 469,
  name: 'Josh Allen',
  position: 'QB',
  team: 'BUF',
  adp: 22.8,
}

const POOL_PLAYER: PoolPlayer = {
  player_id: 469,
  name: 'Josh Allen',
  position: 'QB',
  team: 'BUF',
  adp: 22.8,
  espn_ppr_rank: 69,
  percent_owned: 99.8,
  sample: 'full',
  games_played: 17,
  games_missed: 0,
  weeks_played: [1, 2],
  team_weeks: [1, 2],
}

function renderTab({
  rows = [{ kind: 'player', dp: DRAFT_PLAYER, rank: 1 }],
  posRank = new Map<number, number>(),
}: {
  rows?: PoolRow[]
  posRank?: Map<number, number>
} = {}) {
  render(
    <PlayersTab
      rows={rows}
      playerMap={new Map([[POOL_PLAYER.player_id, POOL_PLAYER]])}
      posRank={posRank}
      byeMap={new Map()}
      posOptions={['ALL']}
      posFilter="ALL"
      onPosFilter={() => {}}
      teamOptions={['ALL']}
      teamFilter="ALL"
      onTeamFilter={() => {}}
      byeOptions={['ALL']}
      byeFilter="ALL"
      onByeFilter={() => {}}
      scheduleLoaded
      sortOptions={[{ key: 'rank', label: 'Rank', direction: 'asc' }]}
      sortKey="rank"
      onSort={() => {}}
      onClearFilters={() => {}}
      shown={1}
      available={1}
      drafted={0}
      queue={[]}
      onClock
      completed={false}
      onSelectPlayer={() => {}}
      onDraft={() => {}}
      onQueue={() => {}}
      onUnqueue={() => {}}
    />,
  )
}

describe('PlayersTab', () => {
  it('shows the filtered player-pool ordinal instead of the gapped source rank', () => {
    renderTab()

    const table = within(screen.getByTestId('pool-table'))
    expect(table.getByText('1')).toBeTruthy()
    expect(table.queryByText('69')).toBeNull()
  })

  it('leads the numeric columns with Proj then Exp PPR/G, ahead of Bye and ADP', () => {
    renderTab()

    const texts = Array.from(
      screen.getByTestId('pool-table').querySelectorAll('thead th'),
    ).map(th => (th.textContent ?? '').trim())
    // The Proj header carries a sub-label ("2026 PPR"); match its head, the
    // same way REG-render matches header text rather than counting positions.
    expect(texts[0]).toBe('#')
    expect(texts[1]).toBe('Player')
    expect(texts[2].startsWith('Proj')).toBe(true)
    expect(texts[3].startsWith('Exp PPR/G')).toBe(true)
    expect(texts[4]).toBe('Bye')
    expect(texts[5]).toBe('ADP')
    expect(texts[6]).toBe('Available')
    expect(texts[7]).toBe('')
  })

  it('prints the rank label alone in the subtitle — never "QB · QB1"', () => {
    renderTab({ posRank: new Map([[469, 1]]) })
    expect(screen.getByTestId('pool-player-subtitle').textContent).toBe('BUF · QB1')
    expect(screen.getByTestId('pool-player-subtitle').textContent).not.toMatch(/\bQB\b.*\bQB\d/)
  })

  it('spans the "your pick" divider across all eight columns', () => {
    renderTab({
      rows: [
        { kind: 'divider', pickNo: 13, round: 1, inRound: 1 },
        { kind: 'player', dp: DRAFT_PLAYER, rank: 1 },
      ],
    })
    const divider = screen.getByTestId('your-pick-divider')
    expect(divider.querySelector('td')?.colSpan).toBe(8)
  })
})
