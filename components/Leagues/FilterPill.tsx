/**
 * A filter control shaped like the pills the major sports sites use above a
 * standings table: a rounded outline, the accent colour on the value itself,
 * and a chevron that says it opens.
 *
 * The value carries the label — a pill reading "2026" needs no "SEASON:"
 * caption next to it, and a row of captions is what makes a filter bar read as
 * a form. The name is still published to assistive tech via `aria-label`, so
 * dropping the visible caption costs nothing there.
 *
 * This stays a native <select>: it opens as the platform picker on mobile,
 * keyboards work, and 25 options scroll. `appearance-none` removes only the
 * browser's own arrow so ours can sit in its place.
 */
export default function FilterPill({
  label,
  value,
  options,
  onSelect,
  id,
}: {
  label: string
  value: string | number
  options: { value: string | number; label: string }[]
  onSelect: (value: string) => void
  id?: string
}) {
  return (
    <div className="relative inline-flex">
      <select
        id={id}
        aria-label={label}
        value={value}
        onChange={event => onSelect(event.target.value)}
        className="appearance-none cursor-pointer rounded-full border border-zinc-800 bg-zinc-900 py-1.5 pl-4 pr-9 text-sm font-medium text-emerald-400 transition-colors hover:border-zinc-700 focus:border-emerald-500/40 focus:outline-none"
      >
        {options.map(option => (
          <option key={option.value} value={option.value} className="bg-zinc-900 text-zinc-200">
            {option.label}
          </option>
        ))}
      </select>
      <svg
        aria-hidden="true"
        viewBox="0 0 20 20"
        fill="none"
        className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-emerald-400/70"
      >
        <path d="M6 8l4 4 4-4" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </div>
  )
}
