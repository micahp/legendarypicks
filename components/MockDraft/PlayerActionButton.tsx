/* ── One action button per row, always ──────────────────────────────────────
   The row used to carry two controls: a Draft button that appeared when it was
   your turn, and a `+Q` / `−Q` toggle that was always there. So the action cell
   held one button sometimes and two others, the column reflowed the moment the
   turn flipped, and the queue toggle was a symbol nobody has ever seen on a
   draft board.

   ESPN's own walkthrough states the rule we are adopting: "When it's your turn
   to draft, the QUEUE button will be replaced with DRAFT buttons that you will
   tap to make your pick." One button, in a fixed-width cell, whose label is the
   only thing that changes.

   Colour is deliberately NOT the differentiator. ESPN paints Draft blue and the
   header green; our accent marks absence and nothing else (honest-data-ui §5),
   so the two states are separated by weight and fill instead. Spending the one
   saturated colour on "it is your turn" would spend it on achievement, and the
   games a player missed would then have to compete with it. */

interface Props {
  playerId: number
  /** Named in the aria-label, so the control is not just "button" to a screen reader. */
  name: string
  /** Your turn AND the client is accepting a pick. See DraftRoom for why those differ. */
  onClock: boolean
  queued: boolean
  completed: boolean
  onDraft: (playerId: number) => void
  onQueue: (playerId: number) => void
  onUnqueue: (playerId: number) => void
}

// Fixed, so the column does not reflow when Draft becomes Queue mid-draft.
const WIDTH = 'w-[4.75rem]'
const BASE =
  `${WIDTH} rounded border px-2 py-1 text-[10px] font-semibold uppercase tracking-wider ` +
  'transition-colors'

export default function PlayerActionButton({
  playerId, name, onClock, queued, completed, onDraft, onQueue, onUnqueue,
}: Props) {
  // Absent, not disabled: there is nothing to draft into once the draft is over,
  // and a greyed-out control that can never become live is just noise.
  if (completed) return null

  if (onClock) {
    return (
      <button
        type="button"
        aria-label={`Draft ${name}`}
        onClick={e => { e.stopPropagation(); onDraft(playerId) }}
        className={`${BASE} border-zinc-500 bg-zinc-700 text-zinc-100 hover:border-zinc-400 hover:bg-zinc-600`}
      >
        Draft
      </button>
    )
  }

  if (queued) {
    return (
      <button
        type="button"
        aria-label={`Remove ${name} from your queue`}
        onClick={e => { e.stopPropagation(); onUnqueue(playerId) }}
        className={`${BASE} border-zinc-600 bg-zinc-800 text-zinc-300 hover:border-zinc-500 hover:text-zinc-100`}
      >
        Queued
      </button>
    )
  }

  return (
    <button
      type="button"
      aria-label={`Queue ${name}`}
      onClick={e => { e.stopPropagation(); onQueue(playerId) }}
      className={`${BASE} border-zinc-800 bg-zinc-900 text-zinc-500 hover:border-zinc-700 hover:text-zinc-300`}
    >
      Queue
    </button>
  )
}
