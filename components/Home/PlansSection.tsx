import React from 'react'
import Link from 'next/link'
import { SectionHeading } from './QuestionsSection'

const FREE = [
  'The prop board for every sport, with last-5 hit rates',
  'The NFL board: projections, lines, picks and grades',
  'One game breakdown each week',
  'The full record, every graded line and forecast',
  'Live scores and news',
]
const MEMBER = [
  'Full prop history in every sport: 5, 10, 20 and season hit rates, every market',
  'Teammate-out splits on the prop chart',
  'Every NFL game breakdown, every week',
  "Player projections with ESPN's beside them",
  'A message when each NFL game locks',
  'CSV export of the record and the prop history',
]

function Items({ items }: { items: string[] }) {
  return (
    <ul>
      {items.map((t) => (
        <li key={t} className="flex gap-2 border-t border-zinc-800 py-[7px] text-sm text-zinc-300 first:border-t-0">
          <span className="text-emerald-400" aria-hidden="true">+</span>
          {t}
        </li>
      ))}
    </ul>
  )
}

export default function PlansSection() {
  return (
    <section aria-labelledby="h-plans">
      <SectionHeading id="h-plans">Free and member</SectionHeading>
      <p className="mb-[18px] max-w-[70ch] border-l-2 border-emerald-600 pl-3.5 text-sm text-zinc-300">
        The record is always free. We do not sell picks. You pay for the data and the tools.
      </p>
      <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2">
        <div className="flex min-w-0 flex-col gap-3 rounded-xl border border-zinc-800 bg-zinc-900 p-[22px]">
          <h3 className="text-xl font-bold">Free</h3>
          <div className="text-[26px] font-bold tabular-nums">$0</div>
          <Items items={FREE} />
          <Link href="/props?tab=props" className="rounded-lg border border-zinc-800 px-5 py-2.5 text-center font-medium hover:bg-zinc-800">
            Browse free
          </Link>
        </div>
        <div className="flex min-w-0 flex-col gap-3 rounded-xl border border-emerald-500/45 bg-zinc-900 p-[22px]">
          <h3 className="text-xl font-bold">Member</h3>
          <div className="text-[26px] font-bold"><span className="text-amber-400">Price to be set</span></div>
          <Items items={MEMBER} />
          {/* No waitlist exists yet: a disabled control, not a dead link or a form. */}
          <button
            type="button"
            aria-disabled="true"
            className="cursor-not-allowed rounded-lg border border-emerald-600 bg-emerald-600 px-5 py-2.5 text-center font-bold text-white opacity-60"
          >
            Join the waitlist
          </button>
        </div>
      </div>
    </section>
  )
}
