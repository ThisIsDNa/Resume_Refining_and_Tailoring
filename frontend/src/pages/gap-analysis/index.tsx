// Refinery page: role-based gap analysis, improvement recommendations, and optional export metadata.
import { type FormEvent, type ReactNode, useEffect, useMemo, useState } from 'react'

import { ChangeReviewPanel } from '@/components/ChangeReviewPanel'
import { postGapAnalysis } from '@/lib/api/gapAnalysis'
import { postRefineryExportDocx, RefineryExportValidationError } from '@/lib/api/refineryExport'
import { buildRefineryResumeChanges } from '@/lib/changeReview/mapRefineryChanges'
import { ResumeUpload } from '@/components/resume-tailor/ResumeUpload'
import type { ClassifiedGapRow, GapAnalysisResponse, GapCategory } from '@/types/gapAnalysis'

/** Backend expects this field on every POST; Refinery sends it empty (role-based analysis only). */
const REFINERY_JOB_DESCRIPTION_PAYLOAD = ''

const ROLE_OPTIONS: { value: string; label: string }[] = [
  { value: 'strategy_operations', label: 'Strategy & Operations' },
  { value: 'product_analyst', label: 'Product Analyst' },
  { value: 'bizops', label: 'BizOps' },
]

const GAP_LABELS: Record<GapCategory, string> = {
  resume_fixable: 'Resume fixable',
  project_needed: 'Project needed',
  experience_gap: 'Experience gap',
}

/** Lightweight UI estimate from gap counts (not backend scoring). */
function computeCurrentFitScore(report: GapAnalysisResponse): number {
  const s = report.gaps.strong_matches?.length ?? 0
  const w = report.gaps.weak_matches?.length ?? 0
  const m = report.gaps.missing_signals?.length ?? 0
  const raw = 48 + s * 7 - w * 5 - m * 11
  return Math.max(0, Math.min(100, Math.round(raw)))
}

/**
 * Ceiling 85. Bonus from gap classification rows (not raw weak/missing counts):
 * resume_fixable +5, project_needed +3, experience_gap +1 per classified row.
 */
function computeProjectedFitScore(report: GapAnalysisResponse, current: number): number {
  const classified = report.gaps.classified ?? []
  let bump = 0
  for (const row of classified) {
    const cat = row.gap_category
    if (cat === 'resume_fixable') bump += 5
    else if (cat === 'project_needed') bump += 3
    else if (cat === 'experience_gap') bump += 1
  }
  return Math.min(85, Math.round(current + bump))
}

function renderBoldSegments(text: string): ReactNode[] {
  const nodes: ReactNode[] = []
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  let key = 0
  for (const part of parts) {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      nodes.push(
        <strong key={key++} className="font-semibold text-zinc-900 dark:text-zinc-100">
          {part.slice(2, -2)}
        </strong>,
      )
    } else if (part) {
      nodes.push(<span key={key++}>{part}</span>)
    }
  }
  return nodes
}

function FitSummaryText({ text }: { text: string }) {
  const normalized = (text || '').replace(/\s+/g, ' ').trim()
  return (
    <div className="text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">
      <p className="m-0 whitespace-normal">{renderBoldSegments(normalized)}</p>
    </div>
  )
}

function SectionCard({
  title,
  description,
  children,
}: {
  title: string
  description?: string
  children: ReactNode
}) {
  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">{title}</h2>
      {description ? (
        <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">{description}</p>
      ) : null}
      <div className="mt-4 space-y-4">{children}</div>
    </section>
  )
}

function GapsToClose({ report }: { report: GapAnalysisResponse }) {
  const byId = new Map<string, ClassifiedGapRow>()
  for (const row of report.gaps.classified ?? []) byId.set(row.signal_id, row)
  const rows = (report.gaps.missing_signals ?? []).map((m) => ({
    signal_id: m.signal_id,
    label: m.label,
    rationale: byId.get(m.signal_id)?.rationale ?? m.notes ?? 'No grounded evidence line found in resume text.',
    gap_category: byId.get(m.signal_id)?.gap_category ?? 'experience_gap',
  }))

  if (!rows.length) {
    return (
      <p className="text-sm text-zinc-500 dark:text-zinc-400">
        No immediate closure gaps detected for this role profile.
      </p>
    )
  }
  return (
    <ul className="space-y-3">
      {rows.map((r) => (
        <li
          key={r.signal_id}
          className="rounded-lg border border-zinc-200 bg-zinc-50/70 px-3 py-2.5 dark:border-zinc-800 dark:bg-zinc-950/30"
        >
          <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100">{r.label}</p>
          <p className="mt-0.5 font-mono text-[11px] text-zinc-500 dark:text-zinc-400">{r.signal_id}</p>
          <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-300">
            <span className="font-semibold text-zinc-800 dark:text-zinc-200">{GAP_LABELS[r.gap_category]}</span>
          </p>
          <p className="mt-1 text-xs leading-snug text-zinc-600 dark:text-zinc-400">{r.rationale}</p>
        </li>
      ))}
    </ul>
  )
}

