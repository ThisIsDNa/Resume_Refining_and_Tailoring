type GapsToWatchCardProps = {
  gaps: string[]
  fullGapList?: string[]
}

export function GapsToWatchCard({ gaps, fullGapList }: GapsToWatchCardProps) {
  const top = gaps ?? []
  const full = fullGapList ?? []
  const extra = full.filter((g) => !top.some((t) => t.toLowerCase() === g.toLowerCase()))

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
      <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">Gaps to watch</h3>
      <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">Quick sanity check before you apply.</p>
      {top.length === 0 && full.length === 0 ? (
        <p className="mt-4 text-sm text-zinc-600 dark:text-zinc-400">No major gaps flagged — still read the posting yourself.</p>
      ) : top.length === 0 && full.length > 0 ? (
        <p className="mt-4 text-sm text-zinc-600 dark:text-zinc-400">
          Open the list below for the full set of considerations.
        </p>
      ) : (
        <ul className="mt-4 space-y-2.5">
          {top.map((g, i) => (
            <li key={i} className="flex gap-2 text-sm leading-snug text-zinc-700 dark:text-zinc-300">
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400 dark:bg-amber-500" aria-hidden />
              <span>{g}</span>
            </li>
          ))}
        </ul>
      )}
      {extra.length > 0 ? (
        <details className="mt-4 text-sm">
          <summary className="cursor-pointer font-medium text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-200">
            {top.length > 0 ? `Additional notes (${extra.length})` : `All notes (${full.length})`}
          </summary>
          <ul className="mt-2 space-y-2 pl-1 text-zinc-600 dark:text-zinc-400">
            {(top.length > 0 ? extra : full).map((g, i) => (
              <li key={i}>{g}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  )
}
