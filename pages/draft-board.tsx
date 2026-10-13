import Head from 'next/head'
import Link from 'next/link'
import NflDraftBoardSurface from '../components/Leagues/NflDraftBoardSurface'

export default function DraftBoardPage() {
  return (
    <>
      <Head><title>NFL Draft Board — Legendary Picks</title></Head>
      <div className="space-y-6">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-bold uppercase tracking-widest text-emerald-400">NFL draft research</p>
            <h1 className="mt-1 text-3xl font-extrabold tracking-tight">Draft Board</h1>
            <p className="mt-2 max-w-2xl text-sm text-zinc-400">
              Compare projections, published ADP, availability, and your own watch, fade, and rank notes.
            </p>
          </div>
          <div className="flex gap-2 text-sm font-semibold">
            <Link href="/leagues/nfl" className="rounded-lg border border-zinc-800 px-3 py-2 text-zinc-300 hover:border-zinc-700">NFL home</Link>
            <Link href="/mock-draft" className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-emerald-300 hover:bg-emerald-500/15">Start a mock draft</Link>
          </div>
        </header>
        <NflDraftBoardSurface standalone />
      </div>
    </>
  )
}