function ActionList({
  title,
  items,
  stableIds,
}: {
  title: string
  items: string[]
  /** Optional backend ids; length may be shorter if UI appends fallback lines. */
  stableIds?: string[]
}) {
  if (!items.length) {
    return (
      <div>
        <h4 className="text-sm font-medium text-zinc-800 dark:text-zinc-200">{title}</h4>
        <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">No items.</p>
      </div>
    )
  }
  return (
    <div>
      <h4 className="text-sm font-medium text-zinc-800 dark:text-zinc-200">{title}</h4>
      <ul className="mt-2 list-disc space-y-1.5 pl-4 text-sm text-zinc-700 dark:text-zinc-300">
        {items.map((line, i) => (
          <li key={stableIds?.[i] ?? `fallback-${i}-${line.slice(0, 40)}`}>{line}</li>
        ))}
      </ul>
    </div>
  )
}

function FitScoresPanel({ report }: { report: GapAnalysisResponse }) {
  const current = computeCurrentFitScore(report)
  const projected = computeProjectedFitScore(report, current)

  return (
    <div className="rounded-lg border border-zinc-100 bg-zinc-50/90 px-4 py-3.5 dark:border-zinc-800 dark:bg-zinc-950/50">
      <div className="space-y-4">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Current score</p>
          <p className="mt-0.5 text-[11px] leading-snug text-zinc-500 dark:text-zinc-400">
            Directional estimate based on resume signals
          </p>
          <p className="mt-1 text-2xl font-semibold tabular-nums text-zinc-900 dark:text-zinc-50">
            {current}
            <span className="text-base font-normal text-zinc-500 dark:text-zinc-400">/100</span>
          </p>
        </div>
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">Estimated score</p>
          <p className="mt-0.5 text-[11px] leading-snug text-zinc-500 dark:text-zinc-400">
            Estimated after strengthening weak and missing signals
          </p>
          <p className="mt-1 text-2xl font-semibold tabular-nums text-violet-800 dark:text-violet-200">
            ~{projected}
            <span className="text-base font-normal text-violet-600/90 dark:text-violet-300/90">/100</span>
          </p>
          <p className="mt-2 text-xs leading-snug text-zinc-600 dark:text-zinc-400">
            Estimated fit after applying recommended improvements: ~{projected}/100
          </p>
        </div>
      </div>
    </div>
  )
}

function RecommendedNextSteps({
  report,
}: {
  report: GapAnalysisResponse
}) {
  const weakN = report.gaps.weak_matches?.length ?? 0
  const missN = report.gaps.missing_signals?.length ?? 0
  const hasGapwork = weakN + missN > 0

  const resumeChanges = [...(report.actions.resume_changes ?? [])]
  const projectSuggestions = [...(report.actions.project_suggestions ?? [])]
  const skillRecommendations = [...(report.actions.skill_recommendations ?? [])]

  const resumeIds = report.actions.resume_change_items?.map((x) => x.id)
  const projectIds = report.actions.project_suggestion_items?.map((x) => x.id)
  const skillIds = report.actions.skill_recommendation_items?.map((x) => x.id)

  const emptyAll =
    !resumeChanges.length && !projectSuggestions.length && !skillRecommendations.length
  if (hasGapwork && emptyAll) {
    resumeChanges.push(
      'Review the gaps below and add one truthful bullet that ties scope, metric, and stakeholder to a verifiable story you can speak to in an interview.',
    )
  }
  const dashboardGuidance =
    'TODO guidance: strengthen reporting/dashboard ownership with a truthful bullet such as "Built and maintained reporting dashboards using Excel and Power BI to track SLA performance, testing progress, and scenario outcomes, providing leadership with visibility into delivery timelines and risks."'

  return (
    <div className="space-y-4">
      <h3 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">Recommended next steps</h3>
      <p className="text-xs text-zinc-500 dark:text-zinc-400">
        Practical moves grounded in what you can truthfully show — scoped to your selected role profile, not a specific
        opening.
      </p>
      <div className="grid gap-8 md:grid-cols-3">
        <ActionList title="Resume changes" items={resumeChanges} stableIds={resumeIds} />
        <ActionList title="Projects" items={projectSuggestions} stableIds={projectIds} />
        <ActionList title="Skills" items={skillRecommendations} stableIds={skillIds} />
      </div>
      <p className="text-xs text-zinc-500 dark:text-zinc-400">{dashboardGuidance}</p>
    </div>
  )
}

