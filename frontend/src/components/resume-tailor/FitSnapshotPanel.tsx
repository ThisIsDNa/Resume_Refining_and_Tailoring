import type { ScoreBreakdown } from '@/types/resumeTailor'

type FitSnapshotPanelProps = {
  score: ScoreBreakdown
}

const dimensionLabel = (key: string) =>
  ({
    requirement_coverage: 'Role fit coverage',
    keyword_alignment: 'Term overlap',
    evidence_strength: 'Line clarity',
    gap_penalty: 'Open questions',
  }[key] ?? key.replace(/_/g, ' '))

export function FitSnapshotPanel({ score }: FitSnapshotPanelProps) {
  const judgment = score.judgment_notes?.length ? score.judgment_notes : score.notes
  const primary = judgment.slice(0, 3)
  const rest = judgment.slice(3)

  return (
    <div className="rounded-xl border border-zinc-100 bg-zinc-50/60 p-4 shadow-none dark:border-zinc-800/80 dark:bg-zinc-900/30">
      <h3 className="text-sm font-medium text-zinc-600 dark:text-zinc-400">Fit snapshot</h3>
      <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-500">Directional read — not a hiring score.</p>
      {primary.length > 0 ? (
        <ul className="mt-3 space-y-1.5 text-sm leading-snug text-zinc-600 dark:text-zinc-400">
          {primary.map((line, i) => (
            <li key={i} className="border-l-2 border-zinc-200 pl-2.5 dark:border-zinc-700">
              {line}
            </li>
          ))}
        </ul>
      ) : null}
      <p className="mt-3 text-2xl font-normal tabular-nums tracking-tight text-zinc-500 dark:text-zinc-500">
        {score.overall_score}
        <span className="ml-1 text-sm font-normal text-zinc-400 dark:text-zinc-600">/100</span>
      </p>
      {rest.length > 0 ? (
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-200">
            More detail
          </summary>
          <ul className="mt-2 space-y-1 text-zinc-600 dark:text-zinc-400">
            {rest.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        </details>
      ) : null}
      <details className="mt-3 border-t border-zinc-200/80 pt-3 dark:border-zinc-700/80">
        <summary className="cursor-pointer text-xs font-medium uppercase tracking-wide text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300">
          How the score splits out
        </summary>
        <dl className="mt-3 space-y-1.5 text-sm">
          {Object.entries(score.dimensions).map(([k, v]) => (
            <div key={k} className="flex justify-between gap-3">
              <dt className="text-zinc-600 dark:text-zinc-400">{dimensionLabel(k)}</dt>
              <dd className="tabular-nums font-medium text-zinc-900 dark:text-zinc-100">{v}</dd>
            </div>
          ))}
        </dl>
      </details>
    </div>
  )
}
