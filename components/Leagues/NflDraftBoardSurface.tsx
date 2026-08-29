import NflDraftRoom from './NflDraftRoom'
import { useNflDraftBoard } from './hooks/useNflDraftBoard'

/** One owner for the draft research board wiring, shared by both routes. */
export default function NflDraftBoardSurface({ standalone = false }: { standalone?: boolean }) {
  const board = useNflDraftBoard(true)
  return (
    <NflDraftRoom
      data={board.data}
      loading={board.loading}
      error={board.error}
      position={board.position}
      sort={board.sort}
      offset={board.offset}
      query={board.query}
      notes={board.notes}
      syncError={board.syncError}
      onSelectPosition={board.selectPosition}
      onSelectSort={board.selectSort}
      onSetQuery={board.setQuery}
      onClearQuery={board.clearQuery}
      onSetOffset={board.setOffset}
      onSetRank={board.setRank}
      onToggleWatch={board.toggleWatch}
      onToggleFade={board.toggleFade}
      standalone={standalone}
    />
  )
}
