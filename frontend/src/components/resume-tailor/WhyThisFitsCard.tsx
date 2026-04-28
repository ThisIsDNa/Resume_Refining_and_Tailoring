import { useState } from 'react'

import type { WhyThisMatchRow } from '@/types/resumeTailor'

type WhyThisFitsCardProps = {
  rows: WhyThisMatchRow[]
}

function alignmentBadge(alignment: string | undefined) {
  if (alignment === 'clear')
    return (
      <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-200">
        Strong match
      </span>
    )
  return (
    <span className="rounded-full bg-zinc-200 px-2 py-0.5 text-xs font-medium text-zinc-700 dark:bg-zinc-700 dark:text-zinc-200">
      Partial match
    </span>
  )
}

export function WhyThisFitsCard({ rows }: WhyThisFitsCardProps) {
  const [open, setOpen] = useState(false)
  const list = rows ?? []
  const visible = open ? list : list.slice(0, 3)
  const hasMore = list.length > 3

  if (list.length === 0) {
    return (
      <div className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
        <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">Why this fits</h3>
        <p className="mt-4 text-sm text-zinc-600 dark:text-zinc-400">
          No row-by-row mapping this time — check the preview and bullets when that’s enough.
        </p>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
      <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">Why this fits</h3>
      <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">Optional — how individual asks line up.</p>
      <ul className="mt-4 space-y-4">
        {visible.map((row, i) => (
          <li key={i} className="rounded-lg border border-zinc-100 p-3 dark:border-zinc-800">
            <div className="flex flex-wrap items-center gap-2">
              {alignmentBadge(row.alignment)}
              <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100">{row.requirement}</p>
            </div>
            {row.why ? <p className="mt-2 text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">{row.why}</p> : null}
            {row.best_evidence_text ? (
              <p className="mt-2 border-l-2 border-zinc-200 pl-3 text-xs leading-relaxed text-zinc-500 dark:border-zinc-500">
                <span className="font-medium not-italic text-zinc-600 dark:text-zinc-400">From your resume: </span>
                <span className="italic">{row.best_evidence_text}</span>
              </p>
            ) : null}
          </li>
        ))}
      </ul>
      {hasMore ? (
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="mt-4 text-sm font-medium text-violet-700 hover:text-violet-800 dark:text-violet-400"
        >
          {open ? 'Show less' : `Show all ${list.length}`}
        </button>
      ) : null}
    </div>
  )
}
