import { useState } from 'react'

type AlignmentHighlightsCardProps = {
  highlights: string[]
  /** First item shown elsewhere (e.g. above the fold). */
  additionalOnly?: boolean
  /** Any support callout already shown above (softens empty copy). */
  hasSignalAbove?: boolean
}

const VISIBLE = 3

export function AlignmentHighlightsCard({
  highlights,
  additionalOnly,
  hasSignalAbove,
}: AlignmentHighlightsCardProps) {
  const list = highlights ?? []
  const [open, setOpen] = useState(false)
  const shown = open ? list : list.slice(0, VISIBLE)
  const hasMore = list.length > VISIBLE

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
      <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">Strongest alignment</h3>
      <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
        {additionalOnly ? 'More strengths beyond the signal above.' : 'Echo these in a cover note or interview.'}
      </p>
      {list.length === 0 ? (
        <p className="mt-4 text-sm text-zinc-600 dark:text-zinc-400">
          {additionalOnly
            ? 'No additional strengths beyond the signal above.'
            : hasSignalAbove
              ? 'No extra alignment lines beyond the note above — still use the preview and bullets as your guide.'
              : 'No standout strengths surfaced for this posting; the preview and fit notes above still help you decide.'}
        </p>
      ) : (
        <>
          <ul className="mt-4 space-y-2.5">
            {shown.map((h, i) => (
              <li
                key={i}
                className="rounded-lg border border-zinc-100 bg-zinc-50/80 px-3 py-2 text-sm leading-snug text-zinc-800 dark:border-zinc-800 dark:bg-zinc-900/50 dark:text-zinc-200"
              >
                {h}
              </li>
            ))}
          </ul>
          {hasMore ? (
            <button
              type="button"
              onClick={() => setOpen(!open)}
              className="mt-3 text-sm font-medium text-violet-700 hover:text-violet-800 dark:text-violet-400 dark:hover:text-violet-300"
            >
              {open ? 'Show fewer' : `Show ${list.length - VISIBLE} more`}
            </button>
          ) : null}
        </>
      )}
    </div>
  )
}
