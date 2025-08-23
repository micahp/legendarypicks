interface ProviderToggleProps {
  provider: 'fastapi' | 'sportsdata' | 'nba_api'
  onChange: (p: 'fastapi' | 'sportsdata' | 'nba_api') => void
  sportsdataAvailable?: boolean
}

export default function ProviderToggle({ provider, onChange, sportsdataAvailable }: ProviderToggleProps) {
  const options: Array<{ key: 'fastapi' | 'sportsdata'; label: string; disabled?: boolean }> = [
    { key: 'fastapi', label: 'FastAPI' },
    { key: 'sportsdata', label: 'SportsData', disabled: !sportsdataAvailable },
  ]

  return (
    <div className="inline-flex rounded-lg overflow-hidden border border-zinc-800">
      {options.map((opt) => (
        <button
          key={opt.key}
          type="button"
          onClick={() => onChange(opt.key)}
          disabled={opt.disabled}
          className={[
            'px-3 py-1.5 text-sm',
            provider === opt.key ? 'bg-emerald-500 text-black font-semibold' : 'bg-zinc-900 text-zinc-200 hover:bg-zinc-800',
            opt.disabled ? 'opacity-40 cursor-not-allowed' : '',
          ].join(' ')}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}


