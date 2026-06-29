import { useState } from 'react'

// Free live audio anchor for leagues we can't show on video (World Cup etc.). Uses iHeartRadio's
// FIFA World Cup station — FOX Sports English commentary, all 104 games, free and US-accessible
// (talkSPORT/BBC are UK-geo-blocked; iHeart is not). Collapsed by default so it never autoplays.
const IHEART_WC = 'https://www.iheart.com/live/fifa-world-cup-2026-11554/'
export default function ListenLive({ label = 'World Cup · FOX Sports on iHeart (free)' }: { label?: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900/50">
      <div className="flex items-center justify-between gap-3 px-4 py-3">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="flex items-center gap-2 text-left text-sm font-semibold text-zinc-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-500"
        >
          <span aria-hidden>🎧</span> Listen live
          <span className="font-normal text-zinc-500">· {label}</span>
          <span className="font-mono text-xs text-zinc-500">{open ? '▾' : '▸'}</span>
        </button>
        <a href={IHEART_WC} target="_blank" rel="noreferrer"
           className="font-mono text-[11px] text-zinc-500 hover:text-emerald-400">open ↗</a>
      </div>
      {open ? (
        <iframe
          src={IHEART_WC}
          title="FIFA World Cup live audio — iHeart"
          className="w-full"
          height={340}
          style={{ border: 'none' }}
        />
      ) : null}
    </div>
  )
}
