import Link from 'next/link'

/**
 * Entry point to the mock draft, on the NFL camp hub above transactions.
 *
 * The draft itself lives at its own route rather than inline here — it is a
 * full-screen focused task and the camp tab is a skim surface. This card is the
 * doorway.
 *
 * No accent: amber marks absence on this hub and must not be borrowed for a
 * call to action (skill §5, SPEC-slice-D §6.2). The card earns attention from
 * position and copy, the same as the rest of the page.
 */
export default function NflMockDraftCard() {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="min-w-0">
          <p className="text-lg font-bold text-white">Mock draft</p>
          <p className="pt-1 text-sm text-zinc-400">
            Draft a 12-team PPR roster against ADP bots — off this board, with
            last season&rsquo;s availability on every player.
          </p>
        </div>
        <Link
          href="/mock-draft"
          className="shrink-0 rounded-lg border border-zinc-700 bg-zinc-800 px-5 py-2.5 text-sm font-semibold text-zinc-200 transition-colors hover:border-zinc-600 hover:bg-zinc-700"
        >
          Start a mock draft
        </Link>
      </div>
    </div>
  )
}
