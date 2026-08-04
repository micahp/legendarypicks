/**
 * The live indicator, in one place.
 *
 * There were eight copies of this span across three files, at two sizes (`h-1
 * w-1` and `h-1.5 w-1.5`), none with `shrink-0` — so flexbox squashed several
 * into 5.19x6 ellipses. That was the bug, and `shrink-0` is the fix.
 *
 * The size is 6px and stays 6px. It was briefly 8px with a halo ring, on the
 * argument that the live marker should pull the eye; on the page it just read
 * as big. 6px is right beside the 10px uppercase labels this always sits next
 * to — it is a punctuation mark, not a badge, and the pulse is what carries the
 * attention. Do not grow it again without looking at the page.
 */
export default function LiveDot({ className = '' }: { className?: string }) {
  return (
    <span
      className={`block h-1.5 w-1.5 shrink-0 rounded-full bg-red-500 animate-pulse motion-reduce:animate-none ${className}`}
      aria-hidden="true"
    />
  )
}
