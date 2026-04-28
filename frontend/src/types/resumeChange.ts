export type ResumeChangeFlow = 'refinery' | 'tailor'

export type ResumeChangeSection = 'summary' | 'experience' | 'projects' | 'skills' | 'other'

/**
 * One reviewable unit for Refinery or Tailor. Exact edits carry before/after text;
 * guidance-only rows set `recommendationOnly` and must not invent resume wording.
 */
export type ResumeChange = {
  id: string
  flow: ResumeChangeFlow
  section: ResumeChangeSection
  before: string
  after: string
  reason?: string
  confidence?: 'high' | 'medium' | 'low'
  signal?: string
  selectedByDefault?: boolean
  /**
   * When true, there is no safe exact diff — show as guidance / needs manual edit
   * and exclude from “select all” and export selection semantics until backend supports it.
   */
  recommendationOnly?: boolean
}
