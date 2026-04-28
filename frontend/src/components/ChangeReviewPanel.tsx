import type { ResumeChange, ResumeChangeSection } from '@/types/resumeChange'

const SECTION_LABELS: Record<ResumeChangeSection, string> = {
  summary: 'Summary',
  experience: 'Experience',
  projects: 'Projects',
  skills: 'Skills',
  other: 'Other',
}

function ConfidenceBadge({ level }: { level: 'high' | 'medium' | 'low' }) {
  const styles =
    level === 'high'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900/60 dark:bg-emerald-950/40 dark:text-emerald-100'
      : level === 'medium'
        ? 'border-amber-200 bg-amber-50 text-amber-950 dark:border-amber-900/50 dark:bg-amber-950/35 dark:text-amber-100'
        : 'border-zinc-200 bg-zinc-100 text-zinc-800 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200'
  return (
    <span className={`inline-flex rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${styles}`}>
      {level} confidence
    </span>
  )
}

export type ChangeReviewPanelProps = {
  title: string
  subtitle?: string
  changes: ResumeChange[]
  selectedChangeIds: Set<string> | ReadonlySet<string>
  onToggleChange: (id: string) => void
  onSelectAll: () => void
  onClearAll: () => void
  hideHeader?: boolean
}

export function ChangeReviewPanel({
  title,
  subtitle,
  changes,
  selectedChangeIds,
  onToggleChange,
  onSelectAll,
  onClearAll,
  hideHeader = false,
}: ChangeReviewPanelProps) {
  const isKeptAsIs = (c: ResumeChange) => {
    const before = (c.before ?? '').trim()
    const after = (c.after ?? '').trim()
    return Boolean(before && after && before === after)
  }

  const selectable = changes.filter((c) => !c.recommendationOnly && !isKeptAsIs(c))
  const selectableCount = selectable.length

  return (
    <div className="rounded-xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      {!hideHeader ? (
        <div className="border-b border-zinc-200 px-5 py-4 dark:border-zinc-800">
          <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">{title}</h3>
          {subtitle ? <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">{subtitle}</p> : null}
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={onSelectAll}
              disabled={!selectableCount}
              className="rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-xs font-medium text-zinc-800 shadow-sm transition hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-100 dark:hover:bg-zinc-700"
            >
              Select all
            </button>
            <button
              type="button"
              onClick={onClearAll}
              disabled={selectedChangeIds.size === 0}
              className="rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-xs font-medium text-zinc-800 shadow-sm transition hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-100 dark:hover:bg-zinc-700"
            >
              Clear all
            </button>
          </div>
        </div>
      ) : null}

      {!changes.length ? (
        <p className="px-5 py-6 text-sm text-zinc-500 dark:text-zinc-400">No suggested changes to review yet.</p>
      ) : (
        <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">
          {changes.map((c, rowIndex) => {
            const rowDomId = `change-row-${rowIndex}`
            const reasonDomId = `reason-${rowIndex}`
            const checked = selectedChangeIds.has(c.id)
            const keptAsIs = isKeptAsIs(c)
            const disabled = Boolean(c.recommendationOnly || keptAsIs)
            return (
              <li
                key={c.id}
                className={`px-5 py-4 ${
                  c.recommendationOnly
                    ? 'bg-amber-50/40 dark:bg-amber-950/15'
                    : 'bg-white dark:bg-zinc-900'
                }`}
              >
                <div className="flex gap-3">
                  <div className="pt-0.5">
                    <input
                      type="checkbox"
                      id={rowDomId}
                      checked={checked}
                      disabled={disabled}
                      onChange={() => onToggleChange(c.id)}
                      className="h-4 w-4 rounded border-zinc-300 text-violet-600 focus:ring-violet-500 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-600 dark:bg-zinc-800"
                      aria-describedby={c.reason ? reasonDomId : undefined}
                    />
                  </div>
                  <div className="min-w-0 flex-1 space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <label
                        htmlFor={rowDomId}
                        className={`text-sm font-medium ${disabled ? 'cursor-default text-zinc-500' : 'cursor-pointer text-zinc-900 dark:text-zinc-100'}`}
                      >
                        {SECTION_LABELS[c.section]}
                      </label>
                      {c.confidence ? <ConfidenceBadge level={c.confidence} /> : null}
                      {c.signal ? (
                        <span className="rounded border border-violet-200 bg-violet-50 px-1.5 py-0.5 font-mono text-[10px] text-violet-900 dark:border-violet-900/50 dark:bg-violet-950/40 dark:text-violet-100">
                          {c.signal}
                        </span>
                      ) : null}
                      {c.recommendationOnly ? (
                        <span className="rounded border border-amber-300 bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-950 dark:border-amber-800 dark:bg-amber-950/50 dark:text-amber-100">
                          Needs manual edit
                        </span>
                      ) : null}
                      {keptAsIs ? (
                        <span className="rounded border border-zinc-300 bg-zinc-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-zinc-800 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100">
                          Kept as-is
                        </span>
                      ) : null}
                      {!keptAsIs && c.confidence === 'high' ? (
                        <span className="rounded border border-violet-300 bg-violet-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-violet-900 dark:border-violet-800 dark:bg-violet-950/50 dark:text-violet-100">
                          Notable change
                        </span>
                      ) : null}
                    </div>

                    {c.recommendationOnly ? (
                      <p className="text-xs leading-relaxed text-amber-900/90 dark:text-amber-100/90">
                        This item is guidance only — there is no exact automatic replacement text. Update your resume
                        yourself if it applies.
                      </p>
                    ) : null}
                    {keptAsIs ? (
                      <p className="text-xs leading-relaxed text-zinc-600 dark:text-zinc-400">
                        No rewrite applied. This line is shown for context so you can confirm the safer keep decision.
                      </p>
                    ) : null}

                    <div className="grid gap-2 sm:grid-cols-2">
                      <div className="rounded-md border border-red-100 bg-red-50/50 px-2.5 py-2 dark:border-red-900/40 dark:bg-red-950/20">
                        <p className="text-[10px] font-semibold uppercase tracking-wide text-red-800/90 dark:text-red-200/90">
                          Before
                        </p>
                        <p className="mt-1 whitespace-pre-wrap text-xs leading-relaxed text-zinc-800 dark:text-zinc-200">
                          {c.before.trim() ? c.before : '—'}
                        </p>
                      </div>
                      <div className="rounded-md border border-emerald-100 bg-emerald-50/50 px-2.5 py-2 dark:border-emerald-900/40 dark:bg-emerald-950/20">
                        <p className="text-[10px] font-semibold uppercase tracking-wide text-emerald-900/90 dark:text-emerald-200/90">
                          After
                        </p>
                        <p className="mt-1 whitespace-pre-wrap text-xs leading-relaxed text-zinc-800 dark:text-zinc-200">
                          {c.after.trim() ? c.after : '—'}
                        </p>
                      </div>
                    </div>

                    {c.reason ? (
                      <p id={reasonDomId} className="text-xs leading-relaxed text-zinc-600 dark:text-zinc-400">
                        <span className="font-medium text-zinc-800 dark:text-zinc-200">Reason: </span>
                        {c.reason}
                      </p>
                    ) : null}
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
