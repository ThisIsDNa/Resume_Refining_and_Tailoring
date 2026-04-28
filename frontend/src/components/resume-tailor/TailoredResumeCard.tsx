import type { GenerateResponse } from '@/types/resumeTailor'

type TailoredResumeCardProps = {
  response: GenerateResponse
}

export function TailoredResumeCard({ response }: TailoredResumeCardProps) {
  const text = (response.tailored_resume_text || '').trim()

  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
      <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">Tailored preview</h3>
      <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">Draft excerpt — edit before you send.</p>
      {text ? (
        <div className="mt-4 rounded-lg bg-zinc-50 p-4 text-left text-sm leading-relaxed whitespace-pre-wrap text-zinc-800 dark:bg-zinc-900/80 dark:text-zinc-200">
          {text}
        </div>
      ) : (
        <p className="mt-4 text-sm text-zinc-600 dark:text-zinc-400">No preview text returned for this output.</p>
      )}
    </div>
  )
}
