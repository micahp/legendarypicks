import { render, screen, within } from '@testing-library/react'

import type { DraftPlayer } from '../../lib/mockDraft/engine'
import type { PoolPlayer } from '../Leagues/types'
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

describe('PlayersTab', () => {
  it('shows the filtered player-pool ordinal instead of the gapped source rank', () => {
    render(
      <PlayersTab
        rows={[{ kind: 'player', dp: DRAFT_PLAYER, rank: 1 }]}
        playerMap={new Map([[POOL_PLAYER.player_id, POOL_PLAYER]])}
        posRank={new Map()}
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

    const table = within(screen.getByTestId('pool-table'))
    expect(table.getByText('1')).toBeTruthy()
    expect(table.queryByText('69')).toBeNull()
  })
})
