import LiveDot from '../LiveDot'

/* Shared esports primitives — the small label/heading/crest vocabulary used by the live board
 * (pages/esports.tsx), the EWC tournament-center module, and the Esports league hub so all three
 * surfaces share one typography system. */

// One label system: tracked small-caps eyebrows, a red pulse when something is live.
export function Eyebrow({ children, live = false }: { children: React.ReactNode; live?: boolean }) {
  return (
    <div className={`flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-[0.2em] ${live ? 'text-red-400' : 'text-zinc-500'}`}>
      {live ? <LiveDot /> : null}
      <span>{children}</span>
    </div>
  )
}

export function SectionHeader({ eyebrow, title, meta, live = false }: { eyebrow: string; title: string; meta?: string; live?: boolean }) {
  return (
    <div className="space-y-2">
      <div className="flex items-end justify-between gap-3">
        <div className="space-y-1.5">
          {eyebrow ? <Eyebrow live={live}>{eyebrow}</Eyebrow> : null}
          <h2 className="text-xl font-bold tracking-tight text-zinc-50">{title}</h2>
        </div>
        {meta ? <span className="shrink-0 pb-0.5 font-mono text-[10px] uppercase tracking-wider text-zinc-600">{meta}</span> : null}
      </div>
      <div className="h-px w-full bg-gradient-to-r from-zinc-700 to-transparent" />
    </div>
  )
}

export function TeamCrest({ src, size = 'h-6 w-6' }: { src: string | null | undefined; size?: string }) {
  return src
    ? <img src={src} alt="" className={`${size} shrink-0 object-contain`} />
    : <span className={`${size} shrink-0 rounded bg-zinc-800`} />
}
