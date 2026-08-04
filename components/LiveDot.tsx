/**
 * The live indicator, in one place.
 *
 * There were eight copies of this span across three files, at two different
 * sizes (`h-1 w-1` and `h-1.5 w-1.5`), none of them with `shrink-0` — so flexbox
 * squashed several into 5.19x6 ellipses. Fixing that made them round at **6px**,
 * which is the size the original typo'd its way into rather than a size anybody
 * chose. Six pixels of flat red is the weakest possible treatment of the one
 * element on the page whose whole job is to pull the eye.
 *
 * So: 8px core sized to sit with the 10px uppercase labels it always appears
 * beside (their cap height is ~7px), plus a halo ring that carries the pulse.
 * Animating the ring rather than the dot keeps the core at constant opacity —
 * a dot that fades to 50% reads as a disabled control, not a live one.
 *
 * `motion-reduce` kills the animation and keeps the ring, because the ring is
 * doing legibility work, not decoration.
 */
export default function LiveDot({ className = '' }: { className?: string }) {
  return (
    <span className={`relative flex h-2 w-2 shrink-0 ${className}`} aria-hidden="true">
      <span className="absolute inline-flex h-full w-full rounded-full bg-red-500 opacity-60 motion-safe:animate-ping motion-reduce:opacity-40" />
      <span className="relative inline-flex h-2 w-2 rounded-full bg-red-500 ring-2 ring-red-500/25" />
    </span>
  )
}
