import { useState } from 'react'

import type { PrioritizedBulletChange } from '@/types/resumeTailor'

type KeyBulletImprovementsCardProps = {
  bullets: PrioritizedBulletChange[]
}

function emphasisStyles(emphasis: string | undefined) {
  if (emphasis === 'high') return 'border-violet-200 bg-violet-50/80 dark:border-violet-900 dark:bg-violet-950/40'
  if (emphasis === 'medium') return 'border-zinc-200 bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900/50'
  return 'border-zinc-100 bg-white dark:border-zinc-800 dark:bg-zinc-950'
}

function topPriorityShell(index: number, emphasis: string | undefined) {
  const base = emphasisStyles(emphasis)
  if (index === 0) return `${base} ring-1 ring-violet-300/50 shadow-sm dark:ring-violet-800/40`
  if (index === 1) return `${base} ring-1 ring-zinc-200/80 dark:ring-zinc-700/50`
  return `${base} opacity-[0.98]`
}

/** Secondary tier — expanded list, visually quieter than top three. */
function secondaryBulletShell(emphasis: string | undefined) {
  return `${emphasisStyles(emphasis)} border-dashed opacity-95`
}

export function KeyBulletImprovementsCard({ bullets }: KeyBulletImprovementsCardProps) {
  const [expanded, setExpanded] = useState(false)
  const list = bullets ?? []
  const top = list.slice(0, 3)
  const more = list.slice(3)
  const hasMore = more.length > 0

  if (list.length === 0) {
    return (
      <div className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
        <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">Top experience-line updates</h3>
        <p className="mt-3 text-sm text-zinc-600 dark:text-zinc-400">
          Nothing to flag line-by-line — your preview above still carries the role-specific wording.
        </p>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
      <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">Top experience-line updates</h3>
      <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">Same facts; clearer emphasis on what matters here.</p>
      <ul className="mt-4 space-y-4">
        {top.map((b, i) => (
          <li
            key={b.evidence_id ?? i}
            className={`rounded-lg border p-4 ${topPriorityShell(i, b.emphasis)}`}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-zinc-900 text-xs font-semibold text-white dark:bg-zinc-100 dark:text-zinc-900"
                  aria-label={`Change ${i + 1} of ${top.length}`}
                >
                  {i + 1}
                </span>
                <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
                  {b.company ? b.company : 'Experience'}
                </span>
              </div>
              {b.emphasis === 'high' ? (
                <span className="rounded-full bg-violet-100 px-2 py-0.5 text-xs font-medium text-violet-800 dark:bg-violet-900/60 dark:text-violet-200">
                  Notable change
                </span>
              ) : null}
            </div>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <div>
                <p className="text-xs font-medium text-zinc-500">Before</p>
                <p className="mt-1 text-sm leading-snug text-zinc-600 line-clamp-6 dark:text-zinc-400">{b.before}</p>
              </div>
              <div>
                <p className="text-xs font-medium text-violet-700 dark:text-violet-300">After</p>
                <p className="mt-1 text-sm font-medium leading-snug text-zinc-900 dark:text-zinc-100">{b.after}</p>
              </div>
            </div>
            {(b.recruiter_note || b.why) && (
              <p className="mt-3 text-xs leading-relaxed text-zinc-600 dark:text-zinc-400">
                {b.recruiter_note || b.why}
              </p>
            )}
          </li>
        ))}
      </ul>
      {hasMore ? (
        <div className="mt-4">
          {expanded ? (
            <ul className="space-y-4 border-t border-zinc-100 pt-4 dark:border-zinc-800">
              {more.map((b, i) => (
                <li
                  key={b.evidence_id ?? `more-${i}`}
                  className={`rounded-lg border p-4 ${secondaryBulletShell(b.emphasis)}`}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-medium text-zinc-500 dark:text-zinc-500">
                      {b.company ? b.company : 'Experience'}
                    </span>
                  </div>
                  <div className="mt-3 grid gap-3 sm:grid-cols-2">
                    <div>
                      <p className="text-xs font-medium text-zinc-500">Before</p>
                      <p className="mt-1 text-sm text-zinc-600 line-clamp-5 dark:text-zinc-400">{b.before}</p>
                    </div>
                    <div>
                      <p className="text-xs font-medium text-violet-700 dark:text-violet-300">After</p>
                      <p className="mt-1 text-sm text-zinc-900 dark:text-zinc-100">{b.after}</p>
                    </div>
                  </div>
                  {(b.recruiter_note || b.why) && (
                    <p className="mt-3 text-xs text-zinc-600 dark:text-zinc-400">{b.recruiter_note || b.why}</p>
                  )}
                </li>
              ))}
            </ul>
          ) : null}
          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            className="mt-3 text-sm font-medium text-violet-700 hover:text-violet-800 dark:text-violet-400 dark:hover:text-violet-300"
          >
            {expanded ? 'Show fewer changes' : `Show ${more.length} more change${more.length === 1 ? '' : 's'}`}
          </button>
        </div>
      ) : null}
    </div>
  )
}
