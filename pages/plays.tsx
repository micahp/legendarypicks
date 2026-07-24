import Head from 'next/head'
import CuratedPlaysBoard from '../components/Plays/CuratedPlaysBoard'
import LiveDiscounts from '../components/LiveDiscounts'

// /plays composes TWO independent sections:
//   1. Curated conditional board — GET /api/plays/today (atomic snapshot, no request-time network).
//   2. "Cheap Quality, Live" — the existing LiveDiscounts.tsx, unchanged (its own /api/live/discounts
//      endpoint, 45s poll, and receipts). No shared model, poller, or combined endpoint.
export default function PlaysPage() {
  return (
    <>
      <Head>
        <title>Plays — Legendary Picks</title>
        <meta
          name="description"
          content="Curated conditional plays and live discounts — paper research only, no orders."
        />
      </Head>

      <div className="space-y-8">
        {/* hero */}
        <header className="space-y-3">
          <h1 className="text-2xl font-extrabold tracking-tight text-zinc-100">Plays</h1>
          <p className="max-w-2xl text-sm leading-relaxed text-zinc-400">
            Buy-only value discounts: fade <em>reversible</em> overreactions on a quality side, then exit into
            the swing. Nothing here is a pregame buy — every play waits for an exact live trigger. Below the
            curated board, the live surface flags cheap-quality dips as they happen.
          </p>
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-[13px] text-amber-200">
            <span className="font-semibold">Paper research only.</span> No orders are placed. Prices are
            indicative; a valid response is not proof a quote is executable — check board, quote, and window
            status before acting.
          </div>
        </header>

        {/* 1 — curated conditional board */}
        <section aria-labelledby="curated-heading" className="space-y-3">
          <h2 id="curated-heading" className="text-lg font-bold text-zinc-100">
            Today’s curated board
          </h2>
          <CuratedPlaysBoard />
        </section>

        <hr className="border-zinc-800" />

        {/* 2 — independent live surface (unchanged component) */}
        <section aria-labelledby="live-heading" className="space-y-3">
          <div>
            <h2 id="live-heading" className="text-lg font-bold text-zinc-100">
              Cheap Quality, Live
            </h2>
            <p className="text-sm text-zinc-500">
              Independent live-signal surface — its own feed and refresh. A live discount here is a real-time
              flag, not one of the curated conditional plays above.
            </p>
          </div>
          <LiveDiscounts />
        </section>
      </div>
    </>
  )
}
