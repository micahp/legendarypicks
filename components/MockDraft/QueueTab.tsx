import type { DraftPlayer } from '../../lib/mockDraft/engine'
import { positionLabel } from '../../lib/nfl/positionLabel'

/* The queue is the only place a queued player can be removed or reordered. That
   is deliberate: on the clock every pool row reads Draft, so there is nowhere in
   the list to un-queue from, and a control that appears and disappears with the
   turn is worse than one that lives somewhere findable. */

interface Props {
  players: DraftPlayer[]
  onRemove: (playerId: number) => void
  onMoveUp: (idx: number) => void
  onMoveDown: (idx: number) => void
  onSelect: (playerId: number) => void
}

export default function QueueTab({ players, onRemove, onMoveUp, onMoveDown, onSelect }: Props) {
  if (players.length === 0) {
    return (
      <div className="rounded-xl border border-zinc-800 bg-zinc-900 px-4 py-10 text-center">
        <p className="text-sm text-zinc-500">
          No players queued — use Queue on any player to line up your next picks.
        </p>
        <p className="mt-1 text-xs text-zinc-600">
          If your clock runs out, the top of this list is what gets drafted for you.
        </p>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 overflow-hidden">
      <div className="divide-y divide-zinc-800/50">
        {players.map((qp, idx) => (
          <div key={qp.player_id} className="flex items-center gap-2 px-4 py-2.5 text-sm">
            <span className="w-6 shrink-0 text-right text-xs tabular-nums text-zinc-600">
              {idx + 1}
            </span>
            <button
              type="button"
              onClick={() => onSelect(qp.player_id)}
              className="flex-1 truncate text-left font-medium text-zinc-200 hover:text-zinc-50"
            >
              {qp.name}
            </button>
            <span className="shrink-0 text-[10px] text-zinc-500">{qp.team}</span>
            <span className="shrink-0 rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] font-semibold text-zinc-400">
              {positionLabel(qp.position)}
            </span>
            <span className="w-14 shrink-0 text-right font-mono text-xs tabular-nums text-zinc-500">
              {qp.adp != null ? qp.adp.toFixed(1) : <span className="text-zinc-700">—</span>}
            </span>
            <div className="flex shrink-0 items-center gap-0.5">
              <button
                type="button"
                onClick={() => onMoveUp(idx)}
                disabled={idx === 0}
                className="rounded px-1 text-[10px] text-zinc-600 hover:text-zinc-300 disabled:cursor-not-allowed disabled:text-zinc-800"
                aria-label={`Move ${qp.name} up`}
              >
                ▲
              </button>
              <button
                type="button"
                onClick={() => onMoveDown(idx)}
                disabled={idx === players.length - 1}
                className="rounded px-1 text-[10px] text-zinc-600 hover:text-zinc-300 disabled:cursor-not-allowed disabled:text-zinc-800"
                aria-label={`Move ${qp.name} down`}
              >
                ▼
              </button>
            </div>
            <button
              type="button"
              onClick={() => onRemove(qp.player_id)}
              className="shrink-0 rounded px-1 text-[10px] text-zinc-600 hover:text-zinc-400"
              aria-label={`Remove ${qp.name} from your queue`}
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
