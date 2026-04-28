export type ChangeItem = {
  change_id?: string
  section: string
  before: string
  after: string
  why: string
  company?: string | null
  confidence?: 'high' | 'medium' | 'low'
  signal?: string
}

export type ScoreBreakdown = {
  overall_score: number
  dimensions: Record<string, number>
  summary: Record<string, number>
  notes: string[]
  judgment_notes?: string[]
}

export type PrioritizedBulletChange = {
  evidence_id?: string
  /** Optional stable id for selective apply / review (forward-compatible). */
  change_id?: string
  company?: string | null
  section?: string
  before?: string
  after?: string
  why?: string
  reason?: string
  rank?: number
  emphasis?: 'high' | 'medium' | 'standard' | string
  confidence?: 'high' | 'medium' | 'low'
  signal?: string
  recruiter_note?: string
}

export type StructuredResumeChange = {
  id: string
  section: string
  before: string
  after: string
  reason?: string
  confidence?: 'high' | 'medium' | 'low'
  signal?: string
}

export type WhyThisMatchRow = {
  requirement?: string
  alignment?: string
  why?: string
  best_evidence_text?: string
}

export type GenerateResponse = {
  tailored_resume_text: string
  tailored_resume_sections: Record<string, unknown>
  change_breakdown: ChangeItem[]
  gap_analysis: string[]
  score_breakdown: ScoreBreakdown
  job_signals?: Record<string, unknown> | null
  top_alignment_highlights?: string[]
  top_gaps_to_watch?: string[]
  prioritized_bullet_changes?: PrioritizedBulletChange[]
  structured_changes?: StructuredResumeChange[]
  why_this_matches?: WhyThisMatchRow[]
}
