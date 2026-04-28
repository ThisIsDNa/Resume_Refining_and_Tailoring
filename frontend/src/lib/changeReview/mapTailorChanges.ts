import { prioritizeBulletChangesForDisplay } from '@/lib/resumeTailor/bulletChangeFilters'
import type { ChangeItem, GenerateResponse, PrioritizedBulletChange, StructuredResumeChange } from '@/types/resumeTailor'
import type { ResumeChange, ResumeChangeSection } from '@/types/resumeChange'

function inferSectionFromString(raw: string | undefined): ResumeChangeSection {
  const s = (raw ?? '').toLowerCase()
  if (s.includes('summary') || s.includes('profile')) return 'summary'
  if (s.includes('experience') || s.includes('work')) return 'experience'
  if (s.includes('project')) return 'projects'
  if (s.includes('skill')) return 'skills'
  return 'other'
}

function emphasisToConfidence(emphasis?: string): 'high' | 'medium' | 'low' | undefined {
  const e = (emphasis ?? '').toLowerCase()
  if (e === 'high') return 'high'
  if (e === 'medium') return 'medium'
  if (e === 'standard') return 'medium'
  return undefined
}

function bulletToChange(b: PrioritizedBulletChange, index: number): ResumeChange {
  const before = (b.before ?? '').trim()
  const after = (b.after ?? '').trim()
  const idBase = (b.change_id ?? b.evidence_id ?? `idx-${index}`).toString()
  const id = `tailor-bullet-${idBase}`
  const confidence = b.confidence ?? emphasisToConfidence(b.emphasis)
  const hasExactPair = Boolean(before && after)
  const reason =
    [b.why, b.reason, b.recruiter_note].filter(Boolean).join(' ').trim() || undefined
  return {
    id,
    flow: 'tailor',
    section: inferSectionFromString(b.section),
    before,
    after,
    reason,
    confidence,
    signal: b.signal ?? b.evidence_id,
    recommendationOnly: !hasExactPair,
    selectedByDefault: hasExactPair && b.emphasis === 'high',
  }
}

function changeItemToResumeChange(c: ChangeItem, index: number): ResumeChange {
  const before = (c.before ?? '').trim()
  const after = (c.after ?? '').trim()
  const hasExactPair = Boolean(before && after)
  const section = inferSectionFromString(c.section)
  const id = (c.change_id ?? `tailor-breakdown-${index}-${section}`).toString()
  const conf = c.confidence
  const defaultOn = hasExactPair && (conf === 'high' || conf === undefined)
  return {
    id,
    flow: 'tailor',
    section,
    before,
    after,
    reason: (c.why ?? '').trim() || undefined,
    confidence: c.confidence,
    signal: c.signal ?? c.company ?? undefined,
    recommendationOnly: !hasExactPair,
    selectedByDefault: Boolean(defaultOn),
  }
}

function structuredToResumeChange(c: StructuredResumeChange, index: number): ResumeChange | null {
  const before = (c.before ?? '').trim()
  const after = (c.after ?? '').trim()
  if (!before || !after || before === after) return null
  const confidence = c.confidence
  if (confidence === 'low') return null
  const section = inferSectionFromString(c.section)
  const id = (c.id ?? `tailor-structured-${index}-${section}`).toString()
  return {
    id,
    flow: 'tailor',
    section,
    before,
    after,
    reason: (c.reason ?? '').trim() || undefined,
    confidence,
    signal: c.signal,
    recommendationOnly: false,
    selectedByDefault: confidence === 'high',
  }
}

/**
 * Map Tailor generate response into review rows (summary breakdown + displayed bullets).
 */
export function buildTailorResumeChanges(result: GenerateResponse): ResumeChange[] {
  const structured = (result.structured_changes ?? [])
    .map(structuredToResumeChange)
    .filter((x): x is ResumeChange => Boolean(x))
  if (structured.length > 0) return structured

  const breakdown = (result.change_breakdown ?? []).map(changeItemToResumeChange)
  const bullets = prioritizeBulletChangesForDisplay(result.prioritized_bullet_changes ?? []).map(bulletToChange)
  return [...breakdown, ...bullets]
}
