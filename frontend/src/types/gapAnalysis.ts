export type GapCategory = 'resume_fixable' | 'project_needed' | 'experience_gap'

export type GapMatchRow = {
  signal_id: string
  label: string
  strength_level?: string | null
  notes?: string
  priority?: string
  required?: boolean
}

export type ClassifiedGapRow = {
  signal_id: string
  label: string
  gap_category: GapCategory
  rationale: string
}

export type ResumeSignalEvidence = {
  signal_id: string
  label: string
  strength_level: string
  source_section: string
  excerpt: string
}

export type GapAnalysisGaps = {
  strong_matches: GapMatchRow[]
  weak_matches: GapMatchRow[]
  missing_signals: GapMatchRow[]
  classified: ClassifiedGapRow[]
  resume_signals?: {
    strengths: string[]
    tools: string[]
    evidence_signals: ResumeSignalEvidence[]
  }
}

export type GapActionItem = {
  id: string
  text: string
}

/** Optional exact diff rows from the backend for selective apply (forward-compatible). */
export type GapStructuredResumeChange = {
  change_id?: string
  before?: string
  after?: string
  reason?: string
  confidence?: 'high' | 'medium' | 'low'
  signal?: string
  section?: string
}

export type GapAnalysisActions = {
  resume_changes: string[]
  project_suggestions: string[]
  skill_recommendations: string[]
  /** Stable ids aligned with the string lists (same length, same order). */
  resume_change_items?: GapActionItem[]
  project_suggestion_items?: GapActionItem[]
  skill_recommendation_items?: GapActionItem[]
  /** When set, prefer these over free-text `resume_changes` for review rows. */
  structured_resume_changes?: GapStructuredResumeChange[]
}

export type GapAnalysisResponse = {
  fit_summary: string
  gaps: GapAnalysisGaps
  actions: GapAnalysisActions
  meta?: Record<string, unknown>
}
