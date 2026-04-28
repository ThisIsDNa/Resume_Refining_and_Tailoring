import type { ChangeItem } from '@/types/resumeTailor'

type ChangeBreakdownCardProps = {
  items: ChangeItem[]
  title?: string
  /** Nested inside another card / details — no outer chrome */
  variant?: 'default' | 'embedded'
}

export function ChangeBreakdownCard({
  items,
  title = 'Summary',
  variant = 'default',
}: ChangeBreakdownCardProps) {
  const shell =
    variant === 'embedded'
      ? 'p-4 pt-2'
      : 'rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-950'

  return (
    <div className={shell}>
      {variant === 'default' ? (
        <>
          <h3 className="mb-1 text-base font-semibold text-zinc-900 dark:text-zinc-100">{title}</h3>
          <p className="mb-4 text-xs text-zinc-500 dark:text-zinc-400">
            Before and after for the professional summary only.
          </p>
        </>
      ) : null}
      {items.length === 0 ? (
        <p className="text-sm text-zinc-500">No changes listed.</p>
      ) : (
        <ul className="space-y-4">
          {items.map((c, i) => (
            <li key={i} className="rounded-md border border-zinc-100 p-3 text-sm dark:border-zinc-800">
              {variant === 'default' ? (
                <p className="font-medium capitalize text-zinc-900 dark:text-zinc-100">{c.section}</p>
              ) : items.length > 1 || String(c.section).toLowerCase() !== 'summary' ? (
                <p className="mb-1 text-xs font-medium capitalize text-zinc-500 dark:text-zinc-400">{c.section}</p>
              ) : null}
              {c.company ? <p className="text-xs text-zinc-500">{c.company}</p> : null}
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                <div>
                  <p className="text-xs uppercase tracking-wide text-zinc-500">Before</p>
                  <p className="whitespace-pre-wrap text-zinc-700 dark:text-zinc-300">{c.before}</p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-wide text-zinc-500">After</p>
                  <p className="whitespace-pre-wrap text-zinc-700 dark:text-zinc-300">{c.after}</p>
                </div>
              </div>
              <p className="mt-2 text-zinc-600 dark:text-zinc-400">
                <span className="font-medium text-zinc-800 dark:text-zinc-200">Why: </span>
                {c.why}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
