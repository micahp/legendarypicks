import type { SelectHTMLAttributes } from 'react'

export default function ModelSelect(props: SelectHTMLAttributes<HTMLSelectElement>) {
  const { className = '', children, ...selectProps } = props
  return (
    <span className="relative inline-flex items-center">
      <select
        {...selectProps}
        className={`appearance-none rounded-lg bg-zinc-900 py-2 pl-3 pr-10 text-zinc-100 ${className}`}
      >
        {children}
      </select>
      <svg
        aria-hidden="true"
        viewBox="0 0 20 20"
        fill="none"
        className="pointer-events-none absolute right-3 h-4 w-4 text-zinc-400"
      >
        <path d="m5.5 7.5 4.5 4 4.5-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  )
}
