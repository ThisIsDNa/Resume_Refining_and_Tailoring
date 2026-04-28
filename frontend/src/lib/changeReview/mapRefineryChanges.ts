import type { GapAnalysisResponse, GapMatchRow, GapStructuredResumeChange } from '@/types/gapAnalysis'
import type { ResumeChange, ResumeChangeSection } from '@/types/resumeChange'

function inferSection(raw?: string): ResumeChangeSection {
  const s = (raw ?? '').toLowerCase()
  if (s.includes('summary') || s.includes('profile')) return 'summary'
  if (s.includes('experience') || s.includes('work')) return 'experience'
  if (s.includes('project')) return 'projects'
  if (s.includes('skill')) return 'skills'
  return 'other'
}

function inferConfidenceFromStrength(raw?: string | null): 'high' | 'medium' | 'low' | undefined {
  const s = (raw ?? '').toLowerCase()
  if (s.includes('high')) return 'high'
  if (s.includes('medium')) return 'medium'
  if (s.includes('low') || s.includes('weak')) return 'low'
  return undefined
}

function gapRowToChange(row: GapMatchRow, kind: 'weak' | 'missing', index: number): ResumeChange {
  const id = `refinery-${kind}-${row.signal_id || `row-${index}`}`
  const notes = (row.notes ?? '').trim()
  const label = (row.label ?? '').trim()
  const reasonParts = [label, notes].filter(Boolean)
  return {
    id,
    flow: 'refinery',
    section: 'other',
    before: '',
    after: '',
    reason: reasonParts.join(' — ') || 'Strengthen or add evidence for this profile signal.',
    signal: row.signal_id,
    confidence: inferConfidenceFromStrength(row.strength_level),
    recommendationOnly: true,
    selectedByDefault: false,
  }
}

/**
 * Build review rows from Refinery / gap analysis. Does not invent before/after text.
 */
export function buildRefineryResumeChanges(report: GapAnalysisResponse): ResumeChange[] {
  const out: ResumeChange[] = []
  const actions = report.actions
  const meta = report.meta as Record<string, unknown> | undefined
  const structured =
    actions.structured_resume_changes ??
    (meta?.structured_resume_changes as GapStructuredResumeChange[] | undefined)

  const useStructured = Array.isArray(structured) && structured.length > 0

  if (useStructured) {
    structured!.forEach((row, i) => {
      const before = (row.before ?? '').trim()
      const after = (row.after ?? '').trim()
      const id = (row.change_id ?? `refinery-structured-${i}`).trim() || `refinery-structured-${i}`
      const hasPair = Boolean(before && after)
      const conf = row.confidence
      const defaultOn =
        hasPair && (conf === 'high' || conf === undefined || conf === null)
      out.push({
        id,
        flow: 'refinery',
        section: inferSection(row.section),
        before,
        after,
        reason: row.reason,
        confidence: row.confidence,
        signal: row.signal,
        recommendationOnly: !hasPair,
        selectedByDefault: Boolean(defaultOn),
      })
    })
  } else {
    const items = actions.resume_change_items
    const lines = actions.resume_changes ?? []
    const pairs: { id: string; text: string }[] =
      items && items.length === lines.length
        ? lines.map((text, i) => ({ id: items[i]!.id, text }))
        : lines.map((text, i) => ({ id: `refinery-resume-fallback-${i}`, text }))

    for (let i = 0; i < pairs.length; i++) {
      const { id, text } = pairs[i]!
      const t = text.trim()
      if (!t) continue
      out.push({
        id: `refinery-action-${id}`,
        flow: 'refinery',
        section: 'other',
        before: '',
        after: '',
        reason: t,
        recommendationOnly: true,
        selectedByDefault: false,
      })
    }
  }

  const weak = report.gaps.weak_matches ?? []
  weak.forEach((row, i) => out.push(gapRowToChange(row, 'weak', i)))

  const missing = report.gaps.missing_signals ?? []
  missing.forEach((row, i) => out.push(gapRowToChange(row, 'missing', i)))

  return out
}
