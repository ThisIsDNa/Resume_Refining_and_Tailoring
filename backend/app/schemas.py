"""Stable API contracts for resume tailoring (validated on output)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChangeItem(BaseModel):
    section: str
    before: str
    after: str
    why: str
    company: Optional[str] = None


class ScoreBreakdown(BaseModel):
    overall_score: int = Field(..., ge=0, le=100)
    dimensions: Dict[str, int]
    summary: Dict[str, int]
    notes: List[str]
    judgment_notes: Optional[List[str]] = None


class GenerateResponse(BaseModel):
    tailored_resume_text: str
    tailored_resume_sections: Dict[str, Any]
    change_breakdown: List[ChangeItem]
    gap_analysis: List[str]
    score_breakdown: ScoreBreakdown
    job_signals: Optional[Dict[str, Any]] = None
    top_alignment_highlights: List[str] = Field(default_factory=list)
    top_gaps_to_watch: List[str] = Field(default_factory=list)
    prioritized_bullet_changes: List[Dict[str, Any]] = Field(default_factory=list)
    structured_changes: List[Dict[str, Any]] = Field(default_factory=list)
    why_this_matches: List[Dict[str, Any]] = Field(default_factory=list)


class GapAnalysisResponse(BaseModel):
    """
    Coach-style gap output (deterministic signal layer — independent of DOCX generation).

    ``actions`` may include optional keys for UI/review clients, e.g.
    ``structured_resume_changes`` (list of dicts with change_id, before, after, reason,
    confidence, signal, section). Generators are not required to populate them.
    """

    fit_summary: str
    gaps: Dict[str, Any]
    actions: Dict[str, Any]
    meta: Dict[str, Any] = Field(default_factory=dict)
