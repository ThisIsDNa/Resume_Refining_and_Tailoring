type GapAnalysisCardProps = {
  items: string[]
}

export function GapAnalysisCard({ items }: GapAnalysisCardProps) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-700 dark:bg-zinc-950">
      <h3 className="mb-3 text-sm font-semibold text-zinc-900 dark:text-zinc-100">Gap notes</h3>
      {items.length === 0 ? (
        <p className="text-sm text-zinc-500">No gaps listed.</p>
      ) : (
        <ul className="list-inside list-disc space-y-1 text-sm text-zinc-700 dark:text-zinc-300">
          {items.map((g, i) => (
            <li key={i}>{g}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
