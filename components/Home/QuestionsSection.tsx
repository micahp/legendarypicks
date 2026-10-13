import React from 'react'

const QUESTIONS: [string, string][] = [
  ["Taking a receiver's over?", 'See what happens to his numbers when a teammate is out.'],
  ['Quarterback prop?', 'See how his passing yards change when his top receiver misses.'],
  ['Good number?', 'See how often a player has cleared this exact line, not just his average.'],
  ['Not sure how far to trust it?', 'See the sample size behind every hit rate.'],
  ['Whose projection is better?', "See ours beside ESPN's and how each one did."],
  ['Where do we differ from the line?', "See every NFL game this week with our number beside the market's."],
]

export function SectionHeading({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <h2 id={id} className="mb-[18px] border-b border-zinc-800 pb-2 text-xs font-medium uppercase tracking-[.1em] text-zinc-400">
      {children}
    </h2>
  )
}

export default function QuestionsSection() {
  return (
    <section aria-labelledby="h-q">
      <SectionHeading id="h-q">Questions it answers before you decide</SectionHeading>
      <div className="grid grid-cols-1 gap-3.5 md:grid-cols-3">
        {QUESTIONS.map(([q, a]) => (
          <div key={q} className="rounded-xl border border-zinc-800 bg-zinc-900 px-5 py-[18px]">
            <h3 className="mb-1.5 text-[17px] font-bold">{q}</h3>
            <p className="text-sm text-zinc-400">{a}</p>
          </div>
        ))}
      </div>
    </section>
  )
}
