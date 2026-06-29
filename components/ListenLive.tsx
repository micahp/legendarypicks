import { useState } from 'react'

// Free live audio anchor for leagues we can't show on video (World Cup etc.). talkSPORT carries
// every WC game free with no login (BBC 5 Live needs an account + UK geo). Collapsed by default so
// it never autoplays audio unexpectedly — one tap opens the player.
export default function ListenLive({ label = 'World Cup commentary · talkSPORT (free)' }: { label?: string }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900/50">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-500"
      >
        <span className="flex items-center gap-2 text-sm font-semibold text-zinc-100">
          <span aria-hidden>🎧</span> Listen live
          <span className="font-normal text-zinc-500">· {label}</span>
        </span>
        <span className="font-mono text-xs text-zinc-500">{open ? 'close ▾' : 'play ▸'}</span>
      </button>
      {open ? (
        <iframe
          src="https://tunein.com/embed/player/s17077/"
          title="talkSPORT live audio"
          className="w-full"
          height={100}
          style={{ border: 'none' }}
        />
      ) : null}
    </div>
  )
}
