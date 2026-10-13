import React from 'react'

export const cardBase = 'min-w-0 rounded-[14px] border border-zinc-800 bg-zinc-900/90 p-4 sm:px-[18px]'

/** The quiet state every hero card shares: same footprint as the real card, no spinner. */
export function QuietCard({ label, kind }: { label: string; kind: 'loading' | 'absent' }) {
  return (
    <div className={`${cardBase} flex min-h-[18rem] flex-col gap-3`} aria-label={label} data-state={kind}>
      {kind === 'loading' ? (
        <>
          <div className="h-4 w-1/2 rounded bg-zinc-800" />
          <div className="h-3 w-3/4 rounded bg-zinc-800" />
          <div className="mt-2 h-40 rounded bg-zinc-800" />
        </>
      ) : (
        <p className="m-auto text-sm text-amber-400">This example is not available right now.</p>
      )}
    </div>
  )
}

export function SourceLine({ children }: { children: React.ReactNode }) {
  return <p className="text-[11px] leading-snug text-zinc-500">{children}</p>
}
