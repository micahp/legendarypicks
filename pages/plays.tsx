import Head from 'next/head'
import { useEffect, useState } from 'react'
import LiveBoard from '../components/Plays/LiveBoard'
import ParlayRow from '../components/Plays/ParlayRow'
import SetWatch from '../components/Plays/SetWatch'
import UpcomingBoard from '../components/Plays/UpcomingBoard'

// /plays — one URL for both boards.
//
// This route previously redirected to /props, with the note "Plays is a locked dead-product
// decision — no value in its current state." That was true of the OLD plays page: a curated
// board fed by plays_board.json, which has not been written since 2026-07-19. The redirect
// is why the live surface effectively vanished.
//
// What lives here now is not that board. Two surfaces, deliberately kept apart because they
// answer different questions and are built from different things:
//
//   Live      markets with a tape. Ranked by wyckoff / turn / fade off the order book,
//             with US Open match state attached.
//   Upcoming  markets that are open and tradeable but have NOT started. No score, because
//             before a match begins there is no tape and a number would be invented.
//
// The tab is a switch, not a merge. Combining them into one ranked list would put a scored
// card and an unscorable one in the same order, which is the same incommensurable-scale
// mistake the board already had once between fade and wyckoff.

type Tab = 'live' | 'upcoming'

export default function PlaysPage() {
  const [tab, setTab] = useState<Tab>('live')
  const [upcomingCount, setUpcomingCount] = useState<number | null>(null)
  const [liveCount, setLiveCount] = useState<number | null>(null)

  // Counts on the tabs so the other surface is never silently empty — if there is nothing
  // upcoming, that should be visible without switching to find out.
  useEffect(() => {
    let dead = false
    const load = async () => {
      try {
        const [u, l] = await Promise.all([
          fetch('/api/live/upcoming-board', { cache: 'no-store' }).then((r) => r.json()),
          fetch('/api/live/swing-board', { cache: 'no-store' }).then((r) => r.json()),
        ])
        if (dead) return
        setUpcomingCount(Array.isArray(u?.rows) ? u.rows.length : 0)
        setLiveCount(Array.isArray(l?.cards) ? l.cards.length : 0)
      } catch {
        /* counts are a convenience; the boards report their own failures */
      }
    }
    load()
    const id = setInterval(load, 30000)
    return () => {
      dead = true
      clearInterval(id)
    }
  }, [])

  const tabs: { id: Tab; label: string; count: number | null; hint: string }[] = [
    { id: 'live', label: 'Live', count: liveCount, hint: 'markets with a tape, ranked off the order book' },
    { id: 'upcoming', label: 'Upcoming', count: upcomingCount, hint: 'open and tradeable, not started — no score' },
  ]

  return (
    <>
      <Head>
        <title>Plays — Legendary Picks</title>
        <meta
          name="description"
          content="Live buy-only swing candidates off the Kalshi tape, plus tradeable markets that have not started. Paper research only."
        />
      </Head>

      <div className="space-y-5">
        {/* Above the tabs on purpose: a set in progress is the shortest-lived
            play on the page and the one you cannot come back to later. */}
        <ParlayRow />

        <SetWatch />

        <nav aria-label="Plays sections" className="flex gap-1 border-b border-zinc-800">
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              aria-current={tab === t.id ? 'page' : undefined}
              title={t.hint}
              className={`-mb-px flex items-center gap-1.5 border-b-2 px-4 py-2 text-sm font-bold transition-colors ${
                tab === t.id
                  ? 'border-emerald-400 text-zinc-100'
                  : 'border-transparent text-zinc-500 hover:text-zinc-300'
              }`}
            >
              {t.label}
              {t.count != null && (
                <span
                  className={`rounded-full px-1.5 py-0.5 text-[11px] tabular-nums ${
                    tab === t.id ? 'bg-emerald-500/15 text-emerald-300' : 'bg-zinc-800 text-zinc-500'
                  }`}
                >
                  {t.count}
                </span>
              )}
            </button>
          ))}
        </nav>

        {tab === 'live' ? <LiveBoard /> : <UpcomingBoard />}
      </div>
    </>
  )
}
