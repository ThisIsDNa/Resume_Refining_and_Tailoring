// Tailor page: job-specific resume tailoring, fit preview, and review/apply change selection.
import { type FormEvent, useEffect, useMemo, useState } from 'react'

import { ChangeReviewPanel } from '@/components/ChangeReviewPanel'
import { ContextInput } from '@/components/resume-tailor/ContextInput'
import { FitSnapshotPanel } from '@/components/resume-tailor/FitSnapshotPanel'
import { GenerateButton } from '@/components/resume-tailor/GenerateButton'
import { JobDescriptionInput } from '@/components/resume-tailor/JobDescriptionInput'
import { ResumeUpload } from '@/components/resume-tailor/ResumeUpload'
import { TailoredResumeCard } from '@/components/resume-tailor/TailoredResumeCard'
import {
  ExportDocxValidationError,
  exportDocxResume,
  generateTailoredResume,
} from '@/lib/api/resumeTailor'
import { buildTailorResumeChanges } from '@/lib/changeReview/mapTailorChanges'
import type { GenerateResponse } from '@/types/resumeTailor'

export default function ResumeTailorPage() {
  const [file, setFile] = useState<File | null>(null)
  const [jobDescription, setJobDescription] = useState('')
  const [context, setContext] = useState('')
  const [loading, setLoading] = useState(false)
  const [exportLoading, setExportLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [exportValidationChecks, setExportValidationChecks] = useState<string[] | null>(null)
  const [result, setResult] = useState<GenerateResponse | null>(null)
  const [selectedTailorChangeIds, setSelectedTailorChangeIds] = useState<Set<string>>(() => new Set())

  const tailorChanges = useMemo(() => (result ? buildTailorResumeChanges(result) : []), [result])

  const selectableTailorIds = useMemo(
    () =>
      tailorChanges
        .filter((c) => !c.recommendationOnly && c.before.trim() !== c.after.trim())
        .map((c) => c.id),
    [tailorChanges],
  )

  const estimatedScoreAfterSelection = useMemo(() => {
    const base = Number(result?.score_breakdown?.overall_score ?? 0)
    if (!Number.isFinite(base)) return 0
    let bump = 0
    for (const change of tailorChanges) {
      if (!selectedTailorChangeIds.has(change.id)) continue
      if (change.confidence === 'high') bump += 5
      else if (change.confidence === 'medium') bump += 2
    }
    return Math.min(85, Math.max(0, Math.round(base + bump)))
  }, [result, selectedTailorChangeIds, tailorChanges])

  useEffect(() => {
    if (!result) {
      setSelectedTailorChangeIds(new Set())
      return
    }
    const list = buildTailorResumeChanges(result)
    setSelectedTailorChangeIds(
      new Set(
        list
          .filter((c) => c.selectedByDefault && !c.recommendationOnly && c.before.trim() !== c.after.trim())
          .map((c) => c.id),
      ),
    )
  }, [result])

  async function handleExportDocx() {
    setError(null)
    setExportValidationChecks(null)

    if (!file) {
      setError('Please choose a .docx resume file.')
      return
    }
    if (!jobDescription.trim()) {
      setError('Please paste a job description.')
      return
    }

    const formData = new FormData()
    formData.append('resume_file', file)
    formData.append('job_description', jobDescription)
    formData.append('context', context)

    setExportLoading(true)
    try {
      await exportDocxResume(formData, {
        selectedChangeIds: Array.from(selectedTailorChangeIds),
      })
    } catch (err) {
      if (err instanceof ExportDocxValidationError) {
        setExportValidationChecks(err.checks.length ? err.checks : [err.message])
      } else {
        setError(err instanceof Error ? err.message : 'Export failed.')
      }
    } finally {
      setExportLoading(false)
    }
  }

  function handleToggleTailorChange(id: string) {
    setSelectedTailorChangeIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function handleTailorSelectAll() {
    setSelectedTailorChangeIds(new Set(selectableTailorIds))
  }

  function handleTailorClearAll() {
    setSelectedTailorChangeIds(new Set())
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setExportValidationChecks(null)

    if (!file) {
      setError('Please choose a .docx resume file.')
      return
    }
    if (!jobDescription.trim()) {
      setError('Please paste a job description.')
      return
    }

    const formData = new FormData()
    formData.append('resume_file', file)
    formData.append('job_description', jobDescription)
    formData.append('context', context)

    setLoading(true)
    try {
      const data = await generateTailoredResume(formData)
      setResult(data)
    } catch (err) {
      setResult(null)
      setError(err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-zinc-100 px-4 py-10 text-left dark:bg-zinc-950">
      <div className="mx-auto max-w-6xl space-y-10">
        <header className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">Tailor</h1>
          <p className="max-w-2xl text-sm text-zinc-600 dark:text-zinc-400">
            Upload a resume and a job description. Tailor outputs a job-specific summary, clearer bullets, and a quick
            read on fit — without changing your facts.
          </p>
        </header>

        <form
          onSubmit={handleSubmit}
          aria-busy={loading}
          className="rounded-xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-800 dark:bg-zinc-900"
        >
          <div className="space-y-6">
            <ResumeUpload
              fileName={file?.name ?? null}
              onFileChange={setFile}
              disabled={loading || exportLoading}
            />
            <JobDescriptionInput
              value={jobDescription}
              onChange={setJobDescription}
              disabled={loading || exportLoading}
            />
            <ContextInput value={context} onChange={setContext} disabled={loading || exportLoading} />

            {error ? (
              <div
                role="alert"
                className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/50 dark:text-red-200"
              >
                {error}
              </div>
            ) : null}

            {exportValidationChecks?.length ? (
              <div
                role="alert"
                className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-950 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100"
              >
                <p className="font-medium">DOCX export blocked (validation)</p>
                <ul className="mt-2 list-disc space-y-1 pl-5">
                  {exportValidationChecks.map((line, i) => (
                    <li key={`${i}-${line.slice(0, 120)}`}>{line}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            <div className="flex flex-wrap items-center gap-3">
              <GenerateButton loading={loading} disabled={exportLoading} />
              <button
                type="button"
                onClick={handleExportDocx}
                disabled={loading || exportLoading || !file || !jobDescription.trim()}
                className="inline-flex items-center justify-center rounded-md border border-zinc-300 bg-white px-4 py-2 text-sm font-medium text-zinc-800 shadow-sm transition hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-100 dark:hover:bg-zinc-700"
              >
                {exportLoading ? 'Exporting…' : 'Export DOCX'}
              </button>
              {loading ? (
                <span className="text-sm text-zinc-500 dark:text-zinc-400">Preparing your results…</span>
              ) : null}
              {exportLoading ? (
                <span className="text-sm text-zinc-500 dark:text-zinc-400">Building your .docx…</span>
              ) : null}
            </div>
          </div>
        </form>

        {result ? (
          <section className="space-y-10" aria-live="polite">
            <h2 className="text-xl font-semibold text-zinc-900 dark:text-zinc-50">Your results</h2>

            <div className="grid gap-6 lg:grid-cols-3 lg:items-start">
              <div className="lg:col-span-2">
                <TailoredResumeCard response={result} />
              </div>
              <div className="lg:col-span-1">
                <FitSnapshotPanel score={result.score_breakdown} />
              </div>
            </div>

            <details className="rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
              <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-zinc-800 dark:text-zinc-200">
                Review / Apply Tailoring Changes
              </summary>
              <div className="space-y-3 border-t border-zinc-200 px-5 py-4 dark:border-zinc-800">
                <p className="text-sm text-zinc-700 dark:text-zinc-300">
                  Estimated fit after applying selected changes: <span className="font-semibold">~{estimatedScoreAfterSelection}/100</span>
                </p>
                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                  Summary and experience-line diffs are combined here. Notable changes are tagged, while unchanged lines
                  are marked as kept as-is.
                </p>
                <section className="space-y-3" aria-labelledby="tailor-review-heading">
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={handleTailorSelectAll}
                      disabled={!selectableTailorIds.length}
                      className="rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-xs font-medium text-zinc-800 shadow-sm transition hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-100 dark:hover:bg-zinc-700"
                    >
                      Select all
                    </button>
                    <button
                      type="button"
                      onClick={handleTailorClearAll}
                      disabled={selectedTailorChangeIds.size === 0}
                      className="rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-xs font-medium text-zinc-800 shadow-sm transition hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-100 dark:hover:bg-zinc-700"
                    >
                      Clear all
                    </button>
                  </div>
                  <ChangeReviewPanel
                    title="Apply tailoring changes"
                    subtitle=""
                    changes={tailorChanges}
                    selectedChangeIds={selectedTailorChangeIds}
                    onToggleChange={handleToggleTailorChange}
                    onSelectAll={handleTailorSelectAll}
                    onClearAll={handleTailorClearAll}
                    hideHeader
                  />
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">
                    {selectedTailorChangeIds.size} change{selectedTailorChangeIds.size === 1 ? '' : 's'} selected for
                    export metadata
                  </p>
                </section>
              </div>
            </details>
          </section>
        ) : null}
      </div>
    </div>
  )
}
