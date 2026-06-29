// Free live audio anchor for leagues we can't show on video (World Cup etc.). Plays the iHeart
// FIFA World Cup 2026 station's DIRECT AAC stream (FOX Sports English commentary, all 104 games,
// free + US-accessible) in a native <audio> element — no iHeart page (which defaulted to a local
// station like Kiss.fm) and no UK geo-block like talkSPORT. preload=none so nothing loads until tapped.
const WC_STREAM = 'https://stream.revma.ihrhls.com/zc11554'        // iHeart FIFA World Cup 2026 (FOX, AAC)
const WC_PAGE = 'https://www.iheart.com/live/fifa-world-cup-2026-11554/'

export default function ListenLive({ label = 'World Cup · FOX Sports commentary (free)' }: { label?: string }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-sm font-semibold text-zinc-100">
          <span aria-hidden>🎧</span> Listen live <span className="font-normal text-zinc-500">· {label}</span>
        </span>
        <a href={WC_PAGE} target="_blank" rel="noreferrer" className="font-mono text-[11px] text-zinc-500 hover:text-emerald-400">iHeart ↗</a>
      </div>
      <audio controls preload="none" src={WC_STREAM} className="h-9 w-full">
        Your browser can’t play this stream — <a href={WC_PAGE}>open on iHeart ↗</a>
      </audio>
    </div>
  )
}
