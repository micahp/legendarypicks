interface Props {
  status: string | null | undefined
  compact?: boolean
}

const LABELS: Record<string, { full: string; compact: string }> = {
  QUESTIONABLE: { full: 'Questionable', compact: 'Q' },
  DOUBTFUL: { full: 'Doubtful', compact: 'D' },
  OUT: { full: 'Out', compact: 'O' },
  INJURY_RESERVE: { full: 'Injured reserve', compact: 'IR' },
  INJURY_RESERV: { full: 'Injured reserve', compact: 'IR' },
  SUSPENSION: { full: 'Suspended', compact: 'SUS' },
}

export default function InjuryTag({ status, compact = false }: Props) {
  if (!status || status === 'ACTIVE') return null

  const label = LABELS[status] || {
    full: status.replace(/_/g, ' ').toLowerCase(),
    compact: status,
  }

  return (
    <span
      className={`inline-flex shrink-0 items-center rounded bg-red-900/40 font-bold uppercase tracking-wide text-red-300 ring-1 ring-inset ring-red-800/60 ${
        compact ? 'px-1.5 py-0.5 text-[9px]' : 'px-2 py-1 text-[10px]'
      }`}
      title={label.full}
      aria-label={`Injury status: ${label.full}`}
    >
      {compact ? label.compact : label.full}
    </span>
  )
}