export default function GapAnalysisPage() {
  const [file, setFile] = useState<File | null>(null)
  const [roleTemplate, setRoleTemplate] = useState('product_analyst')
  const [loading, setLoading] = useState(false)
  const [exportLoading, setExportLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [report, setReport] = useState<GapAnalysisResponse | null>(null)
  const [selectedRefineryChangeIds, setSelectedRefineryChangeIds] = useState<Set<string>>(() => new Set())

  const refineryChanges = useMemo(() => (report ? buildRefineryResumeChanges(report) : []), [report])

  const selectableRefineryIds = useMemo(
    () =>
      refineryChanges
        .filter((c) => !c.recommendationOnly && c.before.trim() !== c.after.trim())
        .map((c) => c.id),
    [refineryChanges],
  )

  useEffect(() => {
    if (!report) {
      setSelectedRefineryChangeIds(new Set())
      return
    }
    const list = buildRefineryResumeChanges(report)
    setSelectedRefineryChangeIds(
      new Set(
        list
          .filter((c) => c.selectedByDefault && !c.recommendationOnly && c.before.trim() !== c.after.trim())
          .map((c) => c.id),
      ),
    )
  }, [report])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setReport(null)

    if (!file) {
      setError('Please choose a .docx resume file.')
      return
    }

    const formData = new FormData()
    formData.append('resume_file', file)
    formData.append('role_template', roleTemplate)
    formData.append('job_description', REFINERY_JOB_DESCRIPTION_PAYLOAD)

    setLoading(true)
    try {
      const data = await postGapAnalysis(formData)
      setReport(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Refinery request failed.')
    } finally {
      setLoading(false)
    }
  }

  async function handleExportImprovedResume() {
    setError(null)
    if (!file) {
      setError('Please choose a .docx resume file before exporting.')
      return
    }
    const formData = new FormData()
    formData.append('resume_file', file)
    formData.append('role_template', roleTemplate)
    setExportLoading(true)
    try {
      await postRefineryExportDocx(formData, {
        selectedChangeIds: Array.from(selectedRefineryChangeIds),
      })
    } catch (err) {
      if (err instanceof RefineryExportValidationError) {
        const checks = err.checks.length ? err.checks.join('; ') : 'validation failed'
        setError(`${err.message}: ${checks}`)
      } else {
        setError(err instanceof Error ? err.message : 'Refinery export failed.')
      }
    } finally {
      setExportLoading(false)
    }
  }

  function handleToggleRefineryChange(id: string) {
    setSelectedRefineryChangeIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function handleRefinerySelectAll() {
    setSelectedRefineryChangeIds(new Set(selectableRefineryIds))
  }

  function handleRefineryClearAll() {
    setSelectedRefineryChangeIds(new Set())
  }

  return (
    <div className="min-h-screen bg-zinc-100 px-4 py-10 text-left dark:bg-zinc-950">
      <div className="mx-auto max-w-6xl space-y-10">
        <header className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">Refinery</h1>
          <p className="max-w-2xl text-sm text-zinc-600 dark:text-zinc-400">
            Analyze your resume against a target role to identify gaps and improvement opportunities. Guidance is
            role-based — it is not job-specific tailoring (use Tailor for a particular posting).
          </p>
        </header>

        <form
          onSubmit={handleSubmit}
          aria-busy={loading}
          className="rounded-xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-800 dark:bg-zinc-900"
        >
          <div className="space-y-6">
            <ResumeUpload
              id="gap-resume-file"
              fileName={file?.name ?? null}
              onFileChange={setFile}
              disabled={loading || exportLoading}
            />

            <div>
              <label htmlFor="gap-role" className="block text-sm font-medium text-zinc-800 dark:text-zinc-200">
                Target role
              </label>
              <select
                id="gap-role"
                value={roleTemplate}
                onChange={(e) => setRoleTemplate(e.target.value)}
                disabled={loading || exportLoading}
                className="mt-1.5 w-full max-w-md rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 shadow-sm focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500 disabled:opacity-60 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-100"
              >
                {ROLE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>

            {error ? (
              <div
                role="alert"
                className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/50 dark:text-red-200"
              >
                {error}
              </div>
            ) : null}

            <div className="flex flex-wrap items-center gap-3">
              <button
                type="submit"
                disabled={loading || exportLoading || !file}
                className="inline-flex items-center justify-center rounded-md bg-violet-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading ? 'Running…' : 'Run Refinery'}
              </button>
              <button
                type="button"
                onClick={() => void handleExportImprovedResume()}
                disabled={loading || exportLoading || !file}
                className="inline-flex items-center justify-center rounded-md border border-violet-300 bg-violet-50 px-4 py-2 text-sm font-medium text-violet-900 shadow-sm transition hover:bg-violet-100 disabled:cursor-not-allowed disabled:opacity-60 dark:border-violet-800 dark:bg-violet-950/40 dark:text-violet-100 dark:hover:bg-violet-950/70"
              >
                {exportLoading ? 'Exporting…' : 'Export Improved Resume'}
              </button>
              {loading ? (
                <span className="text-sm text-zinc-500 dark:text-zinc-400">Analyzing resume against role profile…</span>
              ) : null}
              {exportLoading && !loading ? (
                <span className="text-sm text-zinc-500 dark:text-zinc-400">Building role-guided .docx…</span>
              ) : null}
            </div>
          </div>
        </form>

        {report ? (
          <div className="space-y-8" aria-live="polite">
            <SectionCard title="Fit snapshot" description="Where you stand now, what gaps matter, and your score range.">
              <div className="space-y-5">
                <FitSummaryText text={report.fit_summary} />
                {report.meta?.role_display_name ? (
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">
                    Profile:{' '}
                    <span className="font-medium text-zinc-700 dark:text-zinc-300">
                      {String(report.meta.role_display_name)}
                    </span>
                  </p>
                ) : null}
                <div className="space-y-5 border-t border-zinc-200 pt-5 dark:border-zinc-700">
                  <GapsToClose report={report} />
                  <FitScoresPanel report={report} />
                </div>
              </div>
            </SectionCard>

            <details className="rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
              <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-zinc-800 dark:text-zinc-200">
                Review suggested improvements
              </summary>
              <div className="space-y-3 border-t border-zinc-200 px-5 py-4 dark:border-zinc-800">
                <ChangeReviewPanel
                  title="Apply improvements"
                  subtitle="Choose which exact edits you want tied to export metadata. Use Export Improved Resume in the form above; export still produces the full role-guided document until the server applies selections."
                  changes={refineryChanges}
                  selectedChangeIds={selectedRefineryChangeIds}
                  onToggleChange={handleToggleRefineryChange}
                  onSelectAll={handleRefinerySelectAll}
                  onClearAll={handleRefineryClearAll}
                />
                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                  {selectedRefineryChangeIds.size} exact change
                  {selectedRefineryChangeIds.size === 1 ? '' : 's'} selected for export metadata.
                </p>
              </div>
            </details>

            <details className="rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
              <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-zinc-800 dark:text-zinc-200">
                Recommended next steps
              </summary>
              <div className="border-t border-zinc-200 px-5 py-4 dark:border-zinc-800">
                <RecommendedNextSteps report={report} />
              </div>
            </details>

            <details className="rounded-xl border border-dashed border-zinc-300 bg-zinc-50/50 dark:border-zinc-700 dark:bg-zinc-900/40">
              <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-zinc-700 dark:text-zinc-300">
                View raw JSON
                <span className="ml-2 font-normal text-zinc-500">(debug)</span>
              </summary>
              <pre className="max-h-[min(480px,50vh)] overflow-auto border-t border-zinc-200 p-4 text-xs leading-relaxed text-zinc-800 dark:border-zinc-800 dark:text-zinc-200">
                {JSON.stringify(report, null, 2)}
              </pre>
            </details>
          </div>
        ) : null}
      </div>
    </div>
  )
}
